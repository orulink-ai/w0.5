"""Framed, CRC-checked H.264 over the existing USB UART (4 Mbaud)."""
import struct
import os
import time
import zlib
from collections import deque

import serial

MAGIC = b'WTCCUV1\0'
HEADER = struct.Struct('<8sIIIII')
MAX_FRAME = 512 * 1024


class FrameParser:
    def __init__(self):
        self.buffer = bytearray()
        self.previous = None
        self.need_idr = True
        self.frames = self.crc_errors = self.sequence_gaps = 0
        self.last_pts_ms = None

    def feed(self, block):
        self.buffer.extend(block)
        frames = []
        while True:
            offset = self.buffer.find(MAGIC)
            if offset < 0:
                del self.buffer[:max(0, len(self.buffer) - len(MAGIC) + 1)]
                break
            if offset:
                del self.buffer[:offset]
            if len(self.buffer) < HEADER.size:
                break
            _, length, sequence, pts, flags, crc = HEADER.unpack_from(self.buffer)
            if not 1 <= length <= MAX_FRAME or flags not in (0, 1):
                del self.buffer[0]
                continue
            end = HEADER.size + length
            if len(self.buffer) < end:
                break
            payload = bytes(self.buffer[HEADER.size:end])
            actual = zlib.crc32(payload, zlib.crc32(self.buffer[8:24]))
            if actual != crc:
                self.crc_errors += 1
                self.need_idr = True
                # Search again: a bad length may have swallowed a valid header.
                del self.buffer[0]
                continue
            del self.buffer[:end]
            if self.previous is not None and sequence != (self.previous + 1) & 0xffffffff:
                self.sequence_gaps += 1
                self.need_idr = True
            self.previous = sequence
            if flags & 1:
                self.need_idr = False
            if self.need_idr:
                continue
            self.frames += 1
            self.last_pts_ms = pts
            frames.append(payload)
        return frames


SERIAL_BAUD = int(os.environ.get("WTCC_SERIAL_BAUD", "4000000"))
if SERIAL_BAUD not in (2000000, 4000000):
    raise ValueError("WTCC_SERIAL_BAUD must be 2000000 or 4000000")


class SerialVideo:
    def __init__(self, port):
        self.parser = FrameParser()
        self.connection = serial.Serial(port=None, baudrate=SERIAL_BAUD, timeout=.1, write_timeout=1)
        self.connection.dtr = False
        self.connection.rts = False
        self.connection.port = port
        self.closed = False
        try:
            self.connection.open()
            self.connection.reset_input_buffer()
            self.renew_at = 0
            self.renew()
        except Exception:
            self.connection.close()
            raise

    def renew(self):
        if time.monotonic() >= self.renew_at:
            self.connection.write(b'\nVIDEO ON\n')
            self.renew_at = time.monotonic() + 2

    def read_frames(self):
        self.renew()
        block = self.connection.read(max(1, min(65536, self.connection.in_waiting)))
        return self.parser.feed(block)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.connection.is_open:
                self.connection.write(b'\nVIDEO OFF\n')
        except (OSError, serial.SerialException):
            pass
        finally:
            self.connection.close()


class UsbCapture:
    """Decode each complete access unit immediately, without a pipe/parser queue."""
    def __init__(self, port, stop):
        import av
        self.av = av
        self.stop = stop
        self.codec = self.new_codec()
        self.source = SerialVideo(port)
        self.pending = deque()
        self.frames = deque()
        self.received_bytes = self.decoded_frames = self.decode_errors = 0
        self.last_frame_at = time.monotonic()

    def new_codec(self):
        codec = self.av.CodecContext.create('h264', 'r')
        codec.thread_count = 1
        return codec

    def read(self):
        while not self.stop.is_set():
            if self.frames:
                frame = self.frames.popleft()
                self.decoded_frames += 1
                self.last_frame_at = time.monotonic()
                return True, frame.to_ndarray(format='bgr24')
            if time.monotonic() - self.last_frame_at > 15:
                return False, None
            if not self.pending:
                try:
                    self.pending.extend(self.source.read_frames())
                except (OSError, serial.SerialException):
                    # A USB unplug/re-enumeration invalidates the Windows
                    # handle. Let the worker close it and reopen the port.
                    return False, None
                continue
            payload = self.pending.popleft()
            self.received_bytes += len(payload)
            try:
                self.frames.extend(self.codec.decode(self.av.Packet(payload)))
            except self.av.error.FFmpegError:
                self.decode_errors += 1
                self.codec = self.new_codec()
                self.source.parser.need_idr = True
                self.pending.clear()
        return False, None

    def diagnostics(self):
        parser = self.source.parser
        return dict(transport='usb', decoder='pyav-packet', received_bytes=self.received_bytes,
                    decoded_frames=self.decoded_frames, wire_frames=parser.frames,
                    crc_errors=parser.crc_errors, sequence_gaps=parser.sequence_gaps,
                    decode_errors=self.decode_errors, camera_pts_ms=parser.last_pts_ms)

    def release(self):
        self.source.close()
        self.pending.clear()
        self.frames.clear()
        self.codec = None
