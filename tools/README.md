# 开发工具

## 摄像头 / Camera

仓库根目录统一运行 `python tools/camera.py <命令>`：`setup` 安装、`run` 正常启动、`dev` 热更新、`test` 回归测试、`check-usb --port COM15 --seconds 25` 传输诊断、`focus --port COM15` 实验性对焦诊断、`prepare-firmware` 准备固定版本源码、`test-firmware --clang <主机编译器>` 主机 C 测试、`build-firmware` 在已激活的 ESP-IDF 环境中编译。端口可用 `--port` 指定，GUI 也可用 `--source 0` 测试本机摄像头；脚本不执行烧录。

English: `python tools/camera.py` wraps installation, normal/hot-reload preview, regression tests, bounded USB diagnostics, experimental focus scanning, pinned firmware preparation, host C tests and firmware building. Specify `--port` for hardware or `--source 0` for a PC webcam. No command flashes hardware automatically. See [中文](camera_facetrack/README.md) / [English](camera_facetrack/README.en.md).

## STM32

`stm32.py` 提供独立的 STM32 AS5600 PWM 示例入口；在仓库根目录运行：

```sh
python3 tools/stm32.py test
python3 tools/stm32.py build
python3 tools/stm32.py upload
python3 tools/stm32.py monitor --port /dev/cu.usbmodem实际设备名
python3 tools/stm32.py dashboard --port /dev/cu.wchusbserial130
```

`upload` 会覆盖芯片现有程序，执行前断开电机驱动。默认通过开发板 USB CDC 输出日志，要求 Type-C 数据通路接到 MCU；备用 PA2/PA3 串口版本用 `--env g431_as5600_uart` 选择。接线详见 `firmware/stm32/examples/encoder_read/README.md`。以上命令不构建 ESP32 固件。

新环境使用 `python3 -m venv .venv`，然后 `.venv/bin/python -m pip install -r tools/requirements-stm32.txt`。PlatformIO 的平台、板型、依赖及下载协议由示例的 `platformio.ini` 固定。

[AS5600 角度调试台](encoder_dashboard/README.md)运行于 `http://127.0.0.1:8840`，显示角度、PWM 频率/脉宽/周期和有效状态。当前 `--env g431_motor_gpio` 固件支持 PB5 使能、三秒低速点动及停止，均经双向串口等待芯片确认；默认禁用，不自动转动。0°/90°/180°/270°四个按钮属于旧固件的目标暂存，在点动固件中禁用，尚无角度闭环定位。TTL TXD 接 PA3、RXD 接 PA2、GND 共地；与终端串口监视器切换使用。
