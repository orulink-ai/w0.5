# STM32 单轴位置与速度控制

本阶段只交付基础位置伺服、速度闭环和网页持续控制。运行环境为 STM32G431CBT6、STM32duino 2.12.0、SimpleFOC 2.4.0、PlatformIO，固件入口为 `g431_closed_loop`。已确认硬件：12V GB2806（7极对）、DengFOCmini MP6536、AS5600 PWM。当前是单轴调试版本，ESP32与双轴联调另行推进。

## 组件边界

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 编码器 | `firmware/stm32/lib/as5600_pwm/` 与 `src/pwm_input.*` | PA0/TIM2成对捕获，8MHz原始计数解码 |
| 运动策略 | `firmware/stm32/lib/closed_loop/closed_loop.h` | 多圈角度、双速估速、用户零点、限位、模式与反馈故障 |
| 位置轨迹 | `firmware/stm32/lib/closed_loop/position_control.h` | 从当前位置按设定速度推进到固定目标，抵达后保持目标 |
| 运行租约 | `firmware/stm32/lib/closed_loop/run_lease.h` | 当前run_id、1500ms期限、续期和不可复活规则 |
| 协议 | `firmware/stm32/lib/closed_loop/closed_protocol.h` | 有界CSV解析、严格字段与有限数值校验 |
| 硬件适配 | `firmware/stm32/examples/encoder_read/src/closed_loop_hardware.*` | SimpleFOC Sensor/驱动、电机、PB5独占控制、看门狗 |
| 参数 | `firmware/stm32/lib/closed_loop/closed_loop_tuning.h` | 速度PI和滤波，避免散落在网页与应用中 |
| 应用 | `firmware/stm32/examples/encoder_read/src/closed_loop_app.*` | 校准、状态机、策略与硬件调用、ACK及遥测 |
| 主机 | `tools/encoder_dashboard/closed_loop_commands.py` | 参数校验、请求关联、租约所有权与新鲜度 |
| 页面 | `static/components/closed-loop.js`、`lease-keeper.js` | 两模式表单、真实状态、显式启动、独立心跳生命周期 |
| 实时目标 | `static/components/live-position.js` | 本页持有运行权时合并发送拖动目标，单请求在途、200ms限频 |

表中的 `src/` 位于编码器示例目录，`static/` 位于 `tools/encoder_dashboard/`。入口 `closed_loop_main.cpp` 只组合应用并转发setup/loop。FOC控制在MCU执行，不依赖浏览器的实时调度精度。

## 两种控制

- 位置：用户目标和移动速度 → 独立限速位置参考 → SimpleFOC角度／速度级联闭环 → 电压输出。轨迹运动段提供规划速度前馈，抵达目标后前馈清零，目标持续保留。
- 速度：用户有符号rpm → SimpleFOC速度PI → 电压输出。接近软件边界时停止。

AS5600原始角度为0～360°；新帧才更新连续多圈角度，跨零不改变机械目标。校准确认传感器方向和电角度零位，用户位置采用 `方向×多圈角度−原点`。设零只改用户原点，不修改换相零位。目标和限位使用相对角度；SimpleFOC位置目标转成同一方向修正后的绝对轴坐标。

控制使用4ms窗口的快速估速及2ms库滤波；遥测与超速保护使用独立20ms窗口的慢速估值。速度PI目前P=0.08、I=1.0、D=0。输出电压幅度上限1V，母线12V。没有相电流采样，不是电流环，也不提供精确力矩控制。

本版没有手拨阻力、柔顺回中或机械寻限位。位置伺服会尝试纠正外力造成的偏差，操作时应使用停止按钮释放输出，再手动移动转轴。未来触觉交互应作为独立策略开发和验收。

## 持续控制与停止

启动一次后没有固定5秒运行截止。页面每300ms发送绑定本次run_id的心跳，芯片租约为1500ms；页面关闭、串口断开、服务退出或心跳过期后，芯片关闭EN，清除run_id，并报告COMM_TIMEOUT。普通超时停机保留成功校准，用户可显式重新启动；不会自动恢复旧目标。

只有本页面显式启动／校准且收到匹配ACK才拥有心跳资格。页面刷新、状态恢复和发现别处启动的RUNNING状态都不认领控制权。迟到ACK、迟到HTTP响应、旧心跳、停止后重连不能恢复运行。MCU先判断过期，再处理同一时刻到达的心跳；已过期租约不能被续活。

启动默认UNCALIBRATED、EN低；校准同样受租约约束。校准完成关闭EN、进入READY。STOP先关闭硬件再清状态，可打断校准并抢占等待确认的请求。故障锁定，不自动恢复。

保护还包括编码器有效性、软件范围（默认±90°）、实际反馈超速2rad/s、GPIO读回和约100ms看门狗。PB4为nFAULT输入，仅在实物确实连接故障线时反映驱动告警。软件边界不是机械挡块，不保证惯性绝不越界；连续控制也不等于具备电流／温度闭环保护。

