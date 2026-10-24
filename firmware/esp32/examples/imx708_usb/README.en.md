# ESP32-P4 / IMX708 USB video example

[中文](README.md) · [Desktop app](../../../../tools/camera_facetrack/README.en.md) · [Protocol and validation](../../../../docs/camera-imx708.en.md)

Status: `wtcc-live-15` was built and flashed in the original development project, then identified over serial. The migrated entry points also passed source preparation and a full ESP-IDF v6.0.2 build on 2026-10-24 (941,616-byte application; no new flash operation). Image quality and autofocus still require hardware acceptance. This example builds independently of the ESP32-C6 Mini controller and STM32 motor firmware.

## Source layout

`overlay/` contains complete modified source files: the application, serial commands, USB H.264 framing, IMX708 ISP tuning and DW9807 focus driver. Unmodified drivers and example scaffolding come from [upstream](https://github.com/mushBrainDave/esp32-p4-imx-camera), pinned to commit `9a3f8ca28e93526e0854ba45ad3b461b33ef2dac`. Its Apache-2.0 license is retained in `UPSTREAM-LICENSE`.

`prepare.py` creates a separate checkout and overlays these sources. It never builds, flashes or changes an existing directory, and rejects an existing destination. A sibling `imx708-project/` build project avoids excessive nested dependency paths on Windows; custom destinations use `<destination-name>-project`. `dependencies.lock` comes from the successful development build with its local component path made relative. `board.defaults` holds the tested board configuration overlay.

## Hardware

- ESP32-P4 v3.2, 32 MB Flash and 32 MB PSRAM; DIO / 80 MHz Flash, 200 MHz PSRAM.
- IMX708 Wide NoIR on CSI, with a DW9807 focus motor. SCCB SCL GPIO8, SDA GPIO7; motor address `0x0c`.
- Type-C through CH343 USB-UART: UART0 TX GPIO37 / RX GPIO38, 4 Mbaud, 8N1. COM15 is an example development port.
- The board has a C6 wireless companion, but this version starts no Wi-Fi and requires no provisioning or native high-speed USB adapter.

Check pins for other P4 boards. Disconnect power before changing CSI or supply wiring. This example produces video and never commands robot or pan/tilt motors.

## Prepare and build

Install and activate the ESP32-P4 toolchain from ESP-IDF **v6.0.2**. From the repository root:

```powershell
python firmware/esp32/examples/imx708_usb/prepare.py
cd .camera-sdk/imx708-project
idf.py -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.board" build
```

Use `prepare.py --source <local-upstream-git-clone> --destination <new-directory>` to reuse local Git objects. Initial component downloads may still need internet access. The original upstream README describes Wi-Fi operation; this directory documents the current behavior. Some legacy network settings and comments remain in `sdkconfig.defaults`, although startup does not enable networking.

## Application update

Exit desktop preview first. This command is only for the tested board with an already verified compatible bootloader, 32 MB Flash and 4 MB factory application partition at `0x10000`:

```powershell
python -m esptool --chip esp32p4 --port COM15 --baud 2000000 write-flash 0x10000 build/imx708_wifi_video.bin
```

It updates the application only. For a new board, verify partition layout, revision, pins and power before defining a separate initial bootloader/partition deployment procedure. Do not use this image on ESP32-C6 Mini or STM32. Do not erase the whole chip, modify eFuses, publish NVS backups or overwrite wireless-companion firmware.

## Host tests

In the prepared example directory:

```powershell
python main/test/run_host_tests.py --clang <host-clang-path>
```

Requires a host-target Clang / LLD installation or `--zig <zig-path>`. These offline tests cover partial writes, a shared deadline, blocked peers, zero/error writes, IDR recovery and PTS wrap. They do not access hardware.

## Limitations

Capture targets 1920×1080 at 28 FPS; encoding crops the center to 1920×1072 at 2.4 Mbit/s H.264. This is not 12 MP output and does not guarantee sustained 28 FPS or zero loss. 4 Mbaud is the UART line rate; 8N1 payload capacity is lower.

Focus and strong-backlight quality remain unresolved. The latest focus sweep could not detect a face and did not complete. Higher encoded resolution does not establish better optical sharpness. See the technical notes for measurements and acceptance steps.
