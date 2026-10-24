"""AS5600 UART decoding and thread-safe live display state."""
from collections import deque
from math import isfinite
from threading import Lock
import time
from commands import TargetChannel
from enable_commands import EnableChannel
from motor_commands import MotorChannel
from closed_loop_commands import ClosedLoopChannel
from encoder_channels import EncoderChannels


def parse_line(line):
    fields = line.strip().split(",")
    if len(fields) != 6 or fields[0] not in ("OK", "NO_PWM_OR_INVALID"):
        return None
    try:
        high, period = int(fields[4]), int(fields[5])
        if not all(0 <= value <= 0xFFFFFFFF for value in (high, period)):
            return None
        valid = fields[0] == "OK"
        angle, velocity, frequency = (None, None, None)
        if valid:
            angle, velocity, frequency = map(float, fields[1:4])
            if (not all(isfinite(v) for v in (angle, velocity, frequency)) or
                    not 0 <= angle < 360 or frequency <= 0 or
                    not 0 < high < period):
                return None
        return {"valid": valid, "angle_deg": angle, "velocity_rad_s": velocity,
                "frequency_hz": frequency, "high_us": high, "period_us": period}
    except (ValueError, OverflowError):
        return None


class TelemetryStore:
    def __init__(self, clock=time.monotonic, log_limit=30):
        self._lock = Lock()
        self._clock = clock
        self._logs = deque(maxlen=log_limit)
        self._connected = False
        self._port = ""
        self._error = ""
        self._reading = None
        self._last_sample = None
        self._samples = 0
        self._valid_samples = 0
        self._jog = None
        self._jog_at = None
        self.control = TargetChannel(clock)
        self.enable = EnableChannel(clock)
        self.motor = MotorChannel(clock)
        self.closed_loop = ClosedLoopChannel(clock)
        self.closed_loop_secondary = ClosedLoopChannel(clock)
        self._enable_seen = False
        self.encoders = EncoderChannels()

    def set_connection(self, connected, port="", error=""):
        with self._lock:
            self._connected = connected
            self._error = error
            self._jog = self._jog_at = None
            self.control.reset(connected)
            self.enable.reset(connected)
            self.motor.reset(connected)
            self.closed_loop.reset(connected)
            self.closed_loop_secondary.reset(connected)
            self._enable_seen = False
            self.encoders.reset()
            if connected:
                self._port = port
                self._reading = None
                self._last_sample = None
                self._samples = self._valid_samples = 0
                self._logs.clear()

    def consume(self, line, now=None):
        now = self._clock() if now is None else now
        reading = parse_line(line)
        enable_status = self.enable.consume(line)
        motor_status = self.motor.consume(line)
        closed_loop_status = self.closed_loop.consume(line)
        secondary_status = (self.closed_loop_secondary.consume(line.replace('#FOC2_', '#FOC_', 1))
                            if line.startswith('#FOC2_') else False)
        with self._lock:
            was_diagnostic = self.encoders.diagnostic
            channel_sample = self.encoders.consume(line, parse_line, now)
            if channel_sample:
                channel_id, channel_reading, tagged = channel_sample
                if channel_id == 1:
                    reading = channel_reading
                if tagged and not was_diagnostic:
                    # Diagnostic firmware never owns or enables a motor. Do not
                    # retain old motion capability across an in-place reflash.
                    self.closed_loop.reset(self._connected)
                    self.closed_loop_secondary.reset(self._connected)
                    self.control.reset(self._connected)
                    self.enable.reset(self._connected)
                    self.motor.reset(self._connected)
                    self._enable_seen = True
                    self._jog = self._jog_at = None
            if closed_loop_status or secondary_status:
                self.encoders.diagnostic = False
            if (enable_status or motor_status or closed_loop_status) and not self._enable_seen:
                self._enable_seen = True
                self.control.reset(self._connected)
                self._jog = self._jog_at = None
            if not self._enable_seen:
                self.control.consume(line)
            fields = line.split(",")
            if (not self._enable_seen and len(fields) == 7 and fields[:2] == ["#JOG_STATUS", "1"] and
                    fields[2] in ("READY", "RUNNING", "DONE", "FAULT") and
                    fields[3:] == ["MANUAL_EN", "1.0V", "0.5rad_s", "3000ms"]):
                if self._jog is None:
                    self.control.reset(self._connected)
                self._jog = {"state": fields[2], "enable": "manual"}
                self._jog_at = now
            self._logs.append({"time_ms": round(time.time() * 1000), "text": line[:512]})
            if reading is not None:
                self._reading = reading
                self._last_sample = now
                self._samples += 1
                self._valid_samples += int(reading["valid"])

    def foc_channel(self, motor_id):
        if type(motor_id) is not int or motor_id not in (1, 2):
            raise ValueError('电机编号只能为 1 或 2。')
        return self.closed_loop if motor_id == 1 else self.closed_loop_secondary

    def snapshot(self, now=None):
        now = self._clock() if now is None else now
        with self._lock:
            age = None if self._last_sample is None else max(0, now - self._last_sample)
            if not self._connected:
                signal = "disconnected"
            elif age is None:
                signal = "waiting"
            elif age >= 1.0:
                signal = "stale"
            else:
                signal = "valid" if self._reading["valid"] else "invalid"
            reading = dict(self._reading) if self._reading else None
            jog_age = None if self._jog_at is None else max(0, now - self._jog_at)
            jog = (dict(self._jog) if self._connected and jog_age is not None and
                   jog_age < 2.5 else None)
            if reading and signal != "valid":
                reading.update(valid=False, angle_deg=None, velocity_rad_s=None, frequency_hz=None)
            encoders = self.encoders.snapshot(self._connected, now)
            controls = [self.closed_loop.snapshot(), self.closed_loop_secondary.snapshot()]
            return {"connected": self._connected, "port": self._port, "baud": 115200,
                    "signal": signal, "reading": reading, "error": self._error,
                    "age_ms": None if age is None else round(age * 1000),
                    "samples": self._samples, "valid_samples": self._valid_samples,
                    "logs": list(self._logs), "control": self.control.snapshot(), "jog": jog,
                    "enable": self.enable.snapshot(), "motor": self.motor.snapshot(),
                    "closed_loop": controls[0],
                    "motors": [dict(id=index + 1, signal=encoders[index]['signal'],
                                    reading=encoders[index]['reading'], closed_loop=control)
                               for index, control in enumerate(controls)],
                    "encoders": encoders,
                    "encoder_mode": ("dual_control" if controls[1]['supported'] else
                                     "dual_diagnostic" if self.encoders.diagnostic else
                                     "single_with_aux" if self.encoders.auxiliary else "single")}
