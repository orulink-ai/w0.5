# Speaker firmware integration contract

[中文](README.md)

Status: waiting for the actual firmware. No audio driver, playback implementation or flash entry point is provided yet.

Place the future source, board configuration, dependency locks and independent build entry here. Record audio-asset provenance and licensing. Confirm the MCU, amplifier / DAC, I2S or other interface, pins, supply, sample rate and serial port before defining build or flash commands.

Keep camera sources and entry points in `../imx708_usb/` and `tools/camera.py` intact. Speaker work must use its own build directory and must not automatically reuse COM15, flash a device or play audio when preview starts. If both tasks target the same P4, explicitly choose temporary application replacement versus integrated audiovisual tasks and review I2S / CSI / UART pins, memory and scheduling. Close preview before sharing its serial port.

Hardware acceptance should record the firmware commit, board, volume limit, playback / stop, repeated playback and concurrent camera results. Mark checks not executed as pending.
