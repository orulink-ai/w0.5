#!/usr/bin/env python3
"""Local telemetry, target staging, and acknowledged bounded PB5 control."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

import serial
from serial.tools import list_ports
from telemetry import TelemetryStore
from commands import CommandError, validate_target
from enable_commands import validate_enabled
from motor_commands import validate_action
from closed_loop_commands import validate_foc

STATIC = Path(__file__).resolve().parent / "static"


class SerialReader:
    def __init__(self, store):
        self.store = store
        self._control = threading.Lock()
        self._stop = None
        self._thread = None
        self._serial = None

    @staticmethod
    def ports():
        return [{"device": p.device, "description": p.description}
                for p in list_ports.comports()]

    def _disconnect(self):
        if self._stop:
            self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = self._serial = None
        self.store.set_connection(False)

    def disconnect(self):
        with self._control:
            self._disconnect()

    def connect(self, device):
        with self._control:
            if device not in [p["device"] for p in self.ports()]:
                raise ValueError("串口不存在，请刷新设备列表。")
            self._disconnect()
            try:
                connection = serial.Serial(device, 115200, timeout=0.2,
                                           write_timeout=1, exclusive=True)
            except (OSError, serial.SerialException) as error:
                self.store.set_connection(False, error=f"无法打开串口：{error}")
                raise ValueError("无法打开串口，请关闭其他串口监视器后重试。") from error
            self._stop = threading.Event()
            self._serial = connection
            self.store.set_connection(True, device)
            self._thread = threading.Thread(target=self._read,
                                            args=(connection, self._stop), daemon=True)
            self._thread.start()

    def send_target(self, degrees):
        degrees = validate_target(degrees)
        with self._control:
            if self.store.closed_loop.snapshot()["supported"]:
                raise CommandError("当前为闭环固件，请使用闭环工作台；旧控制入口已禁用。")
            if self._serial is None or not self._serial.is_open:
                raise CommandError("串口未连接。")
            request_id, packet = self.store.control.begin(
                degrees, self.store.snapshot()["signal"] == "valid")
            try:
                if self._serial.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("Incomplete target write")
            except (OSError, serial.SerialException) as error:
                self.store.control.fail(request_id, f"串口发送失败：{error}")
                raise CommandError("串口发送失败，目标未确认。") from error
            self.store.control.wait(request_id)

    def send_enable(self, enabled):
        enabled = validate_enabled(enabled)
        with self._control:
            if self.store.closed_loop.snapshot()["supported"]:
                raise CommandError("当前为闭环固件，请使用闭环工作台；旧控制入口已禁用。")
            if self._serial is None or not self._serial.is_open:
                raise CommandError("串口未连接。")
            request_id, packet = self.store.enable.begin(
                enabled, self.store.snapshot()["signal"] == "valid")
            try:
                if self._serial.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("Incomplete enable write")
            except (OSError, serial.SerialException) as error:
                self.store.enable.fail(request_id, f"串口发送失败：{error}")
                raise CommandError("串口发送失败，使能状态未确认。") from error
            self.store.enable.wait(request_id)

    def send_motor(self, action):
        action = validate_action(action)
        with self._control:
            if self.store.closed_loop.snapshot()["supported"]:
                raise CommandError("当前为闭环固件，请使用闭环工作台；旧控制入口已禁用。")
            if self._serial is None or not self._serial.is_open:
                raise CommandError("串口未连接。")
            state = self.store.snapshot()
            request_id, packet = self.store.motor.begin(
                action, state["signal"] == "valid", state["enable"])
            try:
                if self._serial.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("Incomplete motor write")
            except (OSError, serial.SerialException) as error:
                self.store.motor.fail(request_id, f"串口发送失败：{error}")
                raise CommandError("串口发送失败，电机请求未确认。") from error
            self.store.motor.wait(request_id)

    @staticmethod
    def _foc_packet(packet, motor_id):
        return packet if motor_id == 1 else packet.replace(b'FOC,', b'FOC2,', 1)

    def send_foc(self, payload, motor_id=1):
        payload = validate_foc(payload)
        channel = self.store.foc_channel(motor_id)
        # One transport lock, independent request/lease state per motor.
        # ACK waits stay outside this lock so either motor can STOP promptly.
        with self._control:
            if self._serial is None or not self._serial.is_open:
                raise CommandError("串口未连接。")
            state = self.store.snapshot()
            valid = (state['signal'] == 'valid' if motor_id == 1 else
                     state['encoders'][1]['signal'] == 'valid')
            request_id, packet = channel.begin(payload, valid)
            packet = self._foc_packet(packet, motor_id)
            try:
                if self._serial.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("Incomplete FOC write")
            except (OSError, serial.SerialException) as error:
                channel.fail(request_id, f"串口发送失败：{error}")
                raise CommandError("串口发送失败，闭环请求未确认。") from error
        channel.wait(request_id)

    def send_foc_heartbeat(self, payload, motor_id=1):
        if type(payload) is not dict or set(payload) != {'run_id'}:
            raise CommandError("心跳只接受 run_id。")
        channel = self.store.foc_channel(motor_id)
        run_id = payload['run_id']
        with self._control:
            if self._serial is None or not self._serial.is_open:
                channel.clear_owner()
                raise CommandError("串口未连接，运动租约已失效。")
            packet = self._foc_packet(channel.heartbeat(run_id), motor_id)
            try:
                if self._serial.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("Incomplete FOC heartbeat write")
            except (OSError, serial.SerialException) as error:
                channel.clear_owner()
                raise CommandError("运动心跳发送失败，租约已释放。") from error
            channel.heartbeat_written(run_id)
        return {"ok": True, "run_id": run_id}

    def _read(self, connection, stop):
        pending = bytearray()
        try:
            while not stop.is_set():
                chunk = connection.read(min(max(connection.in_waiting, 1), 4096))
                pending.extend(chunk)
                while b"\n" in pending:
                    raw, _, pending = pending.partition(b"\n")
                    if not stop.is_set():
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            self.store.consume(line)
                if len(pending) > 4096:
                    pending.clear()
        except (OSError, serial.SerialException, TypeError) as error:
            if not stop.is_set():
                self.store.set_connection(False, error=f"串口连接中断：{error}")
        finally:
            connection.close()


def make_server(reader, store, port=8840):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def respond(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/ports":
                self.respond(200, reader.ports())
            elif path == "/api/state":
                self.respond(200, store.snapshot())
            elif path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    while True:
                        data = json.dumps(store.snapshot(), ensure_ascii=False, allow_nan=False)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(0.2)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                files = {"/": ("index.html", "text/html; charset=utf-8"),
                         "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                         "/api.js": ("api.js", "application/javascript; charset=utf-8"),
                         "/components/legacy-controls.js": ("components/legacy-controls.js", "application/javascript; charset=utf-8"),
                         "/components/closed-loop.js": ("components/closed-loop.js", "application/javascript; charset=utf-8"),
                         "/components/lease-keeper.js": ("components/lease-keeper.js", "application/javascript; charset=utf-8"),
                         "/components/live-position.js": ("components/live-position.js", "application/javascript; charset=utf-8"),
                         "/components/encoder-readouts.js": ("components/encoder-readouts.js", "application/javascript; charset=utf-8"),
                         "/components/motor-workbench.js": ("components/motor-workbench.js", "application/javascript; charset=utf-8"),
                         "/style.css": ("style.css", "text/css; charset=utf-8"),
                         "/robot-viewer.js": ("robot-viewer.js", "application/javascript; charset=utf-8"),
                         "/robot-finishes.mjs": ("robot-finishes.mjs", "application/javascript; charset=utf-8"),
                         "/robot-rig.js": ("robot-rig.js", "application/javascript; charset=utf-8"),
                         "/robot-motion.mjs": ("robot-motion.mjs", "application/javascript; charset=utf-8"),
                         "/robot-motion-clock.mjs": ("robot-motion-clock.mjs", "application/javascript; charset=utf-8"),
                         "/robot-replica.js": ("robot-replica.js", "application/javascript; charset=utf-8"),
                         "/robot-warm-desktop.js": ("robot-warm-desktop.js", "application/javascript; charset=utf-8"),
                         "/robot-scene-config.mjs": ("robot-scene-config.mjs", "application/javascript; charset=utf-8"),
                         "/robot-desktop.js": ("robot-desktop.js", "application/javascript; charset=utf-8"),
                         "/robot-eyes.js": ("robot-eyes.js", "application/javascript; charset=utf-8"),
                         "/vendor/three/RoomEnvironment.js": ("vendor/three/RoomEnvironment.js", "application/javascript; charset=utf-8"),
                         "/model-loader.mjs": ("model-loader.mjs", "application/javascript; charset=utf-8"),
                         "/models/robot-screen.json": ("models/robot-screen.json", "application/json; charset=utf-8"),
                         "/models/robot-screen.bin": ("models/robot-screen.bin", "application/octet-stream"),
                         "/robot-viewer.css": ("robot-viewer.css", "text/css; charset=utf-8"),
                         "/vendor/three/three.module.min.js": ("vendor/three/three.module.min.js", "application/javascript; charset=utf-8"),
                         "/vendor/three/three.core.min.js": ("vendor/three/three.core.min.js", "application/javascript; charset=utf-8"),
                         "/vendor/three/OrbitControls.js": ("vendor/three/OrbitControls.js", "application/javascript; charset=utf-8"),
                         "/models/robot.json": ("models/robot.json", "application/json; charset=utf-8"),
                         "/models/robot.bin": ("models/robot.bin", "application/octet-stream")}
                if path not in files:
                    self.respond(404, {"error": "Not found"})
                    return
                name, mime = files[path]
                data = (STATIC / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed_origins = {f"http://127.0.0.1:{self.server.server_port}",
                               f"http://localhost:{self.server.server_port}"}
            if origin and origin not in allowed_origins:
                self.close_connection = True
                self.respond(403, {"error": "只接受本地页面操作。"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.close_connection = True
                self.respond(415, {"error": "Expected JSON"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("Invalid body length")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected object")
                if self.path == "/api/connect":
                    device = data.get("port")
                    if not isinstance(device, str):
                        raise ValueError("请选择串口。")
                    reader.connect(device)
                elif self.path == "/api/disconnect":
                    reader.disconnect()
                elif self.path == "/api/target":
                    reader.send_target(data.get("angle_deg"))
                elif self.path == "/api/enable":
                    reader.send_enable(data.get("enabled"))
                elif self.path == "/api/motor":
                    reader.send_motor(data.get("action"))
                elif self.path == "/api/foc":
                    reader.send_foc(data)
                elif self.path == "/api/foc/2":
                    reader.send_foc(data, motor_id=2)
                elif self.path == "/api/foc/2/heartbeat":
                    self.respond(200, reader.send_foc_heartbeat(data, motor_id=2))
                    return
                elif self.path == "/api/foc/heartbeat":
                    self.respond(200, reader.send_foc_heartbeat(data))
                    return
                else:
                    self.respond(404, {"error": "Not found"})
                    return
                self.respond(200, store.snapshot())
            except CommandError as error:
                self.respond(409, {"error": str(error)})
            except (ValueError, UnicodeDecodeError) as error:
                self.respond(400, {"error": str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-port", type=int, default=8840)
    parser.add_argument("--serial-port", help="Automatically connect this serial device")
    args = parser.parse_args()
    store = TelemetryStore()
    reader = SerialReader(store)
    server = make_server(reader, store, args.http_port)
    if args.serial_port:
        try:
            reader.connect(args.serial_port)
        except ValueError as error:
            print(error, flush=True)
    print(f"AS5600 dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        reader.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
