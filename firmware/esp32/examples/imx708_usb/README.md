# ESP32-P4 / IMX708 USB 视频示例

[English](README.en.md) · [电脑端](../../../../tools/camera_facetrack/README.md) · [协议及验证](../../../../docs/camera-imx708.md)

状态：`wtcc-live-15` 已在原调试工程构建、烧录并通过串口版本查询；迁移后的入口也已完成源码准备与 ESP-IDF v6.0.2 全量构建（2026-10-24，应用 941,616 字节，未再次烧录）。画质和自动对焦仍需实机验收。此示例独立于 ESP32-C6 Mini 主控与 STM32 电机固件，不会默认参与它们的构建。

## 代码组织

`overlay/` 保存完整的修改后源文件，包含应用主文件、串口命令、USB H.264 封装、IMX708 ISP 配置及 DW9807 对焦驱动，便于代码审查和断点定位。未修改的驱动与示例骨架由 [上游仓库](https://github.com/mushBrainDave/esp32-p4-imx-camera) 提供，固定在提交 `9a3f8ca28e93526e0854ba45ad3b461b33ef2dac`；原 Apache-2.0 许可证保存在 `UPSTREAM-LICENSE`。

`prepare.py` 创建独立检出目录并覆盖源码，不修改现有工程，不编译、不烧录。目标目录已存在时拒绝覆盖。构建工程生成到相邻的 `imx708-project/` 短路径目录，避免 Windows 深层依赖路径过长；使用自定义目标时工程名为 `<目标目录名>-project`。`dependencies.lock` 来自已成功构建的依赖解析，调整了本地组件的相对路径；`board.defaults` 记录实测板型覆盖配置。

## 硬件

- ESP32-P4 v3.2，32 MB Flash、32 MB PSRAM；DIO / 80 MHz，PSRAM 200 MHz。
- IMX708 Wide NoIR 摄像头与 DW9807 对焦马达，CSI 排线连接；SCCB SCL GPIO8、SDA GPIO7，马达地址 `0x0c`。
- 当前 Type-C 接 CH343 USB-UART，UART0 TX GPIO37 / RX GPIO38，4 Mbaud、8N1；COM15 是开发机端口示例。
- 板载无线协处理器为 C6；本版本不启动 Wi-Fi，不需要网络或原生 USB 高速转接线。

不同 P4 板卡不应直接套用引脚。CSI 排线与供电接线应在断电时调整。此示例只输出视频，不驱动云台或机器人电机。

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
