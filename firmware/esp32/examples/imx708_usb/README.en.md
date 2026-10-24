# ESP32-P4 / IMX708 USB video example

[中文](README.md) · [Desktop app](../../../../tools/camera_facetrack/README.en.md) · [Protocol and validation](../../../../docs/camera-imx708.en.md)

Status: the current source is `wtcc-live-18`, adding bandwidth headroom for continuous video alongside onboard microphone capture and SPK playback at volume **80**. The previous migrated `wtcc-live-15` video entry passed an ESP-IDF v6.0.2 build on 2026-10-24 (941,616 bytes); that older build does not validate concurrent audio. The user confirmed hearing three test tones at volume 80. LLaMA-Omni2 Chinese conversation and audio integrity during continuous preview still require hardware testing. Image quality and autofocus also require acceptance. This example builds independently of the ESP32-C6 Mini controller and STM32 motor firmware.

v18 build validation (2026-10-24): ESP-IDF v6.0.2 incremental compilation and partition-size checks passed with a 1,031,360-byte application. Offline C transport tests passed. These checks do not validate concurrent 4 Mbaud audio/video or Chinese conversation on hardware.

## Source layout

`overlay/` contains complete modified source files: the application, serial commands, USB H.264 framing, IMX708 ISP tuning and DW9807 focus driver. Unmodified drivers and example scaffolding come from [upstream](https://github.com/mushBrainDave/esp32-p4-imx-camera), pinned to commit `9a3f8ca28e93526e0854ba45ad3b461b33ef2dac`. Its Apache-2.0 license is retained in `UPSTREAM-LICENSE`.

`prepare.py` creates a separate checkout and overlays these sources. It never builds, flashes or changes an existing directory, and rejects an existing destination. A sibling `imx708-project/` build project avoids excessive nested dependency paths on Windows; custom destinations use `<destination-name>-project`. `dependencies.lock` comes from the successful development build with its local component path made relative. `board.defaults` holds the tested board configuration overlay.

## Hardware

- ESP32-P4 v3.2, 32 MB Flash and 32 MB PSRAM; DIO / 80 MHz Flash, 200 MHz PSRAM.
- IMX708 Wide NoIR on CSI, with a DW9807 focus motor. SCCB SCL GPIO8, SDA GPIO7; motor address `0x0c`.
- Type-C through CH343 USB-UART: UART0 TX GPIO37 / RX GPIO38, 4 Mbaud, 8N1. COM15 is an example development port.
- The board has a C6 wireless companion, but this version starts no Wi-Fi and requires no provisioning or native high-speed USB adapter.

Check pins for other P4 boards. Disconnect power before changing CSI or supply wiring. This example produces video and audio and never commands robot or pan/tilt motors.

## Microphone and speaker

The ESP32-P4-WIFI6 ES8311 codec (`0x18`) shares the initialized camera I2C0 bus. NS4150B amplifier enable is GPIO53. I2S0 MCLK/BCLK/WS/DOUT/DIN use GPIO13/12/10/9/11 respectively. Connect the speaker to the board's two-pin **SPK** connector; capture uses the onboard microphone. The codec dependency is pinned to `espressif/esp_codec_dev 1.6.2`.

`AUDIO START` initializes audio on demand, with volume 80 and microphone gain 30 dB. UART audio is **24 kHz mono PCM16LE**, up to 480 samples (20 ms) per packet. Internally I2S uses stereo: playback duplicates channels and recording selects the left channel. One host serial owner demultiplexes video, microphone data and acknowledgements; face detection and voice interaction do not stop preview. Only microphone capture pauses during AI playback to avoid recording the reply as a new utterance.

During capture or playback, v18 changes the video target from 2.4 Mbit/s at 28 FPS to 1 Mbit/s at 14 FPS, restoring it afterwards. Image dimensions, pins and volume are unchanged. I2S DMA capacity increases from 40 to 200 ms, with matching silence and drain timing for `AUDIO END`. UART RX interrupts trigger at 32 bytes with a two-symbol tail timeout for additional 4 Mbaud receive headroom. The host must wait for `AUDIO_RX` before sending raw PCM. Hardware acceptance must still measure CRC errors, microphone sequence gaps, ACK latency and audible quality; bitrate control is not a strict maximum IDR size.

| Command | Reply and behavior |
| --- | --- |
| `AUDIO START` | `AUDIO_READY rate=24000 volume=80`, or `AUDIO_ERROR ...` |
| `MIC START` / `MIC STOP` | `MIC_READY ...` / `MIC_STOPPED`; recording emits `MIC_DATA <sequence> <base64 PCM>` |
| `AUDIO DATA <sequence> <hex CRC32> <base64>` | Validates and writes PCM, replying `AUDIO_ACK <sequence>` |
| `AUDIO BIN <sequence> <byte count> <hex CRC32>` | Wait for `AUDIO_RX <sequence> <byte count>`, send raw PCM, then wait for `AUDIO_ACK <sequence>`; maximum 960 bytes |
| `AUDIO END` | Writes silence and drains DMA before `AUDIO_DONE`; a packet ACK only confirms the write |
| `AUDIO STOP` | Mutes and clears queued playback, then replies `AUDIO_STOPPED` |
| `AUDIO TONE` | Diagnostic square wave, followed by `AUDIO_TONE_DONE ...` |
| `AUDIO BAUD 1000000` / `AUDIO BAUD 4000000` | After receiving `AUDIO_BAUD ...` at the old rate, change the host UART rate too |

Text commands end in LF. CRC32 covers decoded mono PCM and matches `esp_rom_crc32_le(0, ...)` / Python `zlib.crc32`. `STATUS` includes `fw=wtcc-live-18 audio=pcm24k mic=pcm24k volume=80`. Successful writes, host tests and HTTP readiness do not establish audible playback or successful Chinese conversation.

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
