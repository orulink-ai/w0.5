"""Presentation must never mutate camera/model input or draw stale face evidence."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app import rotate_frame
from mouth_tracking import MouthTracker


class MouthOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tracker = MouthTracker()
        self.addCleanup(self.tracker.close)
        self.tracker.configure(True)
        self.frame = np.zeros((200, 320, 3), dtype=np.uint8)
        self.tracked = SimpleNamespace(tracker_id=np.array([7]))
        self.tracker.state = dict(self.tracker._empty(True), available=True,
                                  targetId=7, moving=True, observedAt=1000)
        self.tracker.overlay = ((200, 320), ((140, 130), (160, 120), (180, 130), (160, 140)))

    def test_fresh_lip_outline_is_drawn_on_a_copy_and_tracks_preview_transforms(self):
        with patch('mouth_tracking.time.time', return_value=1.1):
            image = self.tracker.annotate(self.frame, self.tracked)
        self.assertTrue(image[115:145, 135:185].any())
        self.assertFalse(self.frame.any(), 'Do not draw into the array used by the model worker')
        mirrored = image[:, ::-1]
        self.assertTrue(mirrored[115:145, 130:180].any())
        rotated = rotate_frame(image, 1)
        self.assertEqual(rotated.shape, (320, 200, 3))
        self.assertTrue(rotated[135:185, 55:85].any())

    def test_active_and_stationary_render_different_colors_without_changing_detection(self):
        with patch('mouth_tracking.time.time', return_value=1.1):
            active = self.tracker.annotate(self.frame, self.tracked)
            self.tracker.state['moving'] = False
            stationary = self.tracker.annotate(self.frame, self.tracked)
        self.assertFalse(np.array_equal(active, stationary))
        self.assertFalse(self.tracker.state['moving'])

    def test_disabled_stale_missing_target_or_wrong_frame_cannot_draw_old_lips(self):
        for failure in ('disabled', 'stale', 'unavailable', 'target-lost', 'wrong-size'):
            with self.subTest(failure=failure):
                self.tracker.state.update(enabled=True, available=True, observedAt=1000)
                tracked = self.tracked
                frame = self.frame
                if failure == 'disabled': self.tracker.state['enabled'] = False
                if failure == 'stale': self.tracker.state['observedAt'] = 100
                if failure == 'unavailable': self.tracker.state['available'] = False
                if failure == 'target-lost': tracked = SimpleNamespace(tracker_id=np.array([8]))
                if failure == 'wrong-size': frame = np.zeros((300, 320, 3), dtype=np.uint8)
                with patch('mouth_tracking.time.time', return_value=1.1):
                    image = self.tracker.annotate(frame, tracked)
                self.assertFalse(image.any())

    def test_reset_and_disable_clear_transient_geometry_and_never_publish_landmarks(self):
        self.assertNotIn('overlay', self.tracker.snapshot())
        self.tracker.reset()
        self.assertIsNone(self.tracker.overlay)
        self.tracker.overlay = ((200, 320), ((10, 10),))
        self.tracker.configure(False)
        self.assertIsNone(self.tracker.overlay)


if __name__ == '__main__':
    unittest.main()
