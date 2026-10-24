# IMX708 摄像头技术说明

[English](camera-imx708.en.md) · [固件](../firmware/esp32/examples/imx708_usb/README.md) · [电脑端](../tools/camera_facetrack/README.md)

## 集成边界

摄像头模块为 ESP32-P4 + IMX708 + DW9807，经 CH343 串口向电脑发送 H.264。电脑运行 YuNet + ByteTrack。它与仓库现有 ESP32-C6 Mini / STM32 运动控制独立；没有接入板间运动命令，也没有实现物理云台跟随。ID 仅用于当前视频会话的连续目标关联。

```text
IMX708 RAW10 → P4 CSI / ISP → YUV420 → 硬件 H.264
  → UART0 / CH343 / USB → CRC校验 / PyAV → YuNet / ByteTrack → Tk GUI
```

固件采用固定上游提交加可读源码覆盖层，避免将 SDK、构建缓存或机器路径带进仓库。硬件示例单独构建，正式主控不依赖电脑端目录。

## USB 帧协议 v1

串口 4,000,000 baud、8N1。每个包为 28 字节头加一个 H.264 编码负载；整数使用小端无符号 32 位。不要直接按本机结构体布局解包。

| 偏移 / 字节 | 字段 | 含义 |
| --- | --- | --- |
| 0 / 8 | magic | ASCII `WTCCUV1` 后跟 `00` |
| 8 / 4 | length | 编码负载字节数，接收上限 512 KiB |
| 12 / 4 | sequence | 帧序号，用于检查缺口 |
| 16 / 4 | pts_ms | 设备时间戳，32 位毫秒计数 |
| 20 / 4 | flags | IDR 标志，当前以 1 表示 IDR |
| 24 / 4 | crc32 | 元数据 16 字节（length 至 flags）再接负载的 CRC32，初值 0 |
| 28 / length | payload | H.264 数据 |

固件在同一输出锁内写完整包，日志只允许出现在包间。接收端按 magic 重同步并检查长度及 CRC；序号缺口或损坏后等待 IDR 恢复，不能随意丢掉 H.264 参考帧继续解码。GUI 的最新帧队列容量为 1，处理跟不上时会替换旧画面；因此不承诺每帧都展示。

ASCII 命令以换行结束：`STATUS` 查询版本，`VIDEO ON` / `VIDEO OFF` 控制视频。视频租约为 5 秒，电脑端每 2 秒续租。ISP 调试命令：`IMAGE STATUS`、`IMAGE TARGET 32..112`、`IMAGE BLACK 0..32`；对焦命令 `IMAGE FOCUS 400..720` / `IMAGE FOCUS AUTO`。参数为当前运行设置，不写入 NVS。焦点读数是驱动接受的位置，不是实际光学距离。

v18 保持 v1 视频协议：一个主机串口所有者持续读取，先按视频头长度精确消费二进制，包间文本再分流 `MIC_DATA` 和 `AUDIO_*`。H.264 负载中的换行或可打印文字不能当成控制事件。所有主机写入共用事务锁，`AUDIO BIN` 头、等待 `AUDIO_RX`、PCM、等待 ACK 期间不得插入视频保活或其他命令。语音开始不关闭视频；播放时只暂停麦克风。

音频活跃时编码目标为 1 Mbit/s、14 FPS，空闲恢复 2.4 Mbit/s、28 FPS；I2S DMA 为 200 毫秒，RX FIFO 中断阈值为 32 字节。4 Mbaud 8N1 约有 400 KB/s 单向有效字节带宽，1 Mbit/s 视频加 base64 麦克风约占 190 KB/s，实际仍有 IDR 突发及调度开销。固件整视频帧仍共用输出锁，不能保证最坏音频等待时间；并发能力需实测，不得只凭平均码率宣称稳定。

## 参数与画质

`wtcc-live-15` 使用 1920×1080 RAW10 输入、中心垂直裁切 8 行得到 1920×1072，目标 28 FPS；编码码率 2.4 Mbit/s、GOP 14、QP 20–40。无需 PPA 缩放即可直接使用对齐的编码输入。传感器标称约 1200 万像素不代表当前传输模式也有 1200 万像素。

