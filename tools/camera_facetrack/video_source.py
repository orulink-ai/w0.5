"""Bounded, cancellable FFmpeg capture for the IMX708 HTTP H.264 stream."""
import os
import ctypes
import http.client
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse

import numpy as np


def camera_http(url, timeout=4):
    """Direct HTTP with per-socket ACK tuning; no global TCP/registry changes."""
    parts = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
    connection = cls(parts.hostname, parts.port, timeout=timeout)
    try:
        connection.connect()
        connection.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
        fast_ack = False
        if os.name == 'nt':
            winsock = ctypes.WinDLL('Ws2_32.dll')
            winsock.WSAIoctl.argtypes = [ctypes.c_size_t, ctypes.c_ulong, ctypes.c_void_p,
                ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_void_p]
            frequency, received = ctypes.c_ulong(1), ctypes.c_ulong()
            fast_ack = winsock.WSAIoctl(connection.sock.fileno(), 0x98000017,
                ctypes.byref(frequency), 4, None, 0, ctypes.byref(received), None, None) == 0
        path = urllib.parse.urlunsplit(('', '', parts.path or '/', parts.query, ''))
        connection.request('GET', path, headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f'摄像头 HTTP {response.status}')
        return connection, response, fast_ack
    except Exception:
        connection.close()
        raise


class NetworkCapture:
    def __init__(self, url, stop):
        self.process = None
        self.closed = threading.Event()
        self.last_frame_at = time.monotonic()
        self.log = None
        self.connection = None
        self.response = None
        self.feeder = None
        self.bytes_received = 0
        self.decoded_frames = 0
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise ValueError('请输入 HTTP/HTTPS 视频流地址。')
        binary = shutil.which('ffmpeg')
        if not binary:
            raise RuntimeError('网络摄像头需要 FFmpeg，请将 ffmpeg.exe 所在目录加入 PATH。')
        # A fixed output canvas avoids making video depend on a separate HTTP
        # metadata server. Preserve source aspect ratio with letterboxing.
        self.width, self.height = 960, 540
        directory = Path(__file__).resolve().parent / 'runtime'
        directory.mkdir(exist_ok=True)
        self.log = (directory / 'network-decoder.log').open('ab', buffering=0)
        command = [binary, '-hide_banner', '-loglevel', 'warning', '-nostdin',
                   '-probesize', '8192', '-analyzeduration', '0', '-fpsprobesize', '0',
                   '-flags', 'low_delay', '-avioflags', 'direct', '-threads', '1']
        if parts.path.endswith('.h264'):
            command += ['-f', 'h264']
        command += ['-blocksize', '4096', '-i', 'pipe:0', '-an', '-vf',
                    'scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2',
                    '-fps_mode', 'passthrough', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
        try:
            # At this site the link cannot sustain 600 kbit/s. Halve the target
            # frame rate and bitrate together to retain the per-frame budget.
            if parts.path in ('/stream.h264', '/stream.mp4'):
                for path in ('/skip?n=4', '/rate?kbit=300'):
                    if stop.is_set():
                        raise InterruptedError('连接已取消')
                    control = urllib.parse.urlunsplit((parts.scheme, parts.hostname, path.split('?')[0], path.split('?')[1], ''))
                    try:
                        conn, response, _ = camera_http(control, timeout=2)
                        try:
                            self.log.write(response.read(512))
                        finally:
                            response.close()
                            conn.close()
                    except OSError as exc:
                        self.log.write(f'Control unavailable: {exc}\n'.encode())
            if stop.is_set():
                raise InterruptedError('连接已取消')
            self.connection, self.response, fast_ack = camera_http(url, timeout=5)
            self.log.write(f'\nStream={parts.path} fast_ack={fast_ack}\n'.encode())
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=self.log,
                                            creationflags=subprocess.CREATE_NO_WINDOW,
                                            env={**os.environ, 'http_proxy': '', 'https_proxy': '',
                                                 'HTTP_PROXY': '', 'HTTPS_PROXY': ''})
        except Exception:
            if self.response is not None:
                self.response.close()
            if self.connection is not None:
                self.connection.close()
            self.log.close()
            raise

        def receive():
            try:
                while not stop.is_set() and not self.closed.is_set():
                    # read1 returns available HTTP body bytes without waiting
                    # for a large block, and HTTPResponse handles chunk framing.
                    block = self.response.read1(65536)
                    if not block:
                        break
                    self.bytes_received += len(block)
                    self.process.stdin.write(block)
                    self.process.stdin.flush()
            except (OSError, ValueError, http.client.HTTPException) as exc:
                if not self.closed.is_set() and not stop.is_set():
                    self.log.write(f'HTTP receive ended: {exc}\n'.encode())
            finally:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
        self.feeder = threading.Thread(target=receive, daemon=True)
        self.feeder.start()

        def cancel():
            while not self.closed.wait(.1):
                if stop.is_set() or time.monotonic() - self.last_frame_at > 15:
                    if self.process.poll() is None:
                        self.process.terminate()
                    return
        threading.Thread(target=cancel, daemon=True).start()

    def read(self):
        remaining = self.width * self.height * 3
        blocks = []
        while remaining:
            block = self.process.stdout.read(remaining)
            if not block:
                return False, None
            blocks.append(block)
            remaining -= len(block)
        self.last_frame_at = time.monotonic()
        self.decoded_frames += 1
        return True, np.frombuffer(b''.join(blocks), np.uint8).reshape(self.height, self.width, 3).copy()

    def diagnostics(self):
        result = {'transport': 'wifi',
                  'received_bytes': self.bytes_received, 'decoded_frames': self.decoded_frames}
        return result

    def release(self):
        self.closed.set()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process.stdout.close()
        if self.connection is not None and self.connection.sock is not None:
            try:
                self.connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.feeder is not None:
            self.feeder.join(timeout=6)
        if self.response is not None:
            self.response.close()
        if self.connection is not None:
            self.connection.close()
        if self.log is not None:
            self.log.close()