手动快速转轴也可能触发 `OVERSPEED`。页面新增“清除超速故障 · 保持停止”：松手停稳后显式发送 RESET，仅解除超速锁定，保留校准、零点与范围，EN保持关闭、不领取运动租约、不恢复旧动作，用户另点启动。固件要求反馈有效、估计速度绝对值不超过0.2rad/s（约1.9rpm）、EN关闭且无硬件故障；不满足时返回 `RESET_NOT_READY`。其他类型故障不通过此入口清除。此功能需更新包含RESET的固件和后端后使用；未上板验证前不视作实机验收。

另提供“关闭超速保护 / 开启超速保护”。阈值2rad/s约等于114.6°/秒、19.1rpm，与目标速度上限5rpm不同。开关仅在停机、EN低、反馈有效且无其他锁定故障时接受；可以在超速锁定时切换，但不会代替RESET清故障。关闭只跳过超速判定，编码器失效、软限位、硬件故障和通信租约逻辑继续执行；不代表释放位置保持。设置仅保存在本次上电的RAM，芯片重启后默认开启，网页刷新或服务重启不会自动写回。页面只显示固件新鲜状态中的确认值，ACK本身不会改变开关显示，旧固件未报告该字段时禁止切换。

## v4实时拖动与兼容接口

位置模式先显式启动，再拖动目标滑块或修改角度，电机按本次设定的速度平滑跟随；松手后到达最后目标并保持。READY时拖动仅填写目标，不会自动启动。范围取芯片确认的软限位，默认±90°。3rpm相当于18°/秒，90°理想轨迹约5秒；实际响应有偏差。速度参数仍需停止后重新启动修改。

实时请求为 `{"action":"target","run_id":123,"target_deg":30}`，经现有 `POST /api/foc` 发送，串口为 `FOC,<新command_id>,TARGET,<现有run_id>,<角度>`，匹配确认是 `#FOC_ACK,<新command_id>,TARGET`。command_id每次递增，run_id保持原START编号。仅v4、当前本页拥有的RUNNING POSITION、反馈有效、EN高、租约未过期时接受。v3保留基础控制，但不允许TARGET。

TARGET保留规划参考的连续位置、既有速度与PI状态，只改目的地，不启动、不使能、不切模式、不续租。网页最多约5次/秒、单请求在途，期间只保留最新角度，松手最终值仍会送达。停止、断线、切换模式、页面离开或失去运行权会清空队列，迟到请求／响应不能重启电机。运行心跳仍独立维持1500ms租约。

HTTP：

```json
{"action":"position","target_deg":10,"speed_rpm":1}
{"action":"velocity","rpm":-1}
{"action":"calibrate"}
{"action":"zero"}
{"action":"limits","min_deg":-90,"max_deg":90}
{"action":"stop"}
{"action":"reset"}
{"action":"overspeed","enabled":false}
```

均提交到 `POST /api/foc`。心跳独立提交到 `POST /api/foc/heartbeat`，内容为 `{"run_id":123}`。角度需在固件确认的范围内，速度幅值0.1～5rpm，位置速度必须为正。除v4实时位置目标外，参数修改需停止后重新显式启动。旧stiffness、往复和弹簧动作不接受。

串口：

```text
FOC,<id>,CALIBRATE|ZERO|STOP|RESET
FOC,<id>,OVERSPEED,<0|1>
FOC,<id>,LIMITS,<min_deg>,<max_deg>
FOC,<id>,START,POSITION,<target_deg>,<speed_rpm>
FOC,<id>,START,VELOCITY,<rpm>
FOC,<id>,TARGET,<active_run_id>,<target_deg>
FOC,<active_run_id>,KEEPALIVE
#FOC_ACK,<id>,<ACTION>
#FOC_NACK,<id>,<REASON>
#FOC_STATUS,4,<state>,<mode>,<highwater_id>,<calibrated>,<actual_EN>,<sensor_valid>,<relative_deg>,<requested_target_deg>,<velocity_rpm>,<zero_raw_deg>,<soft_min_deg>,<soft_max_deg>,<fault>,<active_run_id>,<lease_remaining_ms>,<stop_reason>,<overspeed_enabled_0_or_1>
```

v4状态格式与带超速开关字段的v3一致，版本号改为4，保留第19个overspeed_enabled字段。心跳不等待ACK、不改变命令编号高水位、不创建运行；错误run_id直接忽略。ACK只表示接收，运行和到位须看新鲜反馈。CALIBRATING/RUNNING拥有非零run_id，其余状态run_id为0。停止原因包括NONE、USER_STOP、COMM_TIMEOUT、LIMIT、FAULT。旧v1/v2只供诊断或STOP，网页向v3/v4固件发送启动和心跳，仅向v4发送TARGET。

解析兼容未附加`overspeed_enabled`的旧v3状态，开关值视为未知；OVERSPEED配置需要此扩展字段，RESET与OVERSPEED均不创建运行租约、不启动电机。

## 验证入口

```sh
python3 tools/stm32.py test
.venv/bin/python -m unittest discover -s tools/tests -v
node tools/tests/test_closed_loop_ui.js
node tools/tests/test_foc_lease_keeper.js
python3 tools/stm32.py build --env g431_closed_loop
python3 tools/stm32.py build --env g431_motor_gpio
```

主机测试使用纯策略与伪串口，不控制真实电机。实物版本、运行记录与本阶段边界见 [阶段交付记录](releases/stm32-basic-control.md)。
