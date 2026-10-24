"""YuNet detections -> Supervision ByteTrack. No face recognition or recording."""
from pathlib import Path
import hashlib
import os
import time
import urllib.request

import cv2
import numpy as np
import supervision as sv

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models' / 'face_detection_yunet_2023mar.onnx'
MODEL_URL = ('https://media.githubusercontent.com/media/opencv/opencv_zoo/'
             'main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx')


def download_model():
    """Explicit setup operation; the camera app never downloads in its UI loop."""
    MODEL.parent.mkdir(exist_ok=True)
    if MODEL.exists():
        try:
            cv2.FaceDetectorYN.create(str(MODEL), '', (320, 320))
            return hashlib.sha256(MODEL.read_bytes()).hexdigest()
        except cv2.error:
            pass
    temporary = MODEL.with_suffix('.download.onnx')
    try:
        urls = [MODEL_URL, 'https://github.com/opencv/opencv_zoo/raw/refs/heads/main/'
                'models/face_detection_yunet/face_detection_yunet_2023mar.onnx']
        for attempt in range(4):
            try:
                request = urllib.request.Request(urls[attempt % 2], headers={'User-Agent': 'FaceTrack-Setup/1.0'})
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read()
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(1)
        if len(payload) < 100_000 or payload.startswith(b'version https://git-lfs'):
            raise RuntimeError('下载的模型不完整，请重新运行 setup.ps1。')
        temporary.write_bytes(payload)
        # Parse with the actual runtime before accepting a downloaded model.
        cv2.FaceDetectorYN.create(str(temporary), '', (320, 320))
        temporary.replace(MODEL)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(MODEL.read_bytes()).hexdigest()


def faces_to_detections(faces, scale_x=1.0, scale_y=1.0):
    if faces is None or len(faces) == 0:
        return sv.Detections(xyxy=np.empty((0, 4), dtype=np.float32),
                             confidence=np.empty(0, dtype=np.float32),
                             class_id=np.empty(0, dtype=int))
    boxes = faces[:, :4].copy()
    boxes[:, 2:4] += boxes[:, :2]
    boxes *= np.array([scale_x, scale_y, scale_x, scale_y])
    return sv.Detections(xyxy=boxes, confidence=faces[:, 14].copy(),
                         class_id=np.zeros(len(faces), dtype=int))


class FaceEngine:
    def __init__(self, activation=0.6, buffer=30):
        if os.environ.get('VI_VOICE_PROVIDER') == 'local-cascade':
            # Avoid OpenCV consuming every CPU core alongside ASR and TTS.
            cv2.setNumThreads(1)
        if not MODEL.exists():
            raise FileNotFoundError('缺少 YuNet 模型，请先运行 setup.ps1。')
        # Keep weak detections for ByteTrack's second association stage.
        self.detector = cv2.FaceDetectorYN.create(str(MODEL), '', (320, 320),
                                                 0.1, 0.3, 5000)
        self.tracker = sv.ByteTrack(track_activation_threshold=activation,
                                    lost_track_buffer=buffer, frame_rate=30,
                                    minimum_consecutive_frames=2)

    def process(self, frame, inference_width=640):
        height, width = frame.shape[:2]
        factor = min(1.0, inference_width / width)
        small = cv2.resize(frame, (round(width * factor), round(height * factor)))
        sh, sw = small.shape[:2]
        self.detector.setInputSize((sw, sh))
        _, faces = self.detector.detect(small)
        detections = faces_to_detections(faces, width / sw, height / sh)
        tracked = self.tracker.update_with_detections(detections)
        return frame, tracked


def annotate(frame, tracked, mirror=False):
    if mirror:
        frame = cv2.flip(frame, 1)
    for box, confidence, identity in zip(tracked.xyxy, tracked.confidence,
                                        tracked.tracker_id):
        x1, y1, x2, y2 = box.astype(int)
        if mirror:
            x1, x2 = frame.shape[1] - x2, frame.shape[1] - x1
        color = ((int(identity) * 71) % 155 + 100, 220, 90)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f'Face {identity} | {confidence:.2f}'
        cv2.putText(frame, text, (max(0, x1), max(22, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)
    return frame


if __name__ == '__main__':
    print('Model SHA256:', download_model())
