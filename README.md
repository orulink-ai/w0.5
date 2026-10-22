# W0.5 桌面机器人

采用 monorepo 管理 ESP32 主控固件、STM32 运动控制固件、共享通信协议和集成测试。

当前阶段为架构骨架，尚未包含可烧录固件。已确认 ESP32-C6 Mini、STM32G431C、UART、两个无刷电机与 AS5600 编码器；完整料号、驱动及接线方案待确认。

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

测试功能放置与新增方法见 [测试说明](docs/testing.md)。当前示例均为待实现的文档骨架。

详见 [架构说明](docs/architecture.md) 与 [硬件验证清单](docs/bringup.md)。
