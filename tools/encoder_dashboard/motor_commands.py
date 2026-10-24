"""Explicit one-shot motor jog requests; execution and timing remain on MCU."""
from threading import Condition
import secrets
import time

from commands import CommandError, _uint


def validate_action(value):
    if type(value) is not str or value not in ("jog", "stop"):
        raise ValueError("action 必须是 jog 或 stop。")
    return value


class MotorChannel:
    max_run_ms = 3000

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._condition = Condition()
        self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
        self._connected = False
        self._seen_at = self._state = self._last_id = None
        self._pending = None
        self._command = self._idle()

    @staticmethod
    def _idle():
        return {"status": "idle", "id": None, "action": None, "error": ""}

    def reset(self, connected):
        with self._condition:
            self._connected = connected
            self._seen_at = self._state = self._last_id = None
            if self._pending is not None:
                self._finish("error", "串口连接已中断，点动请求未确认。")
            elif connected:
                self._command = self._idle()
            self._condition.notify_all()

    def consume(self, line):
        """Return True for a valid status, independently of the enable channel."""
        fields = line.split(",")
        try:
            if (len(fields) == 4 and fields[:2] == ["#MOTOR_STATUS", "1"] and
                    fields[2] in ("READY", "RUNNING", "DONE", "FAULT")):
                request_id = _uint(fields[3])
                with self._condition:
                    # A newly connected MCU advertising a zero high-water mark
                    # has an unused namespace, including after a full-ID reboot.
                    if request_id == 0 and self._next_id > 0x7FFFFFFF:
                        self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
                    # A zero heartbeat queued before the first request is not
                    # enough to identify a reset. Never cancel that first request.
                    if request_id == 0 and self._last_id:
                        if self._pending is not None:
                            self._finish("error", "芯片已复位，旧点动请求已失效。")
                        else:
                            self._command = self._idle()
                    self._seen_at = self._clock()
                    self._state, self._last_id = fields[2], request_id
                    self._next_id = max(self._next_id, request_id + 1)
                return True
            if len(fields) != 3 or fields[0] not in ("#MOTOR_ACK", "#MOTOR_NACK"):
                return False
            request_id = _uint(fields[1])
            with self._condition:
                if self._pending != request_id:
                    return False
                if fields[0] == "#MOTOR_ACK":
                    expected = "STARTED" if self._command["action"] == "jog" else "STOPPED"
                    if fields[2] == expected:
                        self._last_id = max(self._last_id or 0, request_id)
                        self._next_id = max(self._next_id, request_id + 1)
                        if self._command["action"] == "jog":
                            self._state = "RUNNING"
                        # ACK acknowledges the request, not completion. Only a
                        # subsequent DONE announcement proves the run finished.
                        self._finish("accepted")
                else:
                    self._finish("error", f"芯片拒绝电机请求：{fields[2][:48]}")
        except (ValueError, OverflowError):
            return False
        return False

    def snapshot(self):
        with self._condition:
            age = None if self._seen_at is None else max(0, self._clock() - self._seen_at)
            available = self._connected and age is not None and age < 2.5
            return {"available": available,
                    "ready": available and self._state in ("READY", "DONE"),
                    "stop_available": self._connected and self._seen_at is not None,
                    "state": self._state if available else None,
                    "last_id": self._last_id if available else None,
                    "age_ms": None if age is None else round(age * 1000),
                    "max_run_ms": self.max_run_ms, "command": dict(self._command)}

    def begin(self, action, sensor_valid, enable_status):
        action = validate_action(action)
        with self._condition:
            status = self.snapshot()
            if not status["stop_available"]:
                raise CommandError("未收到电机点动固件状态，请检查固件和串口连接。")
            if action == "jog":
                if not status["ready"]:
                    raise CommandError("电机未就绪、正在运行或状态过期，暂不能启动。")
                if not sensor_valid:
                    raise CommandError("编码器数据无效或已超时，暂不能启动电机。")
                if not enable_status.get("ready") or enable_status.get("enabled") is not False:
                    raise CommandError("请先关闭 EN，并等待使能状态确认后再点动。")
            if self._pending is not None:
                raise CommandError("上一条电机请求正在等待芯片确认。")
            if action == "jog" and self._next_id > 0x7FFFFFFF:
                raise CommandError("电机命令编号已耗尽，请重新启动 MCU 并重新连接串口。")
            # STOP is safe to repeat even when the monotonic ID space is full;
            # firmware always executes it, while JOG never wraps to an old ID.
            request_id = min(self._next_id, 0x7FFFFFFF)
            self._next_id = request_id + 1
            self._pending = request_id
            self._command = {"status": "pending", "id": request_id,
                             "action": action, "error": ""}
            return request_id, f"MOTOR,{request_id},{action.upper()}\n".encode("ascii")

    def _finish(self, status, error=""):
        self._command.update(status=status, error=error)
        self._pending = None
        self._condition.notify_all()

    def fail(self, request_id, error):
        with self._condition:
            if self._pending == request_id:
                self._finish("error", error)

    def wait(self, request_id, timeout=1.2):
        with self._condition:
            if not self._condition.wait_for(lambda: self._pending != request_id, timeout):
                self._finish("timeout", "未收到芯片电机请求确认；未自动重发，请查看实时状态。")
            if self._command["id"] != request_id or self._command["status"] != "accepted":
                raise CommandError(self._command["error"] or "电机请求未确认。")
            return self.snapshot()
