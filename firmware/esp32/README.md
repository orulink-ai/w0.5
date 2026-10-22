# ESP32 主控固件

职责：Wi-Fi 连接、上层命令校验与调度、板间通信、设备状态汇总。

已选 ESP32-C6 Mini，完整板型及框架待确认后接入实际工程。板间使用 UART。网络与板间传输通过适配层连接业务逻辑；不在 ESP32 执行依赖确定时序的电机闭环。

## 开发入口

- [app](app/README.md)：正式产品入口。
- [examples](examples/README.md)：独立上板验证功能。
- [tests](tests/README.md)：自动化单元测试。

新增功能前阅读 [测试说明](../../docs/testing.md)。
