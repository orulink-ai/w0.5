# 摄像头预览与人脸追踪

## 本地 ASR + LLM + TTS（当前功能分支）

2026-10-24 本地级联现场回归已完成连续多轮、离场停麦，用户确认播报能听清；两轮实测首包 ACK 为 650/667ms（另加判停与喇叭预填充）。完整记录见 [vi-agent 验收报告](../../../vi-agent/packages/vi-agent/docs/local-cascade-acceptance.zh-CN.md)。单轮模式本次仅自动化覆盖，未执行现场回归；下文原生模式旧测试记录不代表级联模式当前结果。

使用相邻 vi-agent 的 `packages/vi-agent/scripts/setup-local-cascade.ps1` 安装 SenseVoiceSmall INT8、Ollama Qwen3 4B Q4_K_M 和中文 VITS，然后运行本目录 `setup.ps1` 准备摄像头。复制 `robot-console.cascade.example.json` 到 `runtime/robot-console/config.json` 后执行 `robot-console.ps1 -Action Start`。完整部署与验证说明在 vi-agent 的 `packages/vi-agent/docs/local-cascade-deployment.zh-CN.md`。

`pipeline=local-cascade` 必须启用 `features.workbench=true`；启动模型、工作台 API、设备和网页，所有服务必需。网页统一显示中文识别、助手回复、Pi 任务、长期记忆和延迟；不显示浏览器云语音连接按钮。Pi 用本机 Ollama，记忆落盘到 vi-agent `.local-cascade/workbench`。保留人脸单轮触发和在场连续两种模式、离场取消、摄像头持续预览、音量固定 80。判停静音改为 450ms，CPU 人脸推理限制为 1 线程，避免与 ASR/TTS 争抢。输入识别与每段合成仍为离线推理，不能保证全链路亚秒。

本链路由 `voice_session.py` 选择 `board-cascade-main.ts`，与原生入口共用音频 broker。下文 LLaMA-Omni2 原生模式为保留的独立入口，其“不接工作台记忆/Pi”的限制不适用于 local-cascade。固件须实际返回 `AUDIO_READY rate=24000 volume=80`；若板上仍为 volume=60 等旧测试固件，必须更新配套应用，不能只改网页标签。

[English](README.en.md) · [固件与接线](../../firmware/esp32/examples/imx708_usb/README.md) · [技术说明](../../docs/camera-imx708.md)

状态：可运行的硬件调试版本，画质、自动对焦及持续帧率尚未验收。人脸检测采用 YuNet，连续帧 ID 关联采用 ByteTrack；不做人脸身份识别，不控制机器人电机。

## Windows 安装与运行

需要 Python 3.12（含 Tk）、可用的 USB 数据线及 CH343 驱动。端口在设备管理器查看；COM15 只是本机默认值。

```powershell
cd tools/camera_facetrack
powershell -ExecutionPolicy Bypass -File setup.ps1
New-Item -ItemType Directory runtime/robot-console -Force
Copy-Item robot-console.example.json runtime/robot-console/config.json
pwsh -File robot-console.ps1 -Action Start -OpenBrowser
```

统一入口只打开一个网页 `http://127.0.0.1:5173`；摄像头程序以 `--headless` 隐藏 Tk 窗口运行。默认 `VI_NATIVE_ONLY=true` 仅显示开发板控制及真实回复，不挂载云语音、工作台轮询、文字发送或 Key 设置。脚本兼容 Windows PowerShell 5.1 与 PowerShell 7，`-OpenBrowser` 可省略，避免重复打开系统浏览器。首次安装从 OpenCV Zoo 下载 YuNet 模型，保存在被 Git 忽略的 `models/`。

先按相邻 vi-agent 项目的语音说明准备 Node.js 依赖、本地 LLaMA-Omni2 权重、CUDA Python 环境和 Matcha/Whisper 源码；脚本不下载或安装依赖，也不烧录固件。默认仅使用端到端语音模型，不需要 API Key、额外文本模型或云 ASR/TTS，故障时不会回退云服务。

配置中的路径均相对于 `robot-console.ps1` 所在目录解析，绝对路径同样可用；`modelRoot` 指向 LLaMA-Omni2 源码及其 `models/`，`modelPython` 指向装好推理依赖的虚拟环境。修改私有 `runtime/robot-console/config.json` 或传 `-Config 路径`；无私有文件时读取示例。JSON 只存路径、串口、功能和端口，不存任何凭据。`features.camera` 与 `faceVoice` 默认 true，后者依赖前者；`workbench` 默认 false，不启动 Pi 或独立文字模型。可选工作台只有显式启用才启动，其失败会单独警告，不关闭摄像头和原生语音。

