"""Confirmed target selection protocol. Version 1 never enables a motor."""
from threading import Condition
import secrets
import time

PRESETS = (0, 90, 180, 270)


class CommandError(ValueError):
    """A command cannot be confirmed in the current device/session state."""


def validate_target(value):
    if type(value) is not int or value not in PRESETS:
        raise ValueError("请选择 0°、90°、180°或 270°。")
    return value


def _uint(text):
    if not text.isascii() or not text.isdecimal():
        raise ValueError("Invalid integer")
    result = int(text)
    if result > 0x7FFFFFFF:
        raise ValueError("Invalid request id")
    return result


class TargetChannel:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._condition = Condition()
        self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
        self._connected = False
        self._seen_at = None
        self._target = None
        self._pending = None
        self._command = {"status": "idle", "id": None, "angle_deg": None, "error": ""}

    def reset(self, connected):
        with self._condition:
            self._connected = connected
            self._seen_at = self._target = None
            if self._pending is not None:
                self._finish("error", "串口连接已中断，未收到芯片确认。")
            elif connected:
                self._command = {"status": "idle", "id": None, "angle_deg": None, "error": ""}
            self._condition.notify_all()

    def consume(self, line):
        fields = line.split(",")
        try:
            if len(fields) == 5 and fields[:3] == ["#CONTROL", "1", "DISABLED"]:
                request_id = _uint(fields[3])
                angle = -1 if fields[4] == "-1" else _uint(fields[4])
                if not ((request_id == 0 and angle == -1) or
                        (request_id > 0 and 0 <= angle < 360)):
                    return
                with self._condition:
                    # A confirmed target returning to the boot sentinel means
                    # the MCU restarted; never retain its old confirmation.
                    if request_id == 0 and self._target is not None:
                        if self._pending is not None:
                            self._finish("error", "芯片已复位，旧目标已清除，请重新选择。")
                        else:
                            self._command = {"status": "idle", "id": None,
                                             "angle_deg": None, "error": ""}
                    self._seen_at = self._clock()
                    self._target = None if angle == -1 else angle
                return
            if not fields or fields[0] not in ("#TARGET_ACK", "#TARGET_NACK"):
                return
            if len(fields) < 3:
                return
            request_id = _uint(fields[1])
            with self._condition:
                if self._pending != request_id:
                    return
                if len(fields) == 4 and fields[0] == "#TARGET_ACK" and fields[2] == "STAGED":
                    angle = _uint(fields[3])
                    if angle == self._command["angle_deg"]:
                        self._target = angle
                        self._finish("accepted")
                elif len(fields) == 3 and fields[0] == "#TARGET_NACK":
                    self._finish("error", f"芯片拒绝目标：{fields[2][:48]}")
        except (ValueError, OverflowError):
            return

    def snapshot(self):
        with self._condition:
            age = None if self._seen_at is None else max(0, self._clock() - self._seen_at)
            available = self._connected and age is not None and age < 2.5
            return {"available": available, "mode": "target_staging", "motor_enabled": False,
                    "target_deg": self._target if available else None,
                    "age_ms": None if age is None else round(age * 1000),
                    "command": dict(self._command)}

    def begin(self, angle, sensor_valid):
        angle = validate_target(angle)
        with self._condition:
            if not self.snapshot()["available"]:
                raise CommandError("未收到目标命令固件状态，请确认当前固件和串口连接。")
            if not sensor_valid:
                raise CommandError("编码器数据无效或已超时，暂不下发目标。")
            if self._pending is not None:
                raise CommandError("上一条目标正在等待芯片确认。")
            request_id = self._next_id
            self._next_id = request_id % 0x7FFFFFFF + 1
            self._pending = request_id
            self._command = {"status": "pending", "id": request_id,
                             "angle_deg": angle, "error": ""}
            return request_id, f"TARGET,{request_id},{angle}\n".encode("ascii")

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
            done = self._condition.wait_for(lambda: self._pending != request_id, timeout)
            if not done:
                self._finish("timeout", "未收到芯片确认，请检查 TTL TXD→PA3 接线；未自动重发。")
            if self._command["id"] != request_id or self._command["status"] != "accepted":
                raise CommandError(self._command["error"] or "目标未确认。")
            return self.snapshot()
