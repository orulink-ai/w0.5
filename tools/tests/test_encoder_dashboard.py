import json
from pathlib import Path
import sys
import unittest

MODULE_DIR = Path(__file__).resolve().parents[1] / "encoder_dashboard"
sys.path.insert(0, str(MODULE_DIR))
from telemetry import TelemetryStore, parse_line  # noqa: E402


class TelemetryTests(unittest.TestCase):
    def test_valid_angle(self):
        result = parse_line("OK,123.45,-0.125,919.1,389,1088")
        self.assertEqual(result["angle_deg"], 123.45)
        self.assertTrue(result["valid"])
        self.assertEqual(result["period_us"], 1088)

    def test_invalid_signal_never_exposes_nan_or_old_angle(self):
        result = parse_line("NO_PWM_OR_INVALID,nan,nan,nan,26,17")
        self.assertFalse(result["valid"])
        self.assertIsNone(result["angle_deg"])
        self.assertEqual(result["high_us"], 26)
        json.dumps(result, allow_nan=False)

    def test_rejects_bad_rows_and_non_finite_valid_values(self):
        for row in ["status,angle_deg,velocity_rad_s,frequency_hz,high_us,period_us",
                    "booting", "OK,1,2", "OK,nan,0,920,500,1087",
                    "OK,inf,0,920,500,1087", "OK,361,0,920,500,1087",
                    "OK,1,0,920,-1,1087", "OK,1,0,920,500,0"]:
            with self.subTest(row=row):
                self.assertIsNone(parse_line(row))

    def test_disconnect_and_silence_invalidate_previous_valid_reading(self):
        store = TelemetryStore(clock=lambda: 10.0)
        store.set_connection(True, "/dev/test")
        store.consume("OK,90,0,920,300,1087", now=10)
        self.assertEqual(store.snapshot(now=10.5)["signal"], "valid")
        stale = store.snapshot(now=12)
        self.assertEqual(stale["signal"], "stale")
        self.assertIsNone(stale["reading"]["angle_deg"])
        store.set_connection(False)
        self.assertEqual(store.snapshot(now=12)["signal"], "disconnected")

    def test_invalid_rows_and_diagnostics_are_distinct(self):
        store = TelemetryStore(clock=lambda: 1.0)
        store.set_connection(True, "/dev/test")
        store.consume("NO_PWM_OR_INVALID,nan,nan,nan,0,0")
        store.consume("AS5600 PWM / PA0 / SimpleFOC GenericSensor")
        state = store.snapshot()
        self.assertEqual(state["signal"], "invalid")
        self.assertEqual(state["samples"], 1)
        self.assertEqual(len(state["logs"]), 2)

    def test_reconnect_clears_old_session_and_log_ring_is_bounded(self):
        store = TelemetryStore(clock=lambda: 1.0, log_limit=3)
        store.set_connection(True, "/dev/test")
        for _ in range(5):
            store.consume("OK,90,0,920,300,1087")
        self.assertEqual(len(store.snapshot()["logs"]), 3)
        store.set_connection(True, "/dev/other")
        self.assertEqual(store.snapshot()["signal"], "waiting")
        self.assertEqual(store.snapshot()["samples"], 0)

    def test_manual_jog_status_is_fresh_and_not_position_control(self):
        store = TelemetryStore(clock=lambda: 10.0)
        store.set_connection(True, "/dev/test")
        store.consume("#CONTROL,1,DISABLED,12,90", now=10)
        store.consume("#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms", now=10)
        state = store.snapshot(now=10.5)
        self.assertEqual(state["jog"]["state"], "READY")
        self.assertEqual(state["jog"]["enable"], "manual")
        self.assertFalse(state["control"]["available"])
        self.assertIsNone(state["control"]["target_deg"])
        self.assertIsNone(store.snapshot(now=13)["jog"])
        store.consume("#JOG_STATUS,1,RUNNING,MANUAL_EN,1.0V,0.5rad_s,3000ms", now=13)
        self.assertEqual(store.snapshot(now=13)["jog"]["state"], "RUNNING")
        store.set_connection(False)
        self.assertIsNone(store.snapshot(now=13)["jog"])

    def test_malformed_jog_status_cannot_change_display_mode(self):
        store = TelemetryStore(clock=lambda: 10.0)
        store.set_connection(True, "/dev/test")
        for line in ("#JOG_STATUS,2,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms",
                     "#JOG_STATUS,1,UNKNOWN,MANUAL_EN,1.0V,0.5rad_s,3000ms",
                     "#JOG_STATUS,1,READY,GPIO_EN,1.0V,0.5rad_s,3000ms",
                     "#JOG_STATUS,1,READY,MANUAL_EN,12V,0.5rad_s,3000ms"):
            store.consume(line)
        self.assertIsNone(store.snapshot()["jog"])


if __name__ == "__main__":
    unittest.main()
