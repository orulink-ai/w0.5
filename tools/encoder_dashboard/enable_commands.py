"""Explicit, acknowledged PB5 control; the MCU owns the five-second timeout."""
from threading import Condition
import secrets
import time

from commands import CommandError, _uint


def validate_enabled(value):
    if type(value) is not bool:
        raise ValueError("enabled 必须是 true 或 false。")
    return value


class EnableChannel:
    max_on_ms = 5000

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._condition = Condition()
        self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
        self._connected = False
        self._seen_at = self._output_at = None
        self._state = self._enabled = self._last_id = None
        self._pending = None
        self._command = self._idle()

    @staticmethod
    def _idle():
        return {"status": "idle", "id": None, "enabled": None, "error": ""}

    def reset(self, connected):
        with self._condition:
            self._connected = connected
            self._seen_at = self._output_at = None
            self._state = self._enabled = self._last_id = None
            if self._pending is not None:
                self._finish("error", "串口连接已中断，使能状态未知。")
            elif connected:
                self._command = self._idle()
            self._condition.notify_all()

    def consume(self, line):
        """Return True only for a well-formed enable status announcement."""
        fields = line.split(",")
        try:
            if (len(fields) == 5 and fields[:2] == ["#ENABLE_STATUS", "1"] and
                    fields[2] in ("READY", "FAULT") and fields[3] in ("0", "1")):
                request_id = _uint(fields[4])
                with self._condition:
                    # A zero sentinel queued before the first command is not
                    # evidence of a reset. A previous nonzero ID is required.
                    if request_id == 0 and self._last_id:
                        if self._pending is not None:
                            self._finish("error", "芯片已复位，旧使能请求已失效。")
                        else:
                            self._command = self._idle()
                    self._seen_at = self._output_at = self._clock()
                    self._state, self._enabled = fields[2], fields[3] == "1"
                    self._last_id = request_id
                return True
            if len(fields) != 3 or fields[0] not in ("#ENABLE_ACK", "#ENABLE_NACK"):
                return False
            request_id = _uint(fields[1])
            with self._condition:
                if self._pending != request_id:
                    return False
                if fields[0] == "#ENABLE_ACK" and fields[2] in ("0", "1"):
                    enabled = fields[2] == "1"
                    if enabled == self._command["enabled"]:
                        self._enabled = enabled
                        self._output_at = self._clock()
                        self._last_id = request_id
                        self._finish("accepted")
                elif fields[0] == "#ENABLE_NACK":
                    self._finish("error", f"芯片拒绝使能请求：{fields[2][:48]}")
        except (ValueError, OverflowError):
            return False
        return False

    def snapshot(self):
        with self._condition:
            age = None if self._seen_at is None else max(0, self._clock() - self._seen_at)
            output_age = None if self._output_at is None else max(0, self._clock() - self._output_at)
            available = self._connected and age is not None and age < 2.5
            output_fresh = self._connected and output_age is not None and output_age < 2.5
            return {"available": available, "ready": available and self._state == "READY",
                    "off_available": self._connected and self._seen_at is not None,
                    "state": self._state if available else None,
                    "enabled": self._enabled if output_fresh else None,
                    "max_on_ms": self.max_on_ms,
                    "age_ms": None if age is None else round(age * 1000),
                    "last_id": self._last_id if available else None,
                    "command": dict(self._command)}

    def begin(self, enabled, sensor_valid):
        enabled = validate_enabled(enabled)
        with self._condition:
            status = self.snapshot()
            if not status["off_available"]:
                raise CommandError("未收到 PB5 使能固件状态，请检查固件和串口连接。")
            if enabled and not status["ready"]:
                raise CommandError("使能固件状态过期或存在故障，暂不能拉高 PB5。")
            if enabled and not sensor_valid:
                raise CommandError("编码器数据无效或已超时，暂不能拉高 PB5。")
            if self._pending is not None:
                raise CommandError("上一条使能请求正在等待芯片确认。")
            request_id = self._next_id
            self._next_id = request_id % 0x7FFFFFFF + 1
            self._pending = request_id
            self._command = {"status": "pending", "id": request_id,
                             "enabled": enabled, "error": ""}
            return request_id, f"ENABLE,{request_id},{int(enabled)}\n".encode("ascii")

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
                self._finish("timeout", "未收到芯片引脚读回确认；未自动重发，输出以实时状态为准。")
            if self._command["id"] != request_id or self._command["status"] != "accepted":
                raise CommandError(self._command["error"] or "使能请求未确认。")
            return self.snapshot()
