"""Bounded face-ROI optical focus sweep; stop GUI before opening the port."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from face_engine import MODEL
from serial_video import UsbCapture


def run(port):
    cap = UsbCapture(port, threading.Event())
    folder = ROOT / 'runtime'
    folder.mkdir(exist_ok=True)
    report = {'points': [], 'method': 'fixed face ROI, Gaussian/Laplacian contrast; local diagnostic'}
    accepted = False
    try:
        begin = time.monotonic()
        while time.monotonic() - begin < 3:
            ok, initial = cap.read()
            if not ok:
                raise RuntimeError('No camera frames')
        scale = 640 / initial.shape[1]
        small = cv2.resize(initial, (640, round(initial.shape[0] * scale)))
        detector = cv2.FaceDetectorYN.create(str(MODEL), '', (small.shape[1], small.shape[0]), .65, .3, 5000)
        _, faces = detector.detect(small)
        # Startup autofocus may briefly park at an extreme position. Wait for
        # a detectable face instead of measuring a blurred background crop.
        while faces is None and time.monotonic() - begin < 12:
            ok, initial = cap.read()
            if not ok:
                break
            small = cv2.resize(initial, (640, round(initial.shape[0] * scale)))
            _, faces = detector.detect(small)
        cv2.imwrite(str(folder / 'focus-scene.png'), initial)
        if faces is None:
            raise RuntimeError('No face found; refusing to focus on background')
        face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = face[:4] / scale
        x1, y1 = int(x + .15*w), int(y + .15*h)
        x2, y2 = int(x + .85*w), int(y + .7*h)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(initial.shape[1], x2), min(initial.shape[0], y2)
        if x2-x1 < 30 or y2-y1 < 30:
            raise RuntimeError('Face ROI too small')
        report['roi'] = [x1, y1, x2, y2]

        def score(frame):
            gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), .7)
            return float(cv2.Laplacian(gray, cv2.CV_32F).var())

        report['before_score'] = score(initial)
        cv2.imwrite(str(folder / 'focus-before.png'), initial)
        best_score, best_position, best_frame = -1, None, None

        def sample(position):
            nonlocal best_score, best_position, best_frame
            cap.source.connection.write(f'\nIMAGE FOCUS {position}\n'.encode())
            start = time.monotonic()
            scores, frames = [], []
            while time.monotonic() - start < .7:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Video interrupted during focus sweep')
                if time.monotonic() - start > .45:
                    scores.append(score(frame))
                    frames.append(frame)
            value = float(np.median(scores)) if scores else -1
            report['points'].append({'position': position, 'score': round(value, 3)})
            print(position, round(value, 3), flush=True)
            if value > best_score:
                best_score, best_position = value, position
                best_frame = frames[len(frames)//2]

        for position in (400, 420, 440, 460, 480, 500, 520, 560, 600, 640, 680, 720):
            sample(position)
        centre = best_position
        for position in range(max(400, centre-16), min(720, centre+16)+1, 4):
            sample(position)
        cap.source.connection.write(f'\nIMAGE FOCUS {best_position}\n'.encode())
        cv2.imwrite(str(folder / 'focus-best.png'), best_frame)
        report.update(best_position=best_position, best_score=best_score, transport=cap.diagnostics())
        accepted = True
        return report
    finally:
        if not accepted:
            cap.source.connection.write(b'\nIMAGE FOCUS AUTO\n')
        cap.release()
        (folder / 'focus-calibration.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM15')
    args = parser.parse_args()
    print(json.dumps(run(args.port), indent=2))
