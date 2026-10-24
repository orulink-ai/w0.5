# 摄像头预览与人脸追踪

[English](README.en.md) · [固件与接线](../../firmware/esp32/examples/imx708_usb/README.md) · [技术说明](../../docs/camera-imx708.md)

状态：可运行的硬件调试版本，画质、自动对焦及持续帧率尚未验收。人脸检测采用 YuNet，连续帧 ID 关联采用 ByteTrack；不做人脸身份识别，不控制机器人电机。

## Windows 安装与运行

需要 Python 3.12（含 Tk）、可用的 USB 数据线及 CH343 驱动。端口在设备管理器查看；COM15 只是本机默认值。

```powershell
cd tools/camera_facetrack
powershell -ExecutionPolicy Bypass -File setup.ps1
.venv\Scripts\python.exe app.py --watch --autostart --source serial://COM15
```

也可双击 `start-dev.cmd`（热更新）或 `start.cmd`。首次安装从 OpenCV Zoo 下载 YuNet 模型；模型保存在被 Git 忽略的 `models/`。无需配网。测试本机摄像头可用 `--source 0`。停止按钮释放端口，退出窗口关闭程序。热更新会重启应用并重新连接设备。

画面支持左转、右转、重置和镜像；只改变图像方向，不转动物理镜头。右上角显示实际显示 FPS；底部显示原始画面尺寸、处理 FPS、推理耗时及读取后耗时。读取后耗时不包含摄像头采集与传输，不能作为端到端延迟。

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
| `serial_video.py` | 串口分帧、CRC、IDR 恢复、PyAV H.264 解码 |
| `face_engine.py` | YuNet 检测、ByteTrack 关联、标注 |
| `camera_setup.py` / `video_source.py` | 保留的配网 / HTTP 调试模块，当前 USB 路径不使用 |
| `tools/` / `tests/` | 有时间限制的诊断及离线回归测试 |

默认串口为 4,000,000 baud；旧 2 Mbaud 固件可设置 `$env:WTCC_SERIAL_BAUD='2000000'`。两端波特率必须一致。不要在摄像头运行时同时打开串口监视器或烧录工具。

许可证及模型来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本次迁移不包含模型权重、现场照片、Wi-Fi 凭据、固件备份或编译二进制。
