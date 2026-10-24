"""USB wire records: split reads, interleaved logs and corruption recovery."""
import unittest
import zlib
import threading
import queue
import base64
import time
import struct
from fractions import Fraction
from unittest.mock import Mock, patch
import av
import numpy as np

from serial_video import FrameParser, SerialVideo, UsbCapture, HEADER, MAGIC, MAX_FRAME
from board_broker import get_audio_broker


def packet(payload, sequence, idr=False, pts=0):
    header = HEADER.pack(MAGIC, len(payload), sequence, pts, int(idr), 0)
    crc = zlib.crc32(payload, zlib.crc32(header[8:24]))
    return header[:-4] + crc.to_bytes(4, 'little') + payload


class SerialVideoTests(unittest.TestCase):
    def test_wrong_firmware_volume_is_reported_without_waiting_for_timeout(self):
        source = SerialVideo.__new__(SerialVideo)
        source.closed = False
        source.error = None
        source.replies = queue.Queue()
        source.replies.put(b'AUDIO_READY rate=24000 volume=60')
        with self.assertRaisesRegex(RuntimeError, '音量 80'):
            source.wait_reply(b'AUDIO_READY rate=24000 volume=80')

    def test_only_explicit_pcm_rejection_can_resend_a_frame(self):
        for failure, expected_attempts in ((RuntimeError('AUDIO_ERROR invalid_pcm received=958 expected=960'), 2),
                                           (TimeoutError('Missing AUDIO_ACK'), 1),
                                           (RuntimeError('AUDIO_ERROR write'), 1)):
            with self.subTest(failure=str(failure)):
                source = SerialVideo.__new__(SerialVideo)
                source.closed = source.closing = False
                source.error = None
                source.request_lock, source.write_lock = threading.Lock(), threading.RLock()
                source.replies = queue.Queue()
                source.sequence = source.audio_packets = source.audio_samples = source.audio_retries = 0
                source.max_audio_ack_ms = source.total_audio_ack_ms = 0
                source.write_all, source.renew = Mock(), Mock()
                source.wait_reply = Mock(side_effect=[None, failure, None, None])
                if expected_attempts == 2:
                    source.audio_request('frame', 'AAEAAg==')
                    self.assertEqual(source.audio_packets, 1)
                    self.assertEqual(source.audio_retries, 1)
                    source.renew.assert_called_once()
                else:
                    with self.assertRaises(type(failure)):
                        source.audio_request('frame', 'AAEAAg==')
                    self.assertEqual(source.audio_packets, 0)
                    self.assertEqual(source.audio_retries, 0)
                    source.renew.assert_not_called()
                headers = [args[0] for args, _ in source.write_all.call_args_list if args[0].startswith(b'AUDIO BIN ')]
                self.assertEqual(len(headers), expected_attempts)
                self.assertTrue(all(header == headers[0] for header in headers))

    def test_audio_statistics_measure_successful_uart_roundtrips_only(self):
        source = SerialVideo.__new__(SerialVideo)
        source.closed = source.closing = False
        source.error = None
        source.request_lock, source.write_lock = threading.Lock(), threading.RLock()
        source.replies = queue.Queue()
        source.sequence = source.audio_packets = source.audio_samples = 0
        source.max_audio_ack_ms = source.total_audio_ack_ms = 0
        source.write_all, source.wait_reply = Mock(), Mock()
        with patch('serial_video.time.monotonic', side_effect=[10, 10.015, 20, 20.03, 30]):
            source.audio_request('frame', base64.b64encode(b'\0' * 960).decode())
            source.audio_request('frame', base64.b64encode(b'\0' * 480).decode())
            source.wait_reply.side_effect = TimeoutError('No UART credit')
            with self.assertRaises(TimeoutError):
                source.audio_request('frame', 'AAAAAA==')
        self.assertEqual(source.audio_packets, 2)
        self.assertEqual(source.audio_samples, 720)
        self.assertAlmostEqual(source.total_audio_ack_ms, 45)
        self.assertAlmostEqual(source.max_audio_ack_ms, 30)

    def test_full_size_mic_packets_survive_ragged_video_reads_and_report_levels(self):
        class Port:
            is_open = False
            in_waiting = 0
            def __init__(self): self.input = queue.Queue()
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def close(self): self.is_open = False
            def write(self, data): return len(data)
            def read(self, _):
                try: return self.input.get(timeout=.01)
                except queue.Empty: return b''
        port, microphones, peaks = Port(), [], []
        completed = threading.Event()
        def microphone(value):
            microphones.append(value)
            peaks.append(source.mic_peak)
            if value['sequence'] == 99: completed.set()
        with patch('serial_video.serial.Serial', return_value=port):
            source = SerialVideo('MIC-TEST-COM')
            try:
                source.subscribe_microphone(microphone)
                wire = bytearray()
                loud = struct.pack('<hh', -32768, 32767) * 240
                quiet = struct.pack('<h', -12) * 480
                for index in range(100):
                    if index % 10 == 0:
                        wire.extend(packet(b'\0\0\0\1\nMIC_DATA 999 bad\n' + bytes(range(256)) * 20,
                                           index // 10, True))
                    pcm = quiet if index == 99 else loud
                    wire.extend(f'MIC_DATA {index} '.encode() + base64.b64encode(pcm) + b'\r\n')
                sizes, offset, count = (1, 7, 13, 29, 4096, 65536), 0, 0
                while offset < len(wire):
                    length = sizes[count % len(sizes)]
                    port.input.put(bytes(wire[offset:offset + length]))
                    offset += length
                    count += 1
                self.assertTrue(completed.wait(2))
                self.assertEqual(len(microphones), 100)
                self.assertEqual(source.mic_packets, 100)
                self.assertEqual(source.mic_sequence, 99)
                self.assertEqual(source.mic_peak, 12)  # Latest packet, not a sticky lifetime maximum.
                self.assertEqual(peaks[0], 32768)
                self.assertEqual(source.mic_sequence_gaps, 0)
                self.assertEqual(source.mic_errors, 0)
                self.assertEqual(base64.b64decode(microphones[0]['pcm']), loud)
                source.control_line(b'MIC_DATA 100 not-base64!')
                self.assertEqual(source.mic_errors, 1)
                self.assertEqual(source.mic_packets, 100)
                self.assertEqual(source.mic_peak, 12)
                for index in range(12):
                    source.control_line(f'AUDIO_ERROR invalid_pcm received={index} expected=960'.encode())
                with patch('serial_video.SerialVideo', return_value=source):
                    capture = UsbCapture('MIC-TEST-COM', threading.Event())
                    stats = capture.diagnostics()
                self.assertEqual(stats['mic_packets'], 100)
                self.assertEqual(stats['mic_last_sequence'], 99)
                self.assertEqual(stats['mic_peak'], 12)
                self.assertEqual(stats['audio_errors'], 12)
                self.assertEqual(len(stats['audio_control_errors']), 8)
                self.assertIn('received=11', stats['audio_control_errors'][-1]['error'])
                self.assertNotIn('pcm', stats['audio_control_errors'][-1])
                self.assertNotIn('pcm', stats)
            finally:
                source.close()

    def test_video_backlog_is_bounded_and_recovers_only_at_next_idr(self):
        class Port:
            is_open = False
            in_waiting = 0
            def __init__(self): self.input = queue.Queue()
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def close(self): self.is_open = False
            def write(self, data): return len(data)
            def read(self, _):
                try: return self.input.get(timeout=.01)
                except queue.Empty: return b''
        port = Port()
        with patch('serial_video.serial.Serial', return_value=port):
            source = SerialVideo('QUEUE-COM')
            try:
                port.input.put(b''.join(packet(f'old-{index}'.encode(), index, index == 0)
                                        for index in range(9)))
                deadline = time.monotonic() + 1
                while not source.video_queue_drops and time.monotonic() < deadline:
                    threading.Event().wait(.01)
                self.assertEqual(source.video_queue_drops, 1)
                self.assertTrue(source.frames.empty())
                port.input.put(packet(b'unsafe predicted frame', 9) + packet(b'recovered IDR', 10, True))
                self.assertEqual(source.read_frames(), [b'recovered IDR'])
                self.assertLessEqual(source.frames.qsize(), 8)
            finally:
                source.close()

    def test_shared_audio_waits_for_rx_and_keeps_video_and_mic_reading(self):
        class Port:
            is_open = False
            in_waiting = 0
            def __init__(self):
                self.commands = []
                self.input = queue.Queue()
                self.audio = bytearray()
                self.expected = 0
                self.sequence = 0
                self.rx_observed = False
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def close(self): self.is_open = False
            def write(self, data):
                self.commands.append(data)
                if self.expected:
                    if not self.rx_observed:
                        raise AssertionError('PCM arrived before the UART reader received AUDIO_RX')
                    self.audio.extend(data)
                    if len(self.audio) == self.expected:
                        self.expected = 0
                        self.input.put(packet(b'continued video', 2, True) +
                                       f'AUDIO_ACK {self.sequence}\n'.encode())
                elif data.startswith(b'AUDIO BIN '):
                    _, _, sequence, size, _ = data.split()
                    self.sequence, self.expected = int(sequence), int(size)
                    self.input.put(f'AUDIO_RX {self.sequence} {self.expected}\n'.encode())
                elif data == b'AUDIO START\n': self.input.put(b'AUDIO_READY rate=24000 volume=80\n')
                elif data == b'MIC START\n':
                    self.input.put(b'MIC_READY rate=24000 channels=1\nMIC_DATA 1 AAEAAg==\n')
                elif data == b'\nVIDEO ON\n': self.input.put(packet(b'initial video', 1, True))
                return len(data)
            def read(self, _):
                try:
                    data = self.input.get(timeout=.02)
                except queue.Empty:
                    return b''
                if data.startswith(b'AUDIO_RX '): self.rx_observed = True
                return data
        port = Port()
        microphone, received = [], threading.Event()
        def capture(value):
            microphone.append(value)
            received.set()
        with patch('serial_video.serial.Serial', return_value=port):
            source = SerialVideo('FAKE-COM')
            try:
                self.assertEqual(source.read_frames(), [b'initial video'])
                source.subscribe_microphone(capture)
                source.audio_request('start')
                source.audio_request('mic-start')
                self.assertTrue(received.wait(1))
                self.assertEqual(microphone[0]['pcm'], 'AAEAAg==')
                pcm = bytes(range(256)) * 3 + bytes(range(192))
                source.audio_request('frame', base64.b64encode(pcm).decode())
                self.assertEqual(source.audio_packets, 1)
                self.assertEqual(source.audio_samples, 480)
                self.assertGreaterEqual(source.total_audio_ack_ms, 0)
                with patch('serial_video.SerialVideo', return_value=source):
                    stats = UsbCapture('FAKE-COM', threading.Event()).diagnostics()
                self.assertEqual(stats['audio_packets'], 1)
                self.assertEqual(stats['audio_seconds'], .02)
                self.assertEqual(stats['mean_audio_ack_ms'], stats['max_audio_ack_ms'])
                self.assertEqual(source.read_frames(), [b'continued video'])
                self.assertEqual(bytes(port.audio), pcm)
                self.assertNotIn(b'\nVIDEO OFF\n', port.commands)
                self.assertFalse(any(b'AUDIO BAUD' in item for item in port.commands))
                self.assertIsNotNone(get_audio_broker('fake-com'))
            finally:
                source.close()
        self.assertIsNone(get_audio_broker('fake-com'))

    def test_disconnected_reader_unregisters_broker_and_wakes_pending_audio(self):
        class Port:
            is_open = False
            in_waiting = 0
            def __init__(self):
                self.input = queue.Queue()
                self.end_requested = threading.Event()
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def close(self): self.is_open = False
            def write(self, data):
                if data == b'AUDIO END\n': self.end_requested.set()
                return len(data)
            def read(self, _):
                try:
                    value = self.input.get(timeout=.02)
                except queue.Empty:
                    return b''
                if isinstance(value, Exception): raise value
                return value
        port, errors = Port(), []
        with patch('serial_video.serial.Serial', return_value=port):
            source = SerialVideo('ERROR-COM')
            try:
                def request():
                    try: source.audio_request('end')
                    except Exception as exc: errors.append(exc)
                worker = threading.Thread(target=request)
                worker.start()
                self.assertTrue(port.end_requested.wait(1))
                port.input.put(OSError('USB unplugged'))
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertTrue(errors)
                with self.assertRaises(OSError): source.read_frames()
                deadline = time.monotonic() + 1
                while get_audio_broker('ERROR-COM') is not None and time.monotonic() < deadline:
                    threading.Event().wait(.01)
                self.assertIsNone(get_audio_broker('ERROR-COM'))
            finally:
                source.close()

    def test_mixed_records_never_parse_control_text_inside_video_payload(self):
        lines = []
        parser = FrameParser(on_line=lines.append)
        payload = b'\0\0\0\1\nMIC_DATA 9 ZmFrZQ==\nAUDIO_ACK 99\n'
        wire = packet(payload, 1, True) + b'MIC_DATA 1 AAEAAg==\nAUDIO_ACK 2\n'
        frames = []
        for start in range(0, len(wire), 3):
            frames.extend(parser.feed(wire[start:start + 3]))
        self.assertEqual(frames, [payload])
        self.assertEqual(lines, [b'MIC_DATA 1 AAEAAg==', b'AUDIO_ACK 2'])

    def test_corrupt_video_cannot_forge_an_audio_ack_during_resync(self):
        lines = []
        parser = FrameParser(on_line=lines.append)
        corrupt = bytearray(packet(b'\nAUDIO_ACK 123\n', 2))
        corrupt[-1] ^= 1
        frames = parser.feed(packet(b'first', 1, True) + corrupt +
                             b'AUDIO_ACK 124\n' + packet(b'recovered', 3, True) + b'AUDIO_ACK 125\n')
        self.assertEqual(frames, [b'first', b'recovered'])
        self.assertEqual(lines, [b'AUDIO_ACK 125'])

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
            def __init__(self): self.commands = []; self.frame_sent = False
            def open(self): self.is_open = True
            def reset_input_buffer(self): pass
            def write(self, data): self.commands.append(data); return len(data)
            def read(self, count):
                if not self.frame_sent:
                    self.frame_sent = True
                    return packet(b'frame', 0, True)
                threading.Event().wait(.001)
                return b''
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
