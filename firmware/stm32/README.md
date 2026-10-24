# STM32 运动控制固件

职责：电机控制、反馈采集、运动状态机、本地超时与故障保护。

已选 STM32G431CBT6，计划控制两个 GB2806 无刷电机（用户参数图：12V、7 极对、相电阻 5Ω、额定 0.81A、KV=121rpm/V），配合 AS5600 PWM 编码器；板间采用 UART。当前推进单轴，最新驱动资料为 DengFOCmini MP6536 原理图，早期 DRV8313 参数图不用于当前接线。PA8/PA9/PA10 为 TIM1 三通道 PWM，EN 已接 PB5；NFLT 拟用 PB4，尚未接入。用户选择保留板载 R78=100Ω 直接驱动，已说明 GPIO 负载风险，未测实际电流。AS5600 的 PA0/TIM2 读角已实测跑通，PB5 开/关和5秒截止也已上板验证。当前 `g431_motor_gpio` 支持网页显式低速点动，启动默认关闭；实际电机是否转动仍需操作者观察验收，见 [点动步骤](examples/encoder_read/MOTOR_GPIO.md)。

已确定采用 STM32duino + PlatformIO + SimpleFOC，配合编辑器和命令行编译、ST-Link 下载；无需独立 CubeIDE 或 Arduino IDE。CubeMX 可用于外设资源规划，但不能将它生成的纯 HAL 工程直接作为本 Arduino 示例的构建入口。当前已验证 ST-Link 可以连接芯片，并实现 AS5600 PWM 示例及主机测试；目标编译和实测状态见 [示例说明](examples/encoder_read/README.md)。环境与单轴推进步骤见 [硬件验证记录](../../docs/bringup.md)。

## 开发入口

- [app](app/README.md)：正式产品入口。
- [examples](examples/README.md)：独立上板验证功能。
- [tests](tests/README.md)：自动化单元测试。

新增功能前阅读 [测试说明](../../docs/testing.md)。