```powershell
pwsh -File robot-console.ps1 -Action Status
pwsh -File robot-console.ps1 -Action Logs -Tail 40
pwsh -File robot-console.ps1 -Action Restart
pwsh -File robot-console.ps1 -Action Stop
```

脚本默认编排原生语音模型 8790、设备 8791 和网页 5173，可选工作台 API 8787 默认关闭，端口可配置。健康的已有服务会复用并标为 external/unmanaged，Stop/Restart 不接管或结束它们。自有进程按 PID、启动时间、命令与路径核实后管理。模型加载最多等待 180 秒（可用 `-ModelTimeoutSeconds` 调整），每 10 秒提示进度，日志写入私有 runtime。不兼容端口占用会报错，不换端口或结束其他程序。Logs 只读取最多 8 份本脚本日志末尾，不读取 `.env`。服务健康不代表开发板声学已验收。

开发时仍可单独运行 `.venv\Scripts\python.exe app.py --watch --autostart --source serial://COM15`，或使用 `start-dev.cmd` / `start.cmd` 打开浅色 Tk 调试界面；不要与统一入口同时启动第二个串口所有者。测试本机摄像头可用 `--source 0`。热更新会重启应用并重新连接设备。

画面支持左转、右转、重置和镜像；只改变图像方向，不转动物理镜头。右上角显示实际显示 FPS；底部显示原始画面尺寸、处理 FPS、推理耗时及读取后耗时。读取后耗时不包含摄像头采集与传输，不能作为端到端延迟。

## 人脸触发语音（实验）

先准备带音频组件的 v19 固件，以及相邻目录的 `vi-agent` 项目。vi-agent 需安装 Node.js 依赖并运行本机 LLaMA-Omni2 服务（默认 `http://127.0.0.1:8790`）；服务启动和模型依赖详见该项目 `packages/vi-agent/docs/voice-workbench.zh-CN.md`。默认查找 `w0.5` 同级的 `vi-agent`，其他位置用环境变量指定：

```powershell
$env:WTCC_VI_AGENT_ROOT='D:/work/wtcc/vi-agent'
python tools/camera.py run --port COM15
```

统一启动器按 faceVoice 配置启用语音；单独 Tk 调试界面默认关闭。首次必须等待新鲜画面中的人脸稳定出现 1 秒才开启麦克风；人工聆听按钮也经过门控，不能关闭人脸触发或绕过检测。默认最低 RMS 250、噪声底 50，讲话后静音约 800ms 提交一轮，录音最长 15 秒。摄像头预览与人脸追踪持续运行。

| 对话模式 | 行为 |
| --- | --- |
| 在场连续对话（`continuous`，默认） | 同一 Node 进程在播放结束后立即恢复聆听；人脸离开达到 0.75 秒或画面超过 1 秒未更新时，在收音、生成或播放任意阶段取消会话。 |
| 单轮触发（`single`） | 人脸出现后执行一次 `--once` 回合；完成后须先离开再重新出现，才会重新触发，避免同一人在场反复启动。 |

模式通过控制台选择，保存到被忽略的 `runtime/view-settings.json` 的 `voice_mode`，重启后恢复。HTTP `configure` 命令的 `mode` 只接受 `single` 或 `continuous`，未知值会被拒绝。模式切换会取消正在进行的旧会话。没有人脸时不开启麦克风；实际声学与连续稳定性仍需现场验收。

控制台显示聆听、思考、播放、错误和回复文字，音量固定为 80。「停止 / 取消」通知 vi-agent 结束音频会话；关闭窗口也会取消。首次服务准备有超时保护，录音最长 15 秒。v19 使用 400ms 软件播放缓冲及 200ms 预填充。单一 UART broker 在 4 Mbaud 下共享视频与音频，v19 在麦克风或喇叭工作期间将视频目标设为 1Mbps / 14FPS，空闲时恢复 2.4Mbps / 28FPS；实际显示帧率受传输及解码影响。回复生成和播放期间暂停麦克风，暂不支持插话，也没有接入电机控制。

`voice_session.py` 按所选模式调用 vi-agent 的 `board-omni-main.ts --json-events`（单轮追加 `--once`），通过带临时凭据的本机 TCP broker 操作音频，不另开物理串口；音频采集、判停与播放仍由 vi-agent 管理。模型地址仅接受本机 HTTP。原生音频轮次目前独立回答，未接工作台记忆与 Pi 工具；模型和现场录音不入仓库。模型服务尚未就绪时显示错误，摄像头继续运行。

