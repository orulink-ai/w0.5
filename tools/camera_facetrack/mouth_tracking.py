"""Optional, local-only lip geometry. Latest frame only; never records face images."""
import importlib
import hashlib
import math
from pathlib import Path
import queue
import threading
import time
import urllib.request

import cv2


MODEL = Path(__file__).parent / 'models' / 'face_landmarker.task'
MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
MODEL_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'


def download_model(path=MODEL):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        return MODEL_SHA256
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
        payload = response.read(4_000_001)
    if len(payload) != 3_758_596 or hashlib.sha256(payload).hexdigest() != MODEL_SHA256:
        raise ValueError('Face Landmarker SHA256 校验失败，原模型未修改')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.task.part')
    temporary.write_bytes(payload)
    temporary.replace(path)
    return MODEL_SHA256


class MouthMotion:
    def __init__(self):
        self.previous = None
        self.observed = None
        self.last_motion = None

    def update(self, aperture, now):
        if not math.isfinite(aperture) or not 0 <= aperture <= 2:
            self.previous = self.observed = self.last_motion = None
            return False
        if self.observed is None or now - self.observed > 500 or now <= self.observed:
            self.previous = aperture
            self.last_motion = None
        elif abs(aperture - self.previous) >= .015:
            self.last_motion = now
        self.previous = aperture
        self.observed = now
        return self.last_motion is not None and now - self.last_motion <= 200


class MouthTarget:
    def __init__(self):
        self.identity = None
        self.empty_since = None

    def select(self, candidates, now):
        if not candidates:
            if self.empty_since is None:
                self.empty_since = now
            if now - self.empty_since >= 2:
                self.identity = None
            return None
        self.empty_since = None
        if self.identity is None:
            self.identity = max(candidates, key=lambda item: item[1])[0]
        return self.identity if any(item[0] == self.identity for item in candidates) else None


class MouthTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.enabled = False
        self.generation = 0
        self.state = self._empty(False)
        self.frames = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._work, daemon=True, name='mouth-landmarks')
        self.thread.start()

    @staticmethod
    def _empty(enabled, reason='等待嘴部画面'):
        return dict(enabled=enabled, available=False, moving=False, observedAt=0,
                    lastMotionAt=None, targetId=None, inferenceMs=None, reason=reason)

    def configure(self, enabled):
        with self.lock:
            if enabled != self.enabled:
                self.enabled = enabled
                self.generation += 1
                self.state = self._empty(enabled, '等待嘴部画面' if enabled else '已关闭')

    def snapshot(self):
        with self.lock:
            value = self.state.copy()
        if value['available'] and not 0 <= time.time() * 1000 - value['observedAt'] <= 500:
            value.update(available=False, moving=False, reason='嘴部画面过期，使用音频判停')
        return value

    def reset(self):
        """Camera reconnect/rotation invalidates all old track IDs and queued frames."""
        with self.lock:
            self.generation += 1
            self.state = self._empty(self.enabled, '等待新嘴部画面' if self.enabled else '已关闭')

    def submit(self, frame, tracked, captured_at):
        with self.lock:
            if not self.enabled:
                return
            generation = self.generation
        # The worker owns this immutable reference; capture delivers a new array per frame.
        item = (frame, tracked, captured_at, generation)
        try:
            self.frames.put_nowait(item)
        except queue.Full:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frames.put_nowait(item)
            except queue.Full:
                pass

    def _work(self):
        # Optional dependency must not prevent the default camera runtime from starting.
        landmarker = None
        generation = -1
        failed = False
        target = MouthTarget()
        motion = MouthMotion()
        try:
            while not self.stop.is_set():
                try:
                    frame, tracked, captured_at, current = self.frames.get(timeout=.2)
                except queue.Empty:
                    continue
                with self.lock:
                    if current != self.generation or not self.enabled:
                        continue
                if current != generation:
                    generation, failed = current, False
                    target, motion = MouthTarget(), MouthMotion()
                if failed:
                    continue
                value = self._empty(True)
                try:
                    if landmarker is None:
                        mp = importlib.import_module('mediapipe')
                        options = mp.tasks.vision.FaceLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL)),
                            running_mode=mp.tasks.vision.RunningMode.IMAGE, num_faces=1)
                        landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
                    age = time.perf_counter() - captured_at
                    now = time.time() * 1000 - age * 1000
                    if not 0 <= age <= .5:
                        continue
                    candidates = [(int(identity), max(0, box[2]-box[0]) * max(0, box[3]-box[1]))
                                  for identity, box in zip(tracked.tracker_id, tracked.xyxy)]
                    identity = target.select(candidates, time.monotonic())
                    value.update(observedAt=now, targetId=target.identity)
                    if identity is not None:
                        box = next(box for i, box in zip(tracked.tracker_id, tracked.xyxy) if int(i) == identity)
                        x1, y1, x2, y2 = (int(v) for v in box)
                        height, width = frame.shape[:2]
                        pad = int(max(x2-x1, y2-y1) * .15)
                        crop = frame[max(0, y1-pad):min(height, y2+pad), max(0, x1-pad):min(width, x2+pad)]
                        if min(crop.shape[:2]) >= 80:
                            crop = cv2.resize(crop, (256, 256))
                            begin = time.perf_counter()
                            result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                       data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
                            value['inferenceMs'] = round((time.perf_counter()-begin)*1000, 1)
                            if result.face_landmarks:
                                points = result.face_landmarks[0]
                                a, b, left, right = (points[i] for i in (13, 14, 78, 308))
                                mouth_width = math.hypot(left.x-right.x, left.y-right.y)
                                # Require a plausible mouth and frontal-enough nose between eye corners.
                                nose, eye_l, eye_r = (points[i] for i in (1, 33, 263))
                                frontal = min(eye_l.x, eye_r.x) < nose.x < max(eye_l.x, eye_r.x)
                                if mouth_width >= .04 and frontal:
                                    aperture = math.hypot(a.x-b.x, a.y-b.y) / mouth_width
                                    moving = motion.update(aperture, now)
                                    value.update(available=True, moving=moving, lastMotionAt=motion.last_motion,
                                                 reason='嘴部活动中' if moving else '嘴部静止')
                                else:
                                    motion = MouthMotion()
                            else:
                                motion = MouthMotion()
                    else:
                        motion = MouthMotion()
                except Exception as exc:
                    failed = True
                    value = self._empty(True, f'嘴型模型不可用，使用音频判停：{type(exc).__name__}；请运行 setup-mouth.ps1')
                with self.lock:
                    if generation == self.generation and self.enabled:
                        self.state = value
                # Bound optional work to at most 10 FPS without blocking video or audio workers.
                self.stop.wait(.08)
        finally:
            if landmarker is not None:
                landmarker.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)


if __name__ == '__main__':
    print('Face Landmarker SHA256:', download_model())
