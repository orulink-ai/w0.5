# W0.5 桌面机器人

采用 monorepo 管理 ESP32 主控固件、STM32 运动控制固件、共享通信协议和集成测试。

已实现 STM32G431CBT6 的 AS5600 PWM 读角、PB5 使能和网页手动低速点动，采用 STM32duino + PlatformIO + SimpleFOC。单轴硬件为 12V GB2806（7 极对）、DengFOCmini MP6536 与 AS5600；编码器及使能已实测，用户已确认电机能正常运动。当前点动为速度开环，角度闭环定位尚未实现；双电机和 ESP32-C6 Mini 联调仍待推进。

## 目录

```text
firmware/
  esp32/
    app/               # 正式主控程序入口
    examples/          # Wi-Fi、UART 等独立上板验证程序
    tests/             # ESP32 自动化单元测试
  stm32/
    app/               # 正式运动控制程序入口
    examples/          # 编码器、单电机、双电机验证程序
    tests/             # STM32 自动化单元测试
shared/
  protocol/
    tests/             # 共享协议自动化测试与固定测试向量
hardware/              # 硬件接口、引脚、供电与板卡资料
tools/                 # 构建、烧录与调试入口
tests/
  integration/         # 两端通信与故障恢复集成测试
experiments/           # 临时原型与探索
docs/                  # 架构、测试及硬件验证说明
```

## 开发原则

- 两套固件独立构建、独立烧录，不直接引用对方的源码。
- 共享协议代码保持平台无关，不依赖 ESP-IDF、STM32 HAL 或 RTOS。
- 业务逻辑通过接口访问通信、时钟和硬件，便于在主机上测试。
- 对协议、状态机和故障逻辑先写失败测试，再实现；上板验证记录硬件版本和参数。
- 板间采用 UART；协议语义与 UART 收发、分帧适配分离。

测试功能放置与新增方法见 [测试说明](docs/testing.md)。[AS5600 PWM 示例](firmware/stm32/examples/encoder_read/README.md)采用 STM32duino + PlatformIO + SimpleFOC，其他示例仍为文档骨架。

详见 [架构说明](docs/architecture.md) 与 [硬件验证清单](docs/bringup.md)。

## 摄像头模块 / Camera module

新增独立 ESP32-P4 + IMX708 USB 视频与电脑端 YuNet / ByteTrack 追踪调试版本。它不控制现有电机，画质与持续帧率仍待验收。

```powershell
python tools/camera.py setup
pwsh -File tools/camera_facetrack/robot-console.ps1 -Action Start -OpenBrowser
python tools/camera.py test
```

中文：[软件运行](tools/camera_facetrack/README.md)、[固件构建与接线](firmware/esp32/examples/imx708_usb/README.md)、[协议与验证](docs/camera-imx708.md)。

English: [desktop setup](tools/camera_facetrack/README.en.md), [firmware and wiring](firmware/esp32/examples/imx708_usb/README.en.md), [protocol and validation](docs/camera-imx708.en.md). The camera example is independent of motion control; image quality and sustained FPS remain under validation.

统一启动器读取 `tools/camera_facetrack/robot-console.example.json` 或私有 `runtime/robot-console/config.json`，默认管理 LLaMA-Omni2 端到端语音模型、隐藏的摄像头后台与一个网页入口，无需任何 API Key 或额外文本模型。可配置路径、串口和 camera/faceVoice/workbench 开关；workbench 默认关闭，不让 Pi 或云配置阻塞原生语音。模型环境、权重与依赖须先安装。`-Action Status|Logs|Stop|Restart` 管理本脚本创建的服务，复用的已有服务不会被结束。中英文安装步骤见上面的软件运行说明。

麦克风与喇叭使用同一 ESP32-P4 上的 ES8311，音量保持 80。人脸触发语音通过相邻的 vi-agent 项目对话，默认在场连续对话，也可选择须离开后重新出现才触发下一轮的单轮模式；电脑端单一 UART broker 在 4 Mbaud 下分流视频、麦克风和音频确认，视频与人脸追踪持续运行。v19 使用 400ms 软件播放缓冲及 200ms 预填充，音频期间将视频目标降为 1Mbps / 14FPS。控制台提供本机 HTTP 8791，统一网页入口为 `http://127.0.0.1:5173`。此前手动中文语音已获用户确认；v19 已刷入并完成过人脸自动触发的并发回合。同一 Node 进程持续会话已实测多轮；本次第三轮的实际原因是 12 秒未检测到讲话而超时，期间收到 607 个麦克风包，序号缺口和传输错误均为 0，并非 bridge 断连。首因保留已修复；正在调整为安静时持续聆听、仅无音频包等异常才报错，尚待实机回归。会话端已延长 45 秒看门狗并接入心跳，相关 7 项回归通过。当前模型首音频约 6–13 秒，音质与流畅性尚未验收。配置见[电脑端语音说明](tools/camera_facetrack/README.md#人脸触发语音实验)。
