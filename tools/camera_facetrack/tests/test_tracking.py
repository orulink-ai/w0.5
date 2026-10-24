import unittest
import cv2
import numpy as np
import supervision as sv
from face_engine import FaceEngine, faces_to_detections, annotate


def detection(boxes, scores=None):
    return sv.Detections(xyxy=np.array(boxes, dtype=np.float32).reshape(-1, 4),
                         confidence=np.array(scores if scores is not None else [0.95] * len(boxes), dtype=np.float32),
                         class_id=np.zeros(len(boxes), dtype=int))


class TrackingTests(unittest.TestCase):
    def test_box_conversion_and_scale(self):
        faces = np.zeros((1, 15), dtype=np.float32)
        faces[0, :4] = [10, 20, 30, 40]
        faces[0, 14] = 0.85
        result = faces_to_detections(faces, 2, 3)
        np.testing.assert_allclose(result.xyxy, [[20, 60, 80, 180]])
        self.assertAlmostEqual(float(result.confidence[0]), 0.85, places=5)

    def test_two_faces_motion_and_short_gap(self):
        tracker = sv.ByteTrack(track_activation_threshold=0.6, minimum_consecutive_frames=2)
        for offset in range(4):
            current = tracker.update_with_detections(detection([[10+offset, 10, 70+offset, 80], [200+offset, 10, 260+offset, 80]]))
        identities = current.tracker_id.tolist()
        self.assertEqual(len(set(identities)), 2)
        for _ in range(3):
            self.assertEqual(len(tracker.update_with_detections(faces_to_detections(None))), 0)
        resumed = tracker.update_with_detections(detection([[17, 10, 77, 80], [207, 10, 267, 80]]))
        self.assertEqual(resumed.tracker_id.tolist(), identities)

    def test_low_score_maintains_existing_track(self):
        tracker = sv.ByteTrack(track_activation_threshold=0.6)
        first = tracker.update_with_detections(detection([[10, 10, 70, 80]]))
        weak = tracker.update_with_detections(detection([[11, 10, 71, 80]], [0.35]))
        self.assertEqual(first.tracker_id.tolist(), weak.tracker_id.tolist())
        self.assertEqual(len(weak), 1)

    def test_blank_model_inference(self):
        engine = FaceEngine()
        _, result = engine.process(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(len(result), 0)

    def test_mirror_does_not_change_tracking_data(self):
        tracked = detection([[10, 30, 70, 80]])
        tracked.tracker_id = np.array([1])
        original = tracked.xyxy.copy()
        output = annotate(np.zeros((100, 200, 3), dtype=np.uint8), tracked, True)
        np.testing.assert_array_equal(tracked.xyxy, original)
        self.assertTrue(output[80, 130].any())


if __name__ == '__main__':
    unittest.main()
