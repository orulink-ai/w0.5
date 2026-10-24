# Camera preview and face tracking

[中文](README.md) · [Firmware and wiring](../../firmware/esp32/examples/imx708_usb/README.en.md) · [Technical notes](../../docs/camera-imx708.en.md)

Status: runnable hardware debugging version. Image quality, autofocus and sustained frame rate remain unaccepted. YuNet detects faces and ByteTrack associates temporary IDs across frames. This does not recognize identities or command robot motors.

## Windows setup

Install Python 3.12 with Tk and the CH343 driver. Use a USB data cable. Find the actual port in Device Manager; COM15 is only the development default.

```powershell
cd tools/camera_facetrack
powershell -ExecutionPolicy Bypass -File setup.ps1
.venv\Scripts\python.exe app.py --watch --autostart --source serial://COM15
```

Alternatively run `start-dev.cmd` for hot reload or `start.cmd` for normal startup. Setup downloads YuNet from OpenCV Zoo into the ignored `models/` directory. No network provisioning is needed for streaming. Use `--source 0` for a PC webcam. Stop releases the camera; closing the window exits. Hot reload restarts the application and reconnects the device.

Left/right rotation, reset and mirroring affect the image only. The top counter measures displayed FPS. The footer reports native dimensions, processing FPS, inference time and time after frame reception. The latter excludes acquisition and transmission and is not an end-to-end latency measurement.

## Debugging and tests

Stop preview and close other serial monitors before opening these exclusive-port diagnostics:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tools/check_usb.py --port COM15 --seconds 25
.venv\Scripts\python.exe tools/calibrate_focus.py --port COM15
```

The USB check reports accepted frames, CRC failures, sequence gaps, data rate and maximum arrival gap; it does not assess optical quality. The experimental focus tool requires a stationary, visible face under suitable lighting. It refuses background calibration when no face is detected and restores autofocus on failure. It writes local diagnostic images and reports to `runtime/`; do not commit those files.

`runtime/`, `.venv/` and downloaded model weights are ignored. Legacy HTTP decoder tests require FFmpeg on PATH or are skipped. USB decoding uses PyAV and needs no separate FFmpeg executable. Provisioning and HTTP modules retain regression coverage, but the current GUI exposes no provisioning button and the firmware does not start Wi-Fi.

For a manual Python setup (including non-Windows environments): create a Python 3.12 virtual environment, install `requirements.txt` with pip, then run `python face_engine.py` before starting `python app.py --source 0`. Windows USB hardware is the validated target.

## Source map

| File | Responsibility |
| --- | --- |
| `app.py` | Tk UI, workers, rotation, counters, hot reload and reconnect |
| `serial_video.py` | Serial framing, CRC, IDR recovery and PyAV H.264 decoding |
| `face_engine.py` | YuNet, ByteTrack and annotations |
| `camera_setup.py` / `video_source.py` | Retained provisioning / HTTP modules, unused by the current USB path |
| `tools/` / `tests/` | Bounded diagnostics and offline regression tests |

The default is 4,000,000 baud. For older 2 Mbaud firmware set `$env:WTCC_SERIAL_BAUD='2000000'`. Both endpoints must agree. Do not open a serial monitor or flasher while preview owns the port.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Model weights, scene photos, Wi-Fi credentials, flash backups and compiled binaries are excluded from this migration.
