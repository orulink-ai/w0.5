# IMX708 camera technical notes

[中文](camera-imx708.md) · [Firmware](../firmware/esp32/examples/imx708_usb/README.en.md) · [Desktop](../tools/camera_facetrack/README.en.md)

## Integration boundary

The camera module combines ESP32-P4, IMX708 and DW9807. It sends H.264 through the CH343 UART bridge to a PC running YuNet and ByteTrack. It is independent of the existing ESP32-C6 Mini / STM32 motion system. No motor command integration or physical pan/tilt following is implemented. Track IDs associate targets within the current video session only.

```text
IMX708 RAW10 → P4 CSI / ISP → YUV420 → hardware H.264
  → UART0 / CH343 / USB → CRC validation / PyAV → YuNet / ByteTrack → Tk GUI
```

Firmware uses a pinned upstream checkout plus readable source overlays, excluding SDK caches and machine-specific paths. The hardware example builds separately; production control firmware does not depend on desktop code.

## USB frame protocol v1

UART is 4,000,000 baud, 8N1. Each packet has a 28-byte header followed by an H.264 payload. Integers are little-endian unsigned 32-bit values; do not rely on native structure layout.

| Offset / bytes | Field | Meaning |
| --- | --- | --- |
| 0 / 8 | magic | ASCII `WTCCUV1` followed by `00` |
| 8 / 4 | length | Payload bytes, receiver limit 512 KiB |
| 12 / 4 | sequence | Frame sequence for gap detection |
| 16 / 4 | pts_ms | Device timestamp, 32-bit milliseconds |
| 20 / 4 | flags | IDR flag; currently 1 indicates IDR |
| 24 / 4 | crc32 | CRC32 of the 16 metadata bytes (length through flags), then payload; initial value 0 |
| 28 / length | payload | H.264 data |

The firmware holds one output lock for an entire packet; logs may appear between packets. The receiver resynchronizes on magic, validates size and CRC, and waits for IDR after loss or corruption. Arbitrarily dropping H.264 reference frames breaks decoding. The GUI uses a one-frame latest-image queue and can replace old display frames when processing falls behind; every frame is not guaranteed to be displayed.

ASCII commands end with a newline: `STATUS`, `VIDEO ON` and `VIDEO OFF`. Video uses a five-second lease renewed every two seconds. ISP diagnostics include `IMAGE STATUS`, `IMAGE TARGET 32..112`, `IMAGE BLACK 0..32`, `IMAGE FOCUS 400..720` and `IMAGE FOCUS AUTO`. These runtime settings are not persisted to NVS. Focus status reports a driver-accepted position, not a measured optical distance.

## Configuration and quality

`wtcc-live-15` captures 1920×1080 RAW10, crops eight vertical lines to 1920×1072 and targets 28 FPS. H.264 uses 2.4 Mbit/s, GOP 14 and QP 20–40. The aligned encoder input is used directly without PPA scaling. A nominal 12 MP sensor does not imply a 12 MP streaming mode.

The pipeline uses BT.601 limited range to avoid full/limited-range mismatch. AE target is 100 with center weighting; gamma is 0.72 and black offset is 16. Black level has not been calibrated for this sensor unit. Autofocus is bounded to positions 400–720; manual override uses the existing motor-position interface.

The linked IPA binary does not support the previously attempted average metering mode. The current mode is `HIGHLIGHT_PRIOR` with its extra highlight weight and offset both zero. A successful parameter-setting return alone does not prove algorithm support. Focus, backlight exposure, flare and color require separate acceptance; global darkening or increasing encoded resolution cannot establish quality. Smartphone computational-photography equivalence is not claimed.

## Measurements and acceptance

These are historical observations on the development machine, not guarantees or new measurements of the migrated tree:

| Version / check | Observed result |
| --- | --- |
| v14, 25-second USB check | 645 accepted packets; 25.81 active FPS; 2.174 Mbit/s; zero CRC errors; one sequence gap; maximum arrival gap 1.984 seconds |
| v14 GUI | User screenshot around 17 displayed FPS; blur remained. Processing FPS differs from display FPS |
| v15 original project | Build, application flash verification and serial version query succeeded; image-quality acceptance was not completed |
| v15 focus sweep | No face detected; background calibration refused; no accepted focus result |

Migration validation (2026-10-24): installation and model setup in the new directory succeeded; all 18 Python tests, Tk GUI initialization and host C transport tests passed. After shortening the Windows build path, the full ESP-IDF v6.0.2 build passed with a 941,616-byte application. No new flash operation or image-quality acceptance was performed during migration. Credential-scan heuristic matches were reviewed as Tk input widgets and variable assignments, containing no actual passwords. Scene credentials, logs, images and backups are excluded.

Hardware acceptance should use fixed lighting, distance and stationary text / face targets. Compare local original decoded frames for focus and highlight detail. Then measure at least 60 seconds of accepted FPS, CRC failures, sequence gaps and maximum stalls. Measure end-to-end delay using a visible timer or controlled optical signal. Diagnostic images and logs stay in ignored local runtime directories; scene photos are not uploaded.

## Sources and future robot integration

The current choice is YuNet plus ByteTrack: CPU face detection followed by box, confidence and motion association for temporary IDs. YuNet supplies the neural-network detector entry rather than a basic Haar detector; ByteTrack supports multiple targets and short detection gaps rather than independent per-face template or optical-flow tracking. No identity embedding database is used. A detector replacement should preserve box coordinates, confidence and the tracking interface, then revalidate occlusion, fast motion and false positives. Track IDs have no identity meaning across sessions.

- [Upstream IMX708 driver and example](https://github.com/mushBrainDave/esp32-p4-imx-camera), pinned as documented in the firmware README.
- [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) and [camera software documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html) for sensor modes and processing background.
- [ESP32-P4 ISP API](https://docs.espressif.com/projects/esp-idf/en/latest/esp32p4/api-reference/peripherals/isp.html) for ISP interfaces.
- [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) and [ByteTrack](https://github.com/FoundationVision/ByteTrack) for the implemented detection and association algorithms.

Future robot integration should publish face-center error as an observation with explicit timestamps, coordinate conventions, validity and loss behavior in the shared protocol. Motion must remain gated by STM32 local protection. This control path does not exist yet; image rotation is not pan/tilt control.
