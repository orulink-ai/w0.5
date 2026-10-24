"""Bounded loopback HTTP bridge. Commands are accepted into the UI queue only."""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


MAX_BODY = 4096
MAX_STATUS = 128 * 1024
MAX_JPEG = 2 * 1024 * 1024


def validate_command(value):
    if not isinstance(value, dict):
        raise ValueError('命令必须为 JSON 对象')
    action = value.get('action')
    fields = {
        'start': {'volume'}, 'listen': {'volume'}, 'cancel': set(),
        'configure': {'faceTrigger', 'enabled', 'volume', 'mode'},
        'camera-start': set(), 'camera-stop': set(),
        'test-speaker': set(),
        'rotate': {'turns'}, 'mirror': {'enabled'},
    }
    if not isinstance(action, str) or action not in fields:
        raise ValueError('未知控制命令')
    if set(value) - (fields[action] | {'action'}):
        raise ValueError('未知命令字段')
    if 'volume' in value and (type(value['volume']) is not int or value['volume'] != 80):
        raise ValueError('开发板音量固定为 80')
    for field in ('faceTrigger', 'enabled'):
        if field in value and type(value[field]) is not bool:
            raise ValueError(field + ' 必须为布尔值')
    if value.get('faceTrigger') is False:
        raise ValueError('麦克风必须在人脸稳定后触发，不能关闭人脸门控')
    if 'mode' in value and value['mode'] not in ('single', 'continuous'):
        raise ValueError('mode 必须为 single 或 continuous')
    if action == 'rotate' and (type(value.get('turns')) is not int or not 0 <= value['turns'] <= 3):
        raise ValueError('turns 必须为 0 到 3')
    if action == 'mirror' and 'enabled' not in value:
        raise ValueError('mirror 需要 enabled')
    if action == 'configure' and len(value) == 1:
        raise ValueError('configure 需要配置字段')
    return value


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class RobotConsoleServer:
    def __init__(self, on_command, port=8791):
        self.on_command = on_command
        self.port = port
        self._condition = threading.Condition()
        self._status = b'{"connected":false,"revision":0}'
        self._jpeg = None
        self._frame = 0
        self._streams = threading.BoundedSemaphore(2)
        self._closed = False
        self._server = None
        self._thread = None

    def start(self):
        if self._server is not None:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(3)
                self.body_consumed = False

            def log_message(self, *_):
                pass

            def local(self):
                try:
                    host = urlsplit('http://' + self.headers.get('Host', '')).hostname
                    if host not in ('127.0.0.1', 'localhost', '::1'):
                        return False
                    origin = self.headers.get('Origin')
                    if origin:
                        parsed = urlsplit(origin)
                        return (parsed.scheme in ('http', 'https')
                                and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
                                and not parsed.username and not parsed.password)
                    return True
                except ValueError:
                    return False

            def reply(self, status, value):
                if status >= 400 and self.command == 'POST' and not self.body_consumed:
                    # Drain small rejected bodies so closing the connection
                    # does not reset Windows TCP before the error is received.
                    try:
                        length = int(self.headers.get('Content-Length', '0'))
                        if not self.headers.get('Transfer-Encoding') and 0 < length <= 2 * MAX_BODY:
                            self.body_consumed = True
                            self.rfile.read(length)
                    except (ValueError, OSError):
                        pass
                body = json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self.local():
                    self.reply(403, {'error': '仅允许本机控制台访问'})
                    return
                if self.path == '/api/robot/status':
                    with owner._condition:
                        status = owner._status
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(status)))
                    self.end_headers()
                    self.wfile.write(status)
                elif self.path == '/api/robot/camera.mjpeg':
                    if not owner._streams.acquire(blocking=False):
                        self.reply(503, {'error': '预览连接数量已满'})
                        return
                    try:
                        self.send_response(200)
                        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        frame = -1
                        while True:
                            with owner._condition:
                                owner._condition.wait_for(
                                    lambda: owner._closed or owner._frame != frame, timeout=1)
                                if owner._closed:
                                    return
                                if owner._frame == frame:
                                    continue
                                frame = owner._frame
                                jpeg = owner._jpeg
                            if jpeg is None:
                                continue
                            self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                                             + str(len(jpeg)).encode('ascii') + b'\r\n\r\n'
                                             + jpeg + b'\r\n')
                            self.wfile.flush()
                    except (OSError, TimeoutError):
                        pass
                    finally:
                        owner._streams.release()
                else:
                    self.reply(404, {'error': '接口不存在'})

            def do_POST(self):
                if not self.local():
                    self.reply(403, {'error': '仅允许本机控制台访问'})
                    return
                if self.path != '/api/robot/control':
                    self.reply(404, {'error': '接口不存在'})
                    return
                if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                    self.reply(415, {'error': '需要 application/json'})
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_BODY:
                        self.reply(413, {'error': '控制命令大小无效'})
                        return
                    self.body_consumed = True
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError('请求不完整')
                    command = validate_command(json.loads(body))
                except (ValueError, UnicodeDecodeError):
                    self.reply(400, {'error': '控制命令无效，请检查字段；音量固定为 80'})
                    return
                try:
                    accepted = owner.on_command(command)
                    if accepted is False:
                        raise queue.Full()
                except queue.Full:
                    self.reply(503, {'error': '控制命令队列已满，请稍后重试'})
                    return
                except Exception:
                    self.reply(503, {'error': '控制命令未能加入队列'})
                    return
                self.reply(202, {'accepted': True, 'action': command['action']})

        self._server = _Server(('127.0.0.1', self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def publish(self, status, jpeg=None):
        encoded = json.dumps(status, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_STATUS:
            raise ValueError('设备状态超出大小限制')
        if jpeg is not None and (not isinstance(jpeg, bytes) or len(jpeg) > MAX_JPEG):
            raise ValueError('JPEG 超出大小限制或格式错误')
        with self._condition:
            self._status = encoded
            if jpeg is not None:
                self._jpeg = jpeg
                self._frame += 1
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