GUI 启动本机 HTTP 服务 `http://127.0.0.1:8791`，提供 `/api/robot/status`、`/api/robot/camera.mjpeg` 与 `/api/robot/control`；统一网页入口为 vi-agent 的 `http://127.0.0.1:5173`。8791 是状态、预览及控制服务，8790 是模型推理服务，音频 TCP broker 使用独立临时端口。网页电平只在实际聆听时显示，数值取开发板 PCM 峰值；累计音频包、序号缺口和错误数仅用于诊断，旧包数不代表正在收音。助手文字会同步到网页对话区，没有独立 ASR 用户转写。`transport_stats` 保留最近 8 条音频控制错误元数据；仅明确收到 `invalid_pcm` 负确认才允许同一序号重发，最多 3 次发送尝试（首次加 2 次重试），确认超时不重发，避免重复播放。异常链保留最初的 bridge/模型错误，后续停止或清理错误不应覆盖首因。

「测试喇叭」使用提示“请用中文简短介绍一下你自己。”让本地原生模型生成中文回复并播放，内容并非固定问候或逐字播报；不会开启麦克风，也不会启用自动对话。HTTP 控制返回 202 表示命令已入队，执行结果以之后的实际设备状态为准。

验证范围：此前已完成一次控制台手动中文语音回合，用户确认开发板正常回复，并另行确认音量 80 的播放清楚合适。v19 已刷入，并完成过持续预览下的人脸自动触发回合（其中一轮录入 1.68 秒、播放 5.64 秒）。同一 Node 进程持续会话已实测多轮；本次第三轮的实际原因是 12 秒未检测到讲话而超时，期间收到 607 个麦克风包，序号缺口和传输错误均为 0，并非 bridge 断连。首因保留已修复；正在调整为安静时持续聆听、仅无音频包等异常才报错，尚待实机回归。会话端已延长 45 秒看门狗并接入心跳，相关 7 项回归通过。当前模型首音频约 6–13 秒，音质与流畅性尚未验收。本轮离线回归有摄像头侧 68 项、TypeScript 20 项通过，并补充首因保留及会话心跳相关 7 项回归；这些不替代实机连续稳定性和听音验收。

## 调试与测试

以下诊断工具独占串口，先停止预览并退出其他串口监视器。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tools/check_usb.py --port COM15 --seconds 25
.venv\Scripts\python.exe tools/calibrate_focus.py --port COM15
```

`check_usb.py` 输出有效帧数、CRC 错误、序号缺口、接收速率和最长到达间隔；它验证传输，不验证清晰度。`calibrate_focus.py` 是实验性人脸 ROI 焦点扫描，需要人脸稳定、光照正常；找不到脸会拒绝以背景作对焦目标并恢复自动对焦。该工具会在本机 `runtime/` 写诊断图片和报告；不要提交这些文件。

`runtime/` 包括本地视图配置、状态和诊断结果，`.venv/` 是本地环境，均已忽略。测试中遗留的 HTTP 解码用例需要 PATH 中有 FFmpeg，否则自动跳过；USB 使用 PyAV，无需单独安装 FFmpeg 命令行。旧配网及 HTTP 模块保留测试覆盖，当前 GUI 不提供配网按钮，固件不启动 Wi-Fi。

## 源码导航

| 文件 | 职责 |
| --- | --- |
| `app.py` | Tk 界面、工作线程、图像旋转、统计、热更新与重连 |
| `robot-console.ps1` / `robot-console.example.json` | 统一网页启动、功能与路径配置、服务健康及自有进程管理 |
| `serial_video.py` / `board_broker.py` | 唯一串口读写、视频分帧与解码、麦克风及音频确认分流、本机音频 broker |
| `robot_console_server.py` | 本机 HTTP 状态、预览与控制 |
| `face_engine.py` | YuNet 检测、ByteTrack 关联、标注 |
| `face_gate.py` / `voice_panel.py` | 人脸触发去抖、语音控制与会话状态 |
| `voice_session.py` | 调用 vi-agent 持续语音、状态转发、取消及子进程回收 |
| `camera_setup.py` / `video_source.py` | 保留的配网 / HTTP 调试模块，当前 USB 路径不使用 |
| `tools/` / `tests/` | 有时间限制的诊断及离线回归测试 |

默认串口为 4,000,000 baud；旧 2 Mbaud 固件可设置 `$env:WTCC_SERIAL_BAUD='2000000'`。两端波特率必须一致。不要在摄像头运行时同时打开串口监视器或烧录工具。

许可证及模型来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本次迁移不包含模型权重、现场照片、Wi-Fi 凭据、固件备份或编译二进制。
