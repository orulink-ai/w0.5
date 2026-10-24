"""Bounded USB wire check. Stop the GUI preview before opening the same port."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serial_video import SerialVideo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM15')
    parser.add_argument('--seconds', type=int, default=30, choices=range(1, 61))
    args = parser.parse_args()
    source = SerialVideo(args.port)
    start = time.monotonic()
    arrivals, total = [], 0
    try:
        while time.monotonic() - start < args.seconds:
            for payload in source.read_frames():
                arrivals.append(time.monotonic())
                total += len(payload)
        result = dict(seconds=round(time.monotonic() - start, 2), frames=source.parser.frames,
                      crc_errors=source.parser.crc_errors, sequence_gaps=source.parser.sequence_gaps,
                      received_bytes=total)
        if len(arrivals) > 1:
            active = arrivals[-1] - arrivals[0]
            result.update(active_fps=round((len(arrivals) - 1) / active, 2),
                          max_arrival_gap_s=round(max(b-a for a, b in zip(arrivals, arrivals[1:])), 3),
                          mbps=round(total * 8 / active / 1e6, 3))
    finally:
        source.close()
    target = ROOT / 'runtime' / 'usb-health.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
