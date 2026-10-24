import unittest
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from mouth_tracking import MouthMotion, MouthTarget, MouthTracker, download_model


class MouthTrackingTests(unittest.TestCase):
    def test_corrupt_model_download_never_replaces_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'face_landmarker.task'
            path.write_bytes(b'previous-file')
            with patch('mouth_tracking.urllib.request.urlopen') as request:
                request.return_value.__enter__.return_value.read.return_value = b'corrupt'
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    download_model(path)
            self.assertEqual(path.read_bytes(), b'previous-file')

    def test_motion_measures_changes_not_a_permanently_open_mouth(self):
        motion = MouthMotion()
        self.assertFalse(motion.update(.3, 1000))
        self.assertTrue(motion.update(.4, 1100))
        self.assertFalse(motion.update(.4, 1500))

    def test_invalid_or_missing_geometry_resets_motion_baseline(self):
        motion = MouthMotion()
        motion.update(.1, 1000)
        motion.update(float('nan'), 1100)
        self.assertFalse(motion.update(.4, 1200))
        self.assertFalse(motion.update(.4, 2000))

    def test_target_does_not_switch_to_a_bystander_when_locked_face_is_lost(self):
        target = MouthTarget()
        self.assertEqual(target.select([(1, 100), (2, 80)], 0), 1)
        self.assertEqual(target.select([(2, 200)], .2), None)
        self.assertEqual(target.select([(2, 200)], 10), None)
        target.select([], 11)
        target.select([], 13.1)
        self.assertEqual(target.select([(2, 200)], 14), 2)

    def test_disabled_tracker_does_not_load_a_model_and_toggle_clears_old_evidence(self):
        tracker = MouthTracker()
        self.addCleanup(tracker.close)
        self.assertFalse(tracker.snapshot()['enabled'])
        self.assertFalse(tracker.snapshot()['available'])
        tracker.configure(True)
        tracker.configure(False)
        self.assertFalse(tracker.snapshot()['available'])
        self.assertIsNone(tracker.snapshot()['lastMotionAt'])

    def test_unavailable_optional_dependency_reports_audio_fallback_without_crashing(self):
        tracker = MouthTracker()
        self.addCleanup(tracker.close)
        tracker.configure(True)
        with patch('mouth_tracking.importlib.import_module', side_effect=ImportError('optional')) as load:
            tracker.submit(None, None, time.perf_counter())
            deadline = time.monotonic() + 2
            while '不可用' not in tracker.snapshot()['reason'] and time.monotonic() < deadline:
                time.sleep(.01)
            value = tracker.snapshot()
            load.assert_called_once_with('mediapipe')
        self.assertTrue(value['enabled'])
        self.assertFalse(value['available'])
        self.assertIn('使用音频判停', value['reason'])
        self.assertTrue(tracker.thread.is_alive())

    def test_stale_snapshot_becomes_unavailable_without_refreshing_timestamp(self):
        tracker = MouthTracker()
        self.addCleanup(tracker.close)
        tracker.state = dict(tracker._empty(True), available=True, observedAt=1000, moving=True)
        with patch('mouth_tracking.time.time', return_value=2):
            value = tracker.snapshot()
        self.assertFalse(value['available'])
        self.assertFalse(value['moving'])
        self.assertEqual(value['observedAt'], 1000)

    def test_camera_reset_invalidates_target_and_queued_evidence_without_disabling(self):
        tracker = MouthTracker()
        self.addCleanup(tracker.close)
        tracker.configure(True)
        generation = tracker.generation
        tracker.state = dict(tracker._empty(True), available=True, targetId=7)
        tracker.reset()
        self.assertGreater(tracker.generation, generation)
        self.assertTrue(tracker.snapshot()['enabled'])
        self.assertFalse(tracker.snapshot()['available'])
        self.assertIsNone(tracker.snapshot()['targetId'])


if __name__ == '__main__':
    unittest.main()
