# 视觉对话与 Mac 协作交接

## 两个仓库都需要拉取吗？

完整视觉对话需要 **w0.5 + vi-agent 配套运行**。只开发摄像头、人脸检测、目标 ID 跟踪或后续电机跟踪时，可以先运行 w0.5 的相关模块，不必先下载语言及语音模型。

| 仓库 | 职责与入口 |
| --- | --- |
| [w0.5](https://github.com/orulink-ai/w0.5) | ESP32-P4 摄像头/音频固件、电脑端 USB 音视频接入、YuNet 检测与 ByteTrack ID 跟踪、可选嘴型辅助、设备控制服务；主要入口为 `tools/camera_facetrack/app.py` |
| [vi-agent](https://github.com/orulink-ai/vi-agent) | ASR、LLM、TTS、Pi 工具及记忆、统一网页；语音入口为 `packages/vi-agent/src/voice/board-cascade-main.ts` |

目录保持相邻，默认配置才能直接定位另一个仓库：

```text
workspace/
  w0.5/
  vi-agent/
```

两个仓库使用配套的 `feat/local-cascade-robot` 分支。**维护者须先把两个分支推送到远程，再让同事拉取；本地 commit 不会自动出现在同事电脑上。** 以下命令只在远程分支已经存在时执行，GitHub 私有仓库还需要同事账号有权限：

```bash
git clone --branch feat/local-cascade-robot https://github.com/orulink-ai/w0.5.git
git clone --branch feat/local-cascade-robot https://github.com/orulink-ai/vi-agent.git
```

交接时在两个目录分别执行 `git branch --show-current`、`git rev-parse HEAD`，核对维护者提供的配套版本。已有 checkout 时先检查未提交修改，避免覆盖同事的工作。后续电机实验应从配套版本另建自己的功能分支。

模型、`.venv*`、私有 `runtime/` 配置、日志和记忆没有随源码分发，不能期待 clone 后立即具备运行环境。请按本机路径重新生成配置，不复制 Windows 电脑的虚拟环境或私人会话记忆。

## 当前视觉对话链路

```text
ESP32-P4：IMX708 摄像头 + ES8311 麦克风/喇叭
  ↕ 同一 USB 串口，电脑端一个物理串口所有者
w0.5：serial_video.py / board_broker.py
  → YuNet 人脸检测 → ByteTrack 目标 ID → 人脸门控
  → voice_session.py → vi-agent 本地级联
  → SenseVoiceSmall INT8 → Ollama Qwen3 4B Q4 → 中文 VITS
  → 原音频通道回到开发板喇叭，音量 80
```

ASR/TTS 在主机 CPU，LLM 在主机 Ollama；不是把这些模型部署进 ESP32。`single` 与 `continuous` 两种人脸对话模式均由主机协调。嘴型辅助是可选项，电机跟踪本身不要求嘴型模型。

完整本地级联需要四个主机服务：模型 8790、工作台 API 8787、设备 8791、网页 5173，均使用本机地址。不要为绕过单机配置而直接把这些服务暴露到局域网。一个开发板串口只能有一个物理读写者，语音通过现有 broker 复用，不能另开第二个串口读摄像头数据。

Windows 安装与验收以配套 vi-agent 功能分支的 [本地级联部署说明](https://github.com/orulink-ai/vi-agent/blob/feat/local-cascade-robot/packages/vi-agent/docs/local-cascade-deployment.zh-CN.md) 和 [验收记录](https://github.com/orulink-ai/vi-agent/blob/feat/local-cascade-robot/packages/vi-agent/docs/local-cascade-acceptance.zh-CN.md) 为准；本地相邻 checkout 中也有相同路径的文档。本仓库入口见 [摄像头软件说明](../tools/camera_facetrack/README.md)。

## Mac 可以开发吗？

可以作为适配与开发平台，但当前交付的完整板载 USB 视觉对话主要在 Windows 验证，**尚无 macOS 端到端通过记录**。上游支持 Mac 不代表本项目已经完成跨平台适配。

Ollama 官方当前要求 macOS 14 或更新版本，Apple M 系列支持 CPU/GPU，Intel Mac 为 CPU 路径，见 [Ollama macOS 说明](https://docs.ollama.com/macos)。MediaPipe 官方列出 Mac 桌面支持，见 [Python 环境说明](https://developers.google.com/edge/mediapipe/solutions/setup_python)。本项目仍按 Python 3.12 准备；锁定版本的各个依赖是否提供该 Mac 架构的安装包，需要在同事机器验证。

### 模型兼容与推荐分工

Mac 端优先沿用现有模型，不必为了平台更换整条链路。SenseVoiceSmall INT8 和中文 VITS 当前通过 sherpa-onnx 在 CPU 运行；其官方 Python 安装说明列出 macOS arm64、x64 支持，见 [sherpa-onnx 安装说明](https://k2-fsa.github.io/sherpa/onnx/python/install.html)。LLM 继续使用 Ollama `qwen3:4b-instruct-2507-q4_K_M` 和 `vi-robot-local` 别名，M 系列可使用 GPU，Intel Mac 为 CPU 路径。上述平台支持不代表项目锁定版本及整机链路已经在 Mac 验收。

推荐协作方式：

- **现有 Windows + RTX4060 继续作为完整视觉对话与整机回归环境**，复用已经完成的开发板接入、模型部署和人工语音验证。
- **同事的 Mac 重点完成视觉到电机跟随的真实硬件端到端测试**。独立视觉验证和模拟输出只是接硬件前的步骤，最终必须让真实 ESP32 / STM32、驱动、电机及编码器参与闭环验证。该控制链不依赖 LLM、ASR 或 TTS，不必等完整模型部署完成。
- 两边按明确的视觉目标/运动接口协作，完成后再叠加语音回归，并验证完整 Mac 环境。代码通过各自功能分支提交，避免直接覆盖对方工作。

如需 Mac 同时常驻整套模型，优先建议 M 系列、16GB 及以上内存；这是开发配置建议，不是性能保证。先记录实际芯片与内存，再实测资源占用和延迟；Intel 或内存较小的机器可以先只跑视觉与运动开发。不要把 Windows 的实测延迟写成 Mac 的能力指标。

### 已知需要适配的地方

| 位置 | 当前情况与 Mac 工作 |
| --- | --- |
| `tools/camera_facetrack/robot-console.ps1` | 使用 Windows 进程管理、`npm.cmd`、COM 格式校验等；装上 PowerShell 本身不能解决，需新增或适配 macOS 生命周期入口 |
| `setup.ps1`、`setup-mouth.ps1` 与 vi-agent 的 `setup-local-cascade.ps1` | 当前按 Windows 环境准备；Mac 使用 `.venv/bin/python`，不能照用 `.venv/Scripts/python.exe` |
| `app.py`、`board_broker.py` | 多处对串口名 `.upper()`；需要保留 POSIX 设备路径原样，否则 `/dev/cu.*` 会变成错误路径，并统一 broker 注册、查询及启动参数 |
| `app.py` 热重载、`camera_setup.py` 等 | 仍有未按平台保护的 `subprocess.CREATE_NO_WINDOW`；需要按平台处理，并测试重启、取消及进程清理 |
| Python 图像、音频依赖 | 检查 Tk、OpenCV、PyAV、sherpa-onnx 及可选 MediaPipe 的目标架构安装与导入；不要混用 arm64 与 x86_64 环境 |
| 串口与设备 | 在 Mac 枚举实际 `/dev/cu.*` 设备，核对 USB 转串口芯片识别、4 Mbaud 收发及重连；不能沿用 `COM15` |
| 模型与 Pi 配置 | 使用相同模型选型重新准备，并保留 Ollama 别名 `vi-robot-local`、Pi profile 和生成模型目录；仅安装 Ollama 不等于配好完整对话 |

这些是交接时已发现的适配点，不是完整跨平台审计。不要通过关闭人脸门控、吞掉错误或绕过共享串口来“跑通”。USB 音视频仍应验证断开、重新连接、收音和完整播放。

### 可以先做的独立视觉验证

下面是基于现有入口的 **Mac 待验证步骤**，先使用 Mac 自带或外接 UVC 摄像头验证检测算法，不代表已经跑通 ESP32 USB 链路。系统需有带 Tk 的 Python 3.12，首次使用本机摄像头还需要授权：

```bash
cd w0.5/tools/camera_facetrack
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "import tkinter, cv2, av, serial, supervision"
.venv/bin/python face_engine.py
.venv/bin/python -m unittest tests.test_tracking tests.test_face_gate
.venv/bin/python app.py --autostart --source 0
```

先保持语音关闭，观察检测框、目标 ID 和画面方向。板载摄像头测试须等串口路径和平台调用适配完成；再从纯视频、板载收音/播放到完整对话逐层验证。Mac 上的实际帧率、模型延迟与持续稳定性需要重新测量，不能沿用 Windows 的验收数字。

## 后续“电机跟随人脸”的开发边界

当前 ByteTrack 的“跟踪”是画面中目标 ID 的关联，**尚未输出电机控制命令**。ESP32-P4 摄像头示例与 ESP32-C6 Mini / STM32 运动链路目前独立；C6 与 STM32 的完整联调尚待推进。已有 [单轴电机示例](../firmware/stm32/examples/encoder_read/README.md) 和 `tools/encoder_dashboard/motor_commands.py` 是单轴开环低速点动，不能当成已经实现的角度定位接口。

建议下一阶段按以下次序推进，这是待实现计划：

1. 固定一个被跟踪的目标 ID，将人脸中心与画面中心的偏差变成带时间戳的目标数据。明确原始图像、镜像、旋转与电机正方向的对应关系；不能直接拿显示后的坐标驱动电机。
2. 先做只显示控制意图的模拟输出，验证左/右方向、中心死区、平滑、限速与多人目标锁定；短时漏检不要来回切人，目标或画面过期停止输出运动意图。
3. 为视觉到运动的接口定义轴、速度或目标角、命令有效期、确认和停止语义。先确定电机端实际支持的控制模式；不要把连续跟踪简单拼成高频 `JOG` 请求。
4. 接入 STM32 运动状态机与编码器反馈，先验证单轴、限位和断联停止，再扩展双轴。是否经过 ESP32-C6 转发，取决于该阶段实际接通的硬件链路。
5. 视觉与电机先独立验收，再叠加 vi-agent 对话。跟随控制不应等待 ASR、LLM 或 TTS；离场后语音可以播完当前回复，电机则应按目标丢失规则停止，两者生命周期分开。

按 TDD 补上坐标变换、目标过期、多人锁定、方向、死区、限速及停止的失败测试，再接真实电机。硬件验收记录至少包含 Mac 型号/架构、系统版本、两个仓库 commit、固件版本、串口、电机轴与方向、编码器状态及测试结果。

## Mac 端硬件验收完成后移回 Windows

ESP32 与 STM32 上运行的是各自芯片的固件，运动逻辑不依赖上位机操作系统。同事在 Mac 完成运动固件与通信协议后，Windows 可以复用同一固件和协议，不需要因为换电脑重写电机逻辑。Windows 端仍须安装相应驱动、配置实际 COM 端口，并运行能发送相同命令、读取相同反馈的上位机代码；不能只确认 MCU 程序已烧录就宣称整机兼容。

Mac 阶段的交付目标是下列真实硬件链路，而不只是界面上出现检测框或打印模拟命令：

```text
真实摄像头 → 人脸检测/目标位置 → 上位机跟随控制
  → 运动主控 ESP32 → UART → STM32 → 驱动与电机
  ← 状态、命令确认及编码器反馈
```

图中的运动主控 ESP32 与摄像头 ESP32-P4 的角色、接线须先明确。若阶段性由上位机直接连接 STM32，应如实记录为直连测试，不能算已经覆盖 ESP32 转发链路。

至少完成以下硬件验收，再移回 Windows 做整机回归：

1. 确认真正收到摄像头画面、人脸位置及新鲜的编码器状态，核对轴、正反方向和供电接线。
2. 单人左/右移动时，真实电机向正确方向跟随；到达中心死区后停止，避免持续抖动。双轴功能需分别验证，不能用单轴结果代替。
3. 验证实际运动命令经过预定 ESP32 → STM32 路径，确认与反馈正常；记录下发成功、芯片确认和电机实际运动三者的区别。
4. 人脸消失、画面停更、上位机退出、串口断开或主控复位后，电机按固件约定超时停止，不依赖上位机最后补发一次 STOP。恢复连接不自动执行旧指令。
5. 记录固件源码版本、构建/烧录方式、运动协议版本、引脚、串口参数、电机与编码器配置，以及实际测试结果；尚未接通的链路明确标注。
6. Windows 接回同一硬件和配套代码后，重做方向、跟随、反馈与断联停止，再开启视觉对话，验证语音播放不阻塞运动控制、离场时电机停止而已提交回复可按对话策略播完。

完整 Mac 语音链路的适配可以后续单独进行；它不是完成这轮运动硬件端到端验收的前置条件。