ISP 使用 BT.601 limited 范围，避免全范围与有限范围混用；AE 目标 100、中心权重，gamma 0.72，黑电平偏移 16。黑电平尚未做本机传感器标定。自动对焦限制在 400–720；手动覆盖只复用已有驱动位置接口。

当前链接的 IPA 库不支持之前尝试的 average 测光模式，因此已改用 `HIGHLIGHT_PRIOR`，其额外高光权重和偏移均为 0；不能仅凭参数设置调用返回成功判定算法生效。清晰度、逆光曝光、镜头眩光与色彩仍需分别验证，不能用全局压暗或提高编码分辨率替代验收。没有手机计算摄影同等效果的承诺。

## 实测记录与验收

以下是开发机历史观测，不是性能保证，也不是迁移后新测得的数据：

| 版本 / 项目 | 实际结果 |
| --- | --- |
| v14 USB 25 秒传输 | 645 个有效包，活动区间 25.81 FPS，2.174 Mbit/s，CRC 0，序号缺口 1，最长到达间隔 1.984 秒 |
| v14 GUI | 用户截图约 17 FPS，画面仍糊；处理 FPS 与显示 FPS 不同 |
| v15 原工程 | 构建、应用烧录校验及串口版本查询成功；不是新的画质验收 |
| v15 焦点扫描 | 未检测到人脸，拒绝背景校准；未得到可接受的焦点结论 |
| v18 并发余量补丁构建 | ESP-IDF v6.0.2 增量构建、分区检查及离线 C 传输测试通过，应用 1,031,360 字节；持续视频与音频完整性待实测 |

迁移验证（2026-10-24）：新目录安装依赖及模型成功，18 项 Python 测试全部通过，Tk GUI 初始化通过，主机 C 传输测试通过；缩短 Windows 构建目录后，ESP-IDF v6.0.2 全量构建通过，应用为 941,616 字节。没有在此次迁移中再次烧录，也没有新的实机画质验收。凭据扫描的启发式命中已核对为 Tk 输入控件和变量赋值，不含实际密码；现场凭据、日志、图片和备份未纳入提交。

后续实机验收需固定光照、距离和静态文字 / 人脸目标，分别保存本地原始解码帧，检查焦点与高光细节；再记录至少 60 秒有效帧率、CRC、缺口和最大停顿。端到端延迟应使用可见计时器或受控光信号拍摄测量。图像诊断和日志保留在被忽略的本机 runtime 中，不上传现场人脸照片。

## 技术来源与后续接入

当前选择 YuNet + ByteTrack：前者提供本机 CPU 检测，后者用检测框、置信度及运动关联维护临时 ID。相比单纯 Haar 检测，它提供更适合当前人脸框的神经网络检测入口；相比逐脸独立光流 / 模板追踪，它支持多目标关联与短暂丢失后的恢复。没有引入人脸特征身份库；后续若换检测器，应保留检测框坐标、置信度与追踪接口，并重测遮挡、快速运动和误检。当前输出 ID 不具备跨会话身份含义。

- [上游 IMX708 驱动及示例](https://github.com/mushBrainDave/esp32-p4-imx-camera)，构建固定提交，见固件 README。
- [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) 与[官方相机软件说明](https://www.raspberrypi.com/documentation/computers/camera_software.html)：传感器模式与相机处理背景资料。
- [ESP32-P4 ISP 接口](https://docs.espressif.com/projects/esp-idf/en/latest/esp32p4/api-reference/peripherals/isp.html)：ISP 配置参考。
- [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) / [ByteTrack](https://github.com/FoundationVision/ByteTrack)：当前检测与关联算法来源。

后续接入机器人时，应先将人脸中心偏差转成独立的观测消息，在共享协议中定义时间戳、坐标系、目标有效期和丢失行为，经 STM32 本地保护后执行运动。目前没有实现这条控制链，不能把图像旋转按钮当成云台控制。
