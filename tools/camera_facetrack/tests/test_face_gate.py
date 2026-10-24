import unittest

from face_gate import FaceGate


class FaceGateTests(unittest.TestCase):
    def test_manual_turn_also_waits_for_departure_before_auto_trigger(self):
        gate = FaceGate()
        gate.block_until_departure()
        self.assertFalse(gate.update(True, 0))
        self.assertFalse(gate.update(True, 1))
        gate.update(False, 2)
        gate.update(False, 5)
        self.assertFalse(gate.update(True, 6))
        self.assertTrue(gate.update(True, 7))

    def test_stable_face_triggers_once(self):
        gate = FaceGate()
        self.assertFalse(gate.update(True, 0))
        self.assertFalse(gate.update(True, .9))
        self.assertTrue(gate.update(True, 1.0))
        self.assertFalse(gate.update(True, 8))

    def test_must_leave_for_three_observed_seconds(self):
        gate = FaceGate()
        gate.update(True, 0)
        gate.update(True, 1)
        gate.update(False, 2)
        gate.update(False, 4.9)
        self.assertFalse(gate.update(True, 5))
        gate.update(False, 6)
        gate.update(False, 9)
        self.assertFalse(gate.update(True, 10))
        self.assertTrue(gate.update(True, 11))

    def test_suspended_video_never_counts_as_absence(self):
        gate = FaceGate()
        gate.update(True, 0)
        gate.update(True, 1)
        gate.update(False, 2)
        gate.suspend()
        self.assertFalse(gate.update(False, 100))
        self.assertFalse(gate.update(True, 101))
        self.assertFalse(gate.update(True, 102))

    def test_stale_frame_cannot_trigger_or_rearm(self):
        gate = FaceGate()
        gate.update(True, 0)
        self.assertFalse(gate.update(True, 2, fresh=False))
        self.assertFalse(gate.update(True, 3))
        self.assertTrue(gate.update(True, 4))
        gate.update(False, 5)
        gate.update(False, 10, fresh=False)
        self.assertFalse(gate.update(True, 11))


if __name__ == '__main__':
    unittest.main()
