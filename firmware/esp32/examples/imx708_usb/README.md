# ESP32-P4 / IMX708 USB 视频示例

[English](README.en.md) · [电脑端](../../../../tools/camera_facetrack/README.md) · [协议及验证](../../../../docs/camera-imx708.md)

状态：当前源码为 `wtcc-live-18`，在板载麦克风与 SPK 喇叭基础上增加持续视频与语音共用串口的带宽余量，默认音量 **80**。原 `wtcc-live-15` 视频入口曾完成迁移后的 ESP-IDF v6.0.2 全量构建（2026-10-24，941,616 字节）；旧构建不代表本次并发音频改动已经通过实机验收。三声提示音在音量 80 下已由用户确认听到；LLaMA-Omni2 中文语音交互及持续预览下的音频完整性仍需实机测试。画质和自动对焦也仍需验收。此示例独立于 ESP32-C6 Mini 主控与 STM32 电机固件。

v18 构建验证（2026-10-24）：ESP-IDF v6.0.2 增量构建及分区尺寸检查通过，应用为 1,031,360 字节；离线 C 传输测试通过。该记录只覆盖编译和主机逻辑，不代表 4 Mbaud 声画并发或中文对话已经通过实机测试。

## 代码组织

`overlay/` 保存完整的修改后源文件，包含应用主文件、串口命令、USB H.264 封装、IMX708 ISP 配置及 DW9807 对焦驱动，便于代码审查和断点定位。未修改的驱动与示例骨架由 [上游仓库](https://github.com/mushBrainDave/esp32-p4-imx-camera) 提供，固定在提交 `9a3f8ca28e93526e0854ba45ad3b461b33ef2dac`；原 Apache-2.0 许可证保存在 `UPSTREAM-LICENSE`。

`prepare.py` 创建独立检出目录并覆盖源码，不修改现有工程，不编译、不烧录。目标目录已存在时拒绝覆盖。构建工程生成到相邻的 `imx708-project/` 短路径目录，避免 Windows 深层依赖路径过长；使用自定义目标时工程名为 `<目标目录名>-project`。`dependencies.lock` 来自已成功构建的依赖解析，调整了本地组件的相对路径；`board.defaults` 记录实测板型覆盖配置。

## 硬件

- ESP32-P4 v3.2，32 MB Flash、32 MB PSRAM；DIO / 80 MHz，PSRAM 200 MHz。
- IMX708 Wide NoIR 摄像头与 DW9807 对焦马达，CSI 排线连接；SCCB SCL GPIO8、SDA GPIO7，马达地址 `0x0c`。
- 当前 Type-C 接 CH343 USB-UART，UART0 TX GPIO37 / RX GPIO38，4 Mbaud、8N1；COM15 是开发机端口示例。
- 板载无线协处理器为 C6；本版本不启动 Wi-Fi，不需要网络或原生 USB 高速转接线。

不同 P4 板卡不应直接套用引脚。CSI 排线与供电接线应在断电时调整。此示例输出视频和音频，不驱动云台或机器人电机。

## 麦克风与喇叭

ESP32-P4-WIFI6 板上的 ES8311（I2C 地址 `0x18`）共用已初始化的摄像头 I2C0；NS4150B 功放使能为 GPIO53。I2S0 的 MCLK/BCLK/WS/DOUT/DIN 分别为 GPIO13/12/10/9/11。喇叭接板上 **SPK** 二针座，不直接接 GPIO；采集使用板载麦克风。驱动依赖固定为 `espressif/esp_codec_dev 1.6.2`。

初始化只在 `AUDIO START` 时执行，音量固定 80、麦克风增益 30 dB。线缆上传输 **24 kHz、单声道、PCM16LE**，每包最多 480 样本（20 ms）；I2S 内部使用双声道，播放复制左右声道，采集取左声道。视频和音频共用串口，由电脑端唯一串口所有者分流视频、麦克风及 ACK；不因检测到人脸或开始语音而发送 `VIDEO OFF`。电脑端只在 AI 播放时暂停麦克风，避免自己的回复被再次录入，视频仍保持预览。

v18 在采集或播放活跃时将视频目标从 2.4 Mbit/s、28 FPS 调为 1 Mbit/s、14 FPS，结束后恢复；没有改变画面尺寸、接线或音量。I2S DMA 从 40 毫秒增加至 200 毫秒，`AUDIO END` 的静音及排空等待同步增加。UART RX FIFO 在 32 字节时触发读取、尾部超时设为 2 个符号周期，增加 4 Mbaud 突发下行余量。主机必须遵守 `AUDIO_RX` 接收许可，再发送原始 PCM；这些措施仍需测量 CRC、MIC 序号、ACK 延迟和实际声音，码率设置不能保证最大 IDR 帧尺寸。

| 命令 | 返回及含义 |
| --- | --- |
| `AUDIO START` | `AUDIO_READY rate=24000 volume=80`，或 `AUDIO_ERROR ...` |
| `MIC START` / `MIC STOP` | `MIC_READY ...` / `MIC_STOPPED`；采集期间持续输出 `MIC_DATA <序号> <PCM的base64>` |
| `AUDIO DATA <序号> <CRC32十六进制> <base64>` | 校验后播放，返回 `AUDIO_ACK <序号>` |
| `AUDIO BIN <序号> <字节数> <CRC32十六进制>` | 先等 `AUDIO_RX <序号> <字节数>`，再发送原始 PCM，最后等 `AUDIO_ACK <序号>`；最多 960 字节 |
| `AUDIO END` | 写入静音并排空 DMA 后返回 `AUDIO_DONE`；ACK 本身只表示该包已写入 |
| `AUDIO STOP` | 静音、清空待播放数据并返回 `AUDIO_STOPPED` |
| `AUDIO TONE` | 诊断方波，完成返回 `AUDIO_TONE_DONE ...` |
| `AUDIO BAUD 1000000` / `AUDIO BAUD 4000000` | 收到旧速率的 `AUDIO_BAUD ...` 后，电脑端同步切换串口速率 |

所有文本命令以 LF 结束。CRC32 使用与 `esp_rom_crc32_le(0, ...)` / Python `zlib.crc32` 相同的值，作用于解码后的单声道 PCM。`STATUS` 包含 `fw=wtcc-live-18 audio=pcm24k mic=pcm24k volume=80`。驱动写入成功、主机测试或模型 HTTP 就绪都不能替代现场听音和真实中文对话验收。

## 准备与构建

安装并激活 ESP-IDF **v6.0.2** 的 ESP32-P4 工具链，然后在仓库根目录运行：

```powershell
python firmware/esp32/examples/imx708_usb/prepare.py
cd .camera-sdk/imx708-project
idf.py -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.board" build
```

也可用 `prepare.py --source <本地上游Git仓库> --destination <全新目录>` 离线复用上游 Git 对象；组件首次下载仍可能需要网络。原上游 README 描述 Wi-Fi 示例，当前行为以本目录文档为准。`sdkconfig.defaults` 保留部分旧网络配置和历史注释，但当前入口不启动网络。

## 应用更新

先退出电脑端预览。仅适用于已经确认具有相同 bootloader、32 MB Flash 和 4 MB factory 分区（偏移 `0x10000`）的本次实测开发板：

```powershell
python -m esptool --chip esp32p4 --port COM15 --baud 2000000 write-flash 0x10000 build/imx708_wifi_video.bin
```

该命令仅更新应用。不得直接对未知板卡执行；首次部署须先核对分区、芯片版本、引脚与供电，另外制定 bootloader / 分区部署步骤。不要把本示例烧到 ESP32-C6 Mini 或 STM32。不要擦除全片、改 eFuse、烧录 NVS 备份或覆盖无线协处理器固件。

## 主机测试

准备完成后，在构建示例目录运行：

```powershell
python main/test/run_host_tests.py --clang <主机clang路径>
```

需要支持本机目标的 Clang / LLD，或使用 `--zig <zig路径>`。测试涵盖部分写、总截止时间、阻塞端、零/错误写入、IDR 恢复及 PTS 回绕，不访问设备。

## 已知限制

目标采集 1920×1080、28 FPS，编码中心裁切为 1920×1072、2.4 Mbit/s H.264。它不是 1200 万像素输出，也不保证持续 28 FPS 或零丢帧。4 Mbaud 是串口线速，8N1 的有效字节带宽小于线速。

当前焦点与强背光画质仍存在问题；最新焦点扫描因没有检测到人脸而未完成。高分辨率并不等于已经获得更清晰的光学图像。详细实测和后续验收见技术说明。
