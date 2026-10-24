"""USB wire records: split reads, interleaved logs and corruption recovery."""
import unittest
import zlib
import threading
from fractions import Fraction
from unittest.mock import patch
import av
import numpy as np

from serial_video import FrameParser, SerialVideo, UsbCapture, HEADER, MAGIC, MAX_FRAME


def packet(payload, sequence, idr=False, pts=0):
    header = HEADER.pack(MAGIC, len(payload), sequence, pts, int(idr), 0)
    crc = zlib.crc32(payload, zlib.crc32(header[8:24]))
    return header[:-4] + crc.to_bytes(4, 'little') + payload


class SerialVideoTests(unittest.TestCase):
    def test_usb_handle_loss_returns_failure_for_worker_reconnect(self):
        with patch('serial_video.SerialVideo') as source:
            source.return_value.read_frames.side_effect = OSError('USB handle removed')
            cap = UsbCapture('COM15', threading.Event())
            try:
                self.assertEqual(cap.read(), (False, None))
            finally:
                cap.release()
            source.return_value.close.assert_called_once()

    def test_complete_h264_frame_decodes_without_waiting_for_next_packet(self):
        encoder = av.CodecContext.create('libx264', 'w')
        encoder.width, encoder.height = 160, 96
        encoder.pix_fmt = 'yuv420p'
        encoder.time_base = Fraction(1, 14)
        encoder.options = {'preset': 'ultrafast', 'tune': 'zerolatency'}
        packets = encoder.encode(av.VideoFrame.from_ndarray(np.zeros((96, 160, 3), np.uint8), format='bgr24'))
        self.assertEqual(len(packets), 1)
        stop = threading.Event()
        with patch('serial_video.SerialVideo') as constructor:
            source = constructor.return_value
            source.read_frames.return_value = [bytes(packets[0])]
            capture = UsbCapture('COM15', stop)
            try:
                ok, frame = capture.read()
                self.assertTrue(ok)
                self.assertEqual(frame.shape, (96, 160, 3))
                source.read_frames.assert_called_once()
                self.assertEqual(capture.decode_errors, 0)
                stop.set()
                self.assertEqual(capture.read(), (False, None))
            finally:
                capture.release()
            source.close.assert_called_once()

    def test_passive_port_open_keepalive_and_stop(self):
        class Port:
            is_open = False
            in_waiting = 0
            def __init__(self): self.commands = []
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def write(self, data): self.commands.append(data); return len(data)
            def read(self, count): return packet(b'frame', 0, True)
            def close(self): self.is_open = False
        port = Port()
        with patch('serial_video.serial.Serial', return_value=port), patch('serial_video.time.monotonic', return_value=10):
            source = SerialVideo('COM15')
            self.assertFalse(port.dtr)
            self.assertFalse(port.rts)
            self.assertEqual(source.read_frames(), [b'frame'])
            self.assertEqual(port.commands, [b'\nVIDEO ON\n'])
            source.renew_at = 0
            source.renew()
            source.close()
            source.close()
        self.assertEqual(port.commands, [b'\nVIDEO ON\n', b'\nVIDEO ON\n', b'\nVIDEO OFF\n'])
        self.assertFalse(port.is_open)

    def test_split_records_and_console_logs_preserve_exact_payload(self):
        first = b'\0\0\0\1' + bytes(range(256)) * 100
        second = b'\0\0\0\1' + b'predicted' * 50
        wire = b'boot log\n' + packet(first, 8, True, 100) + b'INFO\n' + packet(second, 9, pts=172)
        parser = FrameParser()
        output = []
        for i in range(0, len(wire), 31):
            output.extend(parser.feed(wire[i:i+31]))
        self.assertEqual(output, [first, second])
        self.assertEqual(parser.frames, 2)
        self.assertEqual(parser.last_pts_ms, 172)
        self.assertEqual(parser.crc_errors, 0)

    def test_crc_failure_and_missing_frame_wait_for_idr(self):
        bad = bytearray(packet(b'corrupt', 2))
        bad[-1] ^= 1
        parser = FrameParser()
        output = parser.feed(packet(b'first', 1, True) + bad + packet(b'unsafe', 3)
                             + packet(b'recover', 4, True) + packet(b'next', 5))
        self.assertEqual(output, [b'first', b'recover', b'next'])
        self.assertEqual(parser.crc_errors, 1)
        self.assertEqual(parser.sequence_gaps, 1)

    def test_bounds_noise_and_sequence_wrap(self):
        parser = FrameParser()
        parser.feed(b'x' * 1000000)
        self.assertLess(len(parser.buffer), len(MAGIC))
        bogus = HEADER.pack(MAGIC, MAX_FRAME + 1, 0, 0, 1, 0)
        output = parser.feed(bogus + packet(b'last', 0xffffffff, True) + packet(b'wrap', 0))
        self.assertEqual(output, [b'last', b'wrap'])
        self.assertEqual(parser.sequence_gaps, 0)


if __name__ == '__main__':
    unittest.main()
