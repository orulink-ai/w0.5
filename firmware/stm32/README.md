# STM32 运动控制固件

职责：电机控制、反馈采集、运动状态机、本地超时与故障保护。

已选 STM32G431C，控制两个无刷电机，编码器选用 AS5600，板间采用 UART。完整芯片料号、驱动器与反馈接线确认后创建 CubeMX `.ioc` 和实际工程。生成代码与手写业务逻辑分离；无刷电机控制算法和参数根据硬件选型确定。

## 开发入口

- [app](app/README.md)：正式产品入口。
- [examples](examples/README.md)：独立上板验证功能。
- [tests](tests/README.md)：自动化单元测试。

新增功能前阅读 [测试说明](../../docs/testing.md)。
