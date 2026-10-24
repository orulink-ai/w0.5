# STM32 实时拖动位置控制

日期：2026-10-24。构建环境：`g431_closed_loop`，协议v4。

## 本次改动

- 在位置模式新增角度滑块，范围取固件确认的软限位，默认±90°。
- 校准后显式启动位置控制，再拖动可实时更新目标；松手后到达最后目标并保持。停机时拖动只填写目标。
- 新增绑定已有run_id的TARGET命令，保留轨迹进度、速度和PI状态，不重新使能或续租；停止后的迟到命令不能重启。
- 网页队列组件最多约5Hz，单请求在途并合并最新值；断线、失去运行权、切换模式或页面离开后清空队列。
- 基础控制兼容v3/v4，实时拖动只向v4发送。保留并集成超速故障手动复位及保护开关；芯片重启默认开启超速保护。

## 验证

- `.venv/bin/python -m unittest discover -s tools/tests -v`：74项通过。
- `python3 tools/stm32.py test`：六套C++原生测试通过。
- `node tools/tests/test_closed_loop_ui.js`、`test_foc_lease_keeper.js`、`test_live_position.js`：三组通过。
- `g431_closed_loop`构建和ST-Link烧录校验通过；Flash68420字节，RAM4680字节。
- 固件SHA-256：`670711f4755346e07a2bc38ba3b3c734e75fd81aa5aed0a6d442dbce9e0aed2b`。
- 浏览器已显示滑块、识别v4和有效编码器，390px无横向溢出；烧录后为UNCALIBRATED、EN关闭、fault=NONE。

测试包括伪串口上的实时命令确认和STOP抢占，不操作真实电机。本次没有自动校准或执行真实拖动跟随验收。操作者刷新页面后需校准、点击“启动并保持”再拖动；沿用既有速度限制，默认3rpm=18°/秒，因此快速拖动时会逐渐追上。既有低速波动尚需后续调参，未新增电流环、触觉交互或机械寻限位。

实现与接口见 [闭环架构](../closed-loop-architecture.md)。
