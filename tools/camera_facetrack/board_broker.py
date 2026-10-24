"""Memory-only, authenticated loopback access to a camera-owned audio UART.

The broker never opens a serial port. Its owner is the single SerialVideo
reader and every audio operation shares that owner's write/response locks.
"""
import base64
import hmac
import ipaddress
import json
import queue
import secrets
import socket
import socketserver
import threading
import time

_registry = {}
_registry_lock = threading.Lock()


def get_audio_broker(port):
    """Return (loopback TCP URL, ephemeral token), or None when unavailable."""
    with _registry_lock:
        broker = _registry.get(str(port).upper())
        return (broker.url, broker.token) if broker is not None else None


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False


class _Lines:
    def __init__(self, connection):
        self.connection = connection
        self.pending = bytearray()

    def read(self):
        while True:
            offset = self.pending.find(b'\n')
            if offset >= 0:
                if offset > 4096:
                    raise ValueError('Audio request exceeds 4096 bytes')
                result = bytes(self.pending[:offset])
                del self.pending[:offset + 1]
                return result
            if len(self.pending) > 4096:
                raise ValueError('Audio request exceeds 4096 bytes')
            block = self.connection.recv(4096)
            if not block:
                raise EOFError('Audio client disconnected')
            self.pending.extend(block)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        broker = self.server.broker
        connection = self.request
        if not ipaddress.ip_address(self.client_address[0]).is_loopback:
            return
        if not broker.client_lock.acquire(blocking=False):
            connection.sendall(b'{"id":0,"ok":false,"error":"Audio client already connected"}\n')
            return
        outgoing = queue.Queue(maxsize=128)
        stopped = threading.Event()
        authenticated = False
        initialized = False
        writer = None

        def emit(value):
            try:
                outgoing.put_nowait(value)
            except queue.Full:
                stopped.set()  # Never block the UART reader behind a slow client.
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def write_messages():
            while not stopped.is_set():
                try:
                    value = outgoing.get(timeout=.1)
                except queue.Empty:
                    continue
                try:
                    connection.sendall((json.dumps(value) + '\n').encode('utf-8'))
                except OSError:
                    stopped.set()
                    return

        with broker.connections_lock:
            broker.connections.add(connection)
        try:
            # Audio requests and microphone events are small, frequent records.
            # Do not delay an ACK behind another unacknowledged TCP segment.
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connection.settimeout(.2)
            lines = _Lines(connection)
            deadline = time.monotonic() + 3
            handshake = None
            while handshake is None and not broker.stopped.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Audio authentication timed out')
                try:
                    handshake = json.loads(lines.read())
                except socket.timeout:
                    continue
            if (not isinstance(handshake, dict) or handshake.get('id') != 0
                    or not isinstance(handshake.get('token'), str)
                    or not hmac.compare_digest(handshake['token'], broker.token)):
                connection.sendall(b'{"id":0,"ok":false,"error":"Invalid audio token"}\n')
                return
            authenticated = True
            broker.owner.audio_request('start')
            initialized = True
            broker.owner.audio_request('mic-stop')
            broker.owner.audio_request('stop')
            broker.owner.subscribe_microphone(emit)
            connection.sendall(b'{"id":0,"ok":true,"volume":80,"sampleRate":24000}\n')
            writer = threading.Thread(target=write_messages, daemon=True)
            writer.start()
            while not stopped.is_set() and not broker.stopped.is_set():
                try:
                    request = json.loads(lines.read())
                except socket.timeout:
                    continue
                if (not isinstance(request, dict) or type(request.get('id')) is not int
                        or not 0 < request['id'] < 2**31):
                    raise ValueError('Invalid audio request id')
                identifier = request['id']
                try:
                    operation = request.get('op')
                    if operation not in ('frame', 'mic-start', 'mic-stop', 'stop', 'end'):
                        raise ValueError('Unknown audio operation')
                    pcm = request.get('pcm', '')
                    if not isinstance(pcm, str):
                        raise ValueError('PCM must be base64')
                    if operation == 'frame':
                        raw = base64.b64decode(pcm, validate=True)
                        if not raw or len(raw) > 960 or len(raw) % 2:
                            raise ValueError('PCM packet must contain 1..480 samples')
                    broker.owner.audio_request(operation, pcm)
                    emit({'id': identifier, 'ok': True})
                except Exception as exc:
                    emit({'id': identifier, 'ok': False, 'error': str(exc)})
        except Exception as exc:
            if authenticated and writer is None:
                try:
                    connection.sendall((json.dumps({'id': 0, 'ok': False, 'error': str(exc)}) + '\n').encode())
                except OSError:
                    pass
        finally:
            stopped.set()
            if initialized:
                broker.owner.subscribe_microphone(None)
                if not broker.stopped.is_set():
                    for operation in ('mic-stop', 'stop'):
                        try:
                            broker.owner.audio_request(operation)
                        except Exception:
                            pass
            with broker.connections_lock:
                broker.connections.discard(connection)
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            if writer is not None:
                writer.join(timeout=1)
            broker.client_lock.release()


class AudioBroker:
    def __init__(self, port, owner):
        self.serial_port = str(port).upper()
        self.owner = owner
        self.token = secrets.token_urlsafe(32)
        self.server = _Server(('127.0.0.1', 0), _Handler)
        self.server.broker = self
        self.port = self.server.server_address[1]
        self.url = f'tcp://127.0.0.1:{self.port}'
        self.client_lock = threading.Lock()
        self.connections_lock = threading.Lock()
        self.connections = set()
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.1), daemon=True)
        self.thread.start()
        with _registry_lock:
            _registry[self.serial_port] = self

    def close(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        with _registry_lock:
            if _registry.get(self.serial_port) is self:
                del _registry[self.serial_port]
        with self.connections_lock:
            for connection in self.connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread is not None:
            self.server.shutdown()
        self.server.server_close()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
