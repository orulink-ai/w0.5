"""Framed, CRC-checked H.264 over the existing USB UART (4 Mbaud)."""
import struct
import os
import time
import zlib
import base64
import queue
import threading
from collections import deque

import serial
from board_broker import AudioBroker

MAGIC = b'WTCCUV1\0'
HEADER = struct.Struct('<8sIIIII')
MAX_FRAME = 512 * 1024


class FrameParser:
    def __init__(self, on_line=None):
        self.buffer = bytearray()
        self.previous = None
        self.need_idr = True
        self.frames = self.crc_errors = self.sequence_gaps = 0
        self.last_pts_ms = None
        self.on_line = on_line
        self.resyncing = False

    def text(self, data):
        if self.on_line is not None and not self.resyncing:
            for line in data.split(b'\n')[:-1]:
                line = line.rstrip(b'\r')
                if line.startswith((b'MIC_', b'AUDIO_')):
                    self.on_line(line)

    def feed(self, block):
        self.buffer.extend(block)
        frames = []
        while True:
            offset = self.buffer.find(MAGIC)
            if offset < 0:
                newline = self.buffer.rfind(b'\n')
                if newline >= 0:
                    self.text(bytes(self.buffer[:newline + 1]))
                    del self.buffer[:newline + 1]
                partial_control = any(prefix.startswith(self.buffer) or self.buffer.startswith(prefix)
                                      for prefix in (b'MIC_', b'AUDIO_'))
                if not partial_control or len(self.buffer) > 8192:
                    del self.buffer[:max(0, len(self.buffer) - len(MAGIC) + 1)]
                break
            if offset:
                self.text(bytes(self.buffer[:offset]))
                del self.buffer[:offset]
            if len(self.buffer) < HEADER.size:
                break
            _, length, sequence, pts, flags, crc = HEADER.unpack_from(self.buffer)
            if not 1 <= length <= MAX_FRAME or flags not in (0, 1):
                self.resyncing = True
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
                self.resyncing = True
                # Search again: a bad length may have swallowed a valid header.
                del self.buffer[0]
                continue
            del self.buffer[:end]
            self.resyncing = False
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
        self.parser = FrameParser(on_line=self.control_line)
        self.connection = serial.Serial(port=None, baudrate=SERIAL_BAUD, timeout=.1, write_timeout=1)
        self.connection.dtr = False
        self.connection.rts = False
        self.connection.port = port
        self.closed = False
        self.closing = False
        self.error = None
        self.write_lock = threading.RLock()
        self.request_lock = threading.Lock()
        self.replies = queue.Queue(maxsize=64)
        self.frames = queue.Queue(maxsize=8)
        self.microphone = None
        self.sequence = 0
        self.audio_initialized = False
        self.mic_sequence = None
        self.mic_packets = 0
        self.mic_peak = 0
        self.mic_sequence_gaps = self.mic_errors = self.video_queue_drops = 0
        self.max_audio_ack_ms = 0
        self.audio_packets = self.audio_samples = 0
        self.total_audio_ack_ms = 0
        self.audio_retries = self.audio_errors = 0
        self.audio_operation = None
        self.audio_control_errors = deque(maxlen=8)
        self.broker = None
        self.reader = None
        try:
            self.connection.open()
            self.connection.reset_input_buffer()
            self.renew_at = 0
            self.renew()
            self.broker = AudioBroker(port, self)
            self.broker.start()
            self.reader = threading.Thread(target=self.read_serial, daemon=True)
            self.reader.start()
        except Exception:
            self.closed = True
            if self.broker is not None:
                self.broker.close()
            self.connection.close()
            if self.reader is not None:
                self.reader.join(timeout=1)
            raise

    def renew(self):
        if self.closing or self.closed:
            return
        if time.monotonic() >= self.renew_at:
            # A frame transaction holds the write lock while awaiting AUDIO_RX.
            # Never block the UART reader on that lock: it must receive that RX.
            if self.write_lock.acquire(blocking=False):
                try:
                    self.write_all(b'\nVIDEO ON\n')
                    self.renew_at = time.monotonic() + 2
                finally:
                    self.write_lock.release()

    def write_all(self, data):
        offset = 0
        while offset < len(data):
            count = self.connection.write(data[offset:])
            if count is None or count <= 0:
                raise OSError('Serial write made no progress')
            offset += count

    def read_serial(self):
        try:
            while not self.closed:
                self.renew()
                block = self.connection.read(max(1, min(65536, self.connection.in_waiting)))
                for payload in self.parser.feed(block):
                    try:
                        self.frames.put_nowait(payload)
                    except queue.Full:
                        while True:
                            try:
                                self.frames.get_nowait()
                            except queue.Empty:
                                break
                        self.video_queue_drops += 1
                        self.parser.need_idr = True
                        break
        except Exception as exc:
            self.error = OSError(f'USB serial reader failed: {exc}')
            try:
                self.replies.put_nowait(b'AUDIO_ERROR disconnected')
            except queue.Full:
                pass
            if self.broker is not None:
                self.broker.close()

    def subscribe_microphone(self, callback):
        self.microphone = callback

    def control_line(self, line):
        if line.startswith(b'MIC_DATA '):
            try:
                _, sequence, encoded = line.split(b' ', 2)
                sequence = int(sequence)
                pcm = base64.b64decode(encoded, validate=True)
                if not 0 <= sequence < 2**32 or not pcm or len(pcm) > 960 or len(pcm) % 2:
                    raise ValueError('Invalid microphone record')
                if self.mic_sequence is not None and sequence != (self.mic_sequence + 1) & 0xffffffff:
                    self.mic_sequence_gaps += 1
                self.mic_sequence = sequence
                self.mic_packets += 1
                self.mic_peak = max(abs(sample[0]) for sample in struct.iter_unpack('<h', pcm))
                callback = self.microphone
                if callback is not None:
                    callback({'type': 'mic', 'sequence': sequence, 'pcm': encoded.decode('ascii')})
            except (ValueError, UnicodeError):
                self.mic_errors += 1
            return
        if line.startswith((b'AUDIO_', b'MIC_')):
            if line.startswith(b'AUDIO_ERROR'):
                self.audio_errors += 1
                self.audio_control_errors.append(dict(operation=self.audio_operation, sequence=self.sequence,
                                                       error=line[:200].decode('ascii', errors='replace')))
            try:
                self.replies.put_nowait(line)
            except queue.Full:
                try:
                    self.replies.get_nowait()
                except queue.Empty:
                    pass
                self.replies.put_nowait(line)

    def wait_reply(self, expected, timeout=3):
        deadline = time.monotonic() + timeout
        while not self.closed and self.error is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                line = self.replies.get(timeout=min(.1, remaining))
            except queue.Empty:
                continue
            if line.startswith(b'AUDIO_ERROR'):
                raise RuntimeError(line.decode('ascii', errors='replace'))
            if expected.startswith(b'AUDIO_READY ') and line.startswith(b'AUDIO_READY ') and line != expected:
                raise RuntimeError('开发板固件音频配置不匹配：' + line.decode('ascii', errors='replace') +
                                   '；请更新配套音量 80 固件。')
            if line == expected:
                return
        if self.error is not None:
            raise self.error
        raise TimeoutError(f'Board did not acknowledge {expected.decode("ascii")}')

    def audio_request(self, operation, encoded=''):
        with self.request_lock:
            if self.closed or self.closing or self.error is not None:
                raise OSError('Camera USB transport is unavailable')
            self.audio_operation = operation
            while True:
                try:
                    self.replies.get_nowait()
                except queue.Empty:
                    break
            with self.write_lock:
                if operation == 'frame':
                    pcm = base64.b64decode(encoded, validate=True)
                    if not pcm or len(pcm) > 960 or len(pcm) % 2:
                        raise ValueError('PCM packet must contain 1..480 samples')
                    self.sequence = (self.sequence + 1) & 0xffffffff
                    sequence = self.sequence
                    began = time.monotonic()
                    for attempt in range(3):
                        try:
                            self.write_all(f'AUDIO BIN {sequence} {len(pcm)} {zlib.crc32(pcm):08x}\n'.encode())
                            self.wait_reply(f'AUDIO_RX {sequence} {len(pcm)}'.encode())
                            for offset in range(0, len(pcm), 256):
                                self.write_all(pcm[offset:offset + 256])
                            self.wait_reply(f'AUDIO_ACK {sequence}'.encode())
                            break
                        except RuntimeError as exc:
                            # Firmware rejects invalid PCM before enqueue. Only
                            # that explicit negative ACK permits a safe resend;
                            # a missing ACK may have followed audible playback.
                            if str(exc).split(' ', 2)[:2] != ['AUDIO_ERROR', 'invalid_pcm'] or attempt == 2:
                                raise
                            self.audio_retries += 1
                            self.renew()  # A rejected transaction has released UART RX.
                    elapsed = (time.monotonic() - began) * 1000
                    self.max_audio_ack_ms = max(self.max_audio_ack_ms, elapsed)
                    self.total_audio_ack_ms += elapsed
                    self.audio_packets += 1
                    self.audio_samples += len(pcm) // 2
                else:
                    commands = {
                        'start': (b'AUDIO START\n', b'AUDIO_READY rate=24000 volume=80'),
                        'mic-start': (b'MIC START\n', b'MIC_READY rate=24000 channels=1'),
                        'mic-stop': (b'MIC STOP\n', b'MIC_STOPPED'),
                        'stop': (b'AUDIO STOP\n', b'AUDIO_STOPPED'),
                        'end': (b'AUDIO END\n', b'AUDIO_DONE'),
                    }
                    if operation not in commands:
                        raise ValueError('Unknown audio operation')
                    command, expected = commands[operation]
                    self.write_all(command)
                    self.wait_reply(expected, timeout=8 if operation == 'start' else 3)
                    if operation == 'start':
                        self.audio_initialized = True

    def read_frames(self):
        if self.error is not None:
            raise self.error
        try:
            result = [self.frames.get(timeout=.1)]
        except queue.Empty:
            return []
        while len(result) < 8:
            try:
                result.append(self.frames.get_nowait())
            except queue.Empty:
                break
        return result

    def close(self):
        if self.closed or self.closing:
            return
        self.closing = True
        if self.broker is not None:
            self.broker.close()
        try:
            if self.connection.is_open:
                with self.write_lock:
                    if self.audio_initialized:
                        self.write_all(b'\nMIC STOP\nAUDIO STOP\n')
                    self.write_all(b'\nVIDEO OFF\n')
        except (OSError, serial.SerialException):
            pass
        finally:
            self.closed = True
            self.connection.close()
            if self.reader is not None and self.reader is not threading.current_thread():
                self.reader.join(timeout=1)


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
                    decode_errors=self.decode_errors, camera_pts_ms=parser.last_pts_ms,
                    mic_sequence_gaps=self.source.mic_sequence_gaps,
                    mic_packets=self.source.mic_packets,
                    mic_last_sequence=self.source.mic_sequence,
                    mic_peak=self.source.mic_peak,
                    mic_errors=self.source.mic_errors, video_queue_drops=self.source.video_queue_drops,
                    audio_packets=self.source.audio_packets,
                    audio_retries=self.source.audio_retries,
                    audio_errors=self.source.audio_errors,
                    audio_control_errors=list(self.source.audio_control_errors),
                    audio_seconds=round(self.source.audio_samples / 24000, 3),
                    mean_audio_ack_ms=round(self.source.total_audio_ack_ms / self.source.audio_packets, 1)
                    if self.source.audio_packets else 0,
                    max_audio_ack_ms=round(self.source.max_audio_ack_ms, 1))

    def release(self):
        self.source.close()
        self.pending.clear()
        self.frames.clear()
        self.codec = None
