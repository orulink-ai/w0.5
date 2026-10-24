"""Exercise real chunk framing and decoder cancellation on an owned local server."""
import http.server
import shutil
import subprocess
import threading
import time
import unittest

from video_source import NetworkCapture, camera_http


class NetworkTests(unittest.TestCase):
    def start_server(self, payload, repeat=1, delay=0):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                try:
                    for _ in range(repeat):
                        for offset in range(0, len(payload), 97):
                            block = payload[offset:offset+97]
                            self.wfile.write(f'{len(block):x}\r\n'.encode()+block+b'\r\n')
                            self.wfile.flush()
                        if delay:
                            time.sleep(delay)
                    self.wfile.write(b'0\r\n\r\n')
                except (OSError, ConnectionError):
                    pass

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}/fixture.h264'

    def test_chunked_body_is_byte_exact(self):
        payload = bytes(range(256))*31
        url = self.start_server(payload)
        conn, response, fast_ack = camera_http(url)
        try:
            received = bytearray()
            while True:
                block = response.read1(311)
                if not block:
                    break
                received.extend(block)
            self.assertEqual(bytes(received), payload)
            self.assertIsInstance(fast_ack, bool)
        finally:
            response.close()
            conn.close()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is not installed')
    def test_live_decode_and_stop_release(self):
        generated = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi',
            '-i', 'testsrc=size=160x96:rate=10', '-frames:v', '10', '-c:v', 'libx264',
            '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
            '-f', 'h264', 'pipe:1'], capture_output=True, timeout=10, check=True).stdout
        url = self.start_server(generated, repeat=100, delay=.05)
        stop = threading.Event()
        capture = NetworkCapture(url, stop)
        try:
            ok, frame = capture.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape, (540, 960, 3))
            begin = time.monotonic()
            stop.set()
            capture.release()
            self.assertLess(time.monotonic()-begin, 3)
            self.assertIsNotNone(capture.process.poll())
            self.assertFalse(capture.feeder.is_alive())
        finally:
            if not capture.closed.is_set():
                capture.release()


if __name__ == '__main__':
    unittest.main()
