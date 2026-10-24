from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encoder_dashboard"))
from commands import CommandError, TargetChannel, validate_target


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.channel = TargetChannel(clock=lambda: self.now)
        self.channel.reset(True)

    def advertise(self):
        self.channel.consume("#CONTROL,1,DISABLED,0,-1")

    def test_preset_validation_rejects_floats_bools_and_injection(self):
        for angle in (0, 90, 180, 270):
            self.assertEqual(validate_target(angle), angle)
        for angle in (18, 360, -90, True, 90.0, "90\nARM", None):
            with self.assertRaises(ValueError): validate_target(angle)

    def test_requires_fresh_firmware_and_sensor(self):
        with self.assertRaises(CommandError): self.channel.begin(90, True)
        self.advertise()
        with self.assertRaises(CommandError): self.channel.begin(90, False)
        self.now += 3
        with self.assertRaises(CommandError): self.channel.begin(90, True)

    def test_only_matching_ack_confirms_target(self):
        self.advertise()
        request_id, packet = self.channel.begin(90, True)
        self.assertEqual(packet, f"TARGET,{request_id},90\n".encode())
        self.channel.consume(f"#TARGET_ACK,{request_id + 1},STAGED,90")
        self.channel.consume(f"#TARGET_ACK,{request_id},STAGED,180")
        self.assertIsNone(self.channel.snapshot()["target_deg"])
        self.channel.consume(f"#TARGET_ACK,{request_id},STAGED,90")
        result = self.channel.wait(request_id, timeout=0.01)
        self.assertEqual(result["command"]["status"], "accepted")
        self.assertEqual(result["target_deg"], 90)
        self.assertFalse(result["motor_enabled"])

    def test_timeout_and_disconnect_do_not_claim_execution(self):
        self.advertise()
        request_id, _ = self.channel.begin(180, True)
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=0.001)
        self.assertIsNone(self.channel.snapshot()["target_deg"])
        self.assertEqual(self.channel.snapshot()["command"]["status"], "timeout")
        request_id, _ = self.channel.begin(270, True)
        self.channel.reset(False)
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=0.001)
        self.assertFalse(self.channel.snapshot()["available"])

    def test_status_restore_and_unsupported_modes(self):
        for line in ("#CONTROL,2,DISABLED,0,-1", "#CONTROL,1,ENABLED,0,-1",
                     "#CONTROL,1,DISABLED,0,90", "#CONTROL,1,DISABLED,1,nan"):
            self.channel.consume(line)
        self.assertFalse(self.channel.snapshot()["available"])
        self.channel.consume("#CONTROL,1,DISABLED,12,270")
        self.assertTrue(self.channel.snapshot()["available"])
        self.assertEqual(self.channel.snapshot()["target_deg"], 270)

    def test_nack_and_busy_are_explicit(self):
        self.advertise()
        request_id, _ = self.channel.begin(0, True)
        with self.assertRaises(CommandError): self.channel.begin(90, True)
        self.channel.consume(f"#TARGET_NACK,{request_id},ID_CONFLICT")
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=0.01)
        self.assertIsNone(self.channel.snapshot()["target_deg"])

    def test_device_reset_clears_previous_confirmation_and_fails_pending(self):
        self.advertise()
        request_id, _ = self.channel.begin(90, True)
        self.channel.consume(f"#TARGET_ACK,{request_id},STAGED,90")
        self.channel.wait(request_id, timeout=0.01)
        request_id, _ = self.channel.begin(180, True)
        self.channel.consume("#CONTROL,1,DISABLED,0,-1")
        self.assertIsNone(self.channel.snapshot()["target_deg"])
        self.assertEqual(self.channel.snapshot()["command"]["status"], "error")
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=0.01)
        self.channel.consume(f"#TARGET_ACK,{request_id},STAGED,180")
        self.assertIsNone(self.channel.snapshot()["target_deg"])
        request_id, _ = self.channel.begin(270, True)
        self.channel.consume(f"#TARGET_ACK,{request_id},STAGED,270")
        self.channel.wait(request_id, timeout=0.01)
        self.channel.consume("#CONTROL,1,DISABLED,0,-1")
        self.assertEqual(self.channel.snapshot()["command"]["status"], "idle")
