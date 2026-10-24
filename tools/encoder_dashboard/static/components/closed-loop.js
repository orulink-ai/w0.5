"use strict";
/** Closed-loop controls own their DOM and local request lifecycle. */
(function (scope) {
  const STATES = Object.freeze({UNCALIBRATED: "未校准", CALIBRATING: "校准中", READY: "已校准 · 已停止",
    RUNNING: "闭环运行中", FAULT: "故障"});
  const MODES = Object.freeze({POSITION: "位置保持", VELOCITY: "恒速旋转"});

  function viewModel(state, busy = false) {
    const control = state?.closed_loop;
    const available = Boolean(state?.connected && control?.available);
    const supportedVersion = control?.protocol_version === 3;
    const sensorValid = state?.signal === "valid" && control?.sensor_valid === true;
    const pending = busy || control?.settling || control?.command?.status === "pending";
    const ready = supportedVersion && available && control.state === "READY" && control.calibrated === true && control.enabled === false && sensorValid && !pending;
    return {
      visible: Boolean(control?.supported),
      label: !available ? "等待闭环固件" : !supportedVersion ? "旧版协议 · 仅诊断" :
        control.state === "RUNNING" && !(control.calibrated && control.sensor_valid && control.enabled) ? "运行反馈异常" :
        control.state === "READY" && !control.calibrated ? "未确认校准" : (STATES[control.state] || "状态未知"),
      ready,
      enableLabel: !available ? "未知" : control.enabled === true ? "已开启" : control.enabled === false ? "已关闭" : "未知",
      hasRelative: available && control.calibrated === true && control.sensor_valid === true,
      calibrate: supportedVersion && available && sensorValid && control.enabled === false && !pending && control.state === "UNCALIBRATED",
      stop: Boolean(state?.connected && control?.supported),
      busy: pending,
    };
  }

  class ClosedLoopPanel {
    constructor(element, {send, onState, heartbeat = runId => DashboardAPI.post("/api/foc/heartbeat", {run_id: runId})}) {
      this.element = element;
      this.send = send;
      this.onState = onState;
      this.busy = false;
      this.error = "";
      this.state = null;
      this.requestSequence = 0;
      this.lease = new FOCLeaseKeeper({heartbeat, onError: message => {
        this.error = message;
        this.render(this.state);
      }});
      if (typeof window !== "undefined") window.addEventListener("pagehide", () => this.lease.clear());
      element.innerHTML = `
        <div class="target-heading"><div><div class="section-label">闭环运动工作台</div>
          <p>AS5600 参与换相反馈 · 电压模式 · 页面连接有效时持续保持</p></div>
          <span class="motor-badge" data-field="badge">等待闭环固件</span></div>
        <div class="cl-readouts" aria-live="polite">
          <div><span>相对位置</span><strong data-field="position">—</strong></div>
          <div><span>当前模式</span><strong data-field="mode">—</strong></div>
          <div><span>反馈速度</span><strong data-field="velocity">—</strong></div>
          <div><span>驱动 EN</span><strong data-field="enable">未知</strong></div>
        </div>
        <div class="enable-actions">
          <button class="enable-on" data-action="calibrate" disabled>校准 FOC · 转轴会运动</button>
          <button class="secondary" data-action="zero" disabled>当前位置设为零点</button>
        </div>
        <p class="target-note">校准会让转轴轻微转动。校准完成后再设零、选择模式并手动开始。当前裸轴不执行机械寻限位。</p>
        <form data-form="limits" class="cl-limits">
          <label>左软限位（°）<input name="min_deg" type="number" value="-90" required step="1"></label>
          <label>右软限位（°）<input name="max_deg" type="number" value="90" required step="1"></label>
          <button class="secondary" data-action="limits" disabled>设置范围</button>
        </form>
        <p data-field="limits" class="target-status">固件确认的范围：等待数据</p>
        <div class="cl-tabs" role="group" aria-label="选择闭环模式">
          <button type="button" data-mode="position" aria-pressed="true">位置保持</button>
          <button type="button" data-mode="velocity" aria-pressed="false">恒速旋转</button>
        </div>
        <form data-form="motion">
          <div data-pane="position">
            <label>相对目标角度（°）<input name="target_deg" type="number" value="0" required step="1"></label>
            <div class="cl-presets">${[-45, 0, 45, 90].map(angle => `<button type="button" data-preset="${angle}">${angle}°</button>`).join("")}</div>
            <label>移动速度（rpm）<input name="speed_rpm" type="number" value="3" min="0.1" max="5" step="0.1"></label>
            <p class="target-note">预设只填写角度。启动后按设定速度移动到目标，并持续保持位置。本版用于定位与保持，手动转轴前请先停止。</p>
          </div>
          <div data-pane="velocity" hidden><label>目标速度（rpm）<input name="rpm" type="number" value="3" step="0.1"></label>
            <p class="target-note">正负数决定方向，达到软限位后停止。</p></div>
          <div class="enable-actions"><button class="enable-on" data-action="start" disabled>启动并保持</button>
            <button type="button" class="enable-off" data-action="stop" disabled>立即停止 / 关闭 EN</button></div>
        </form>
        <p data-field="status" class="target-status" role="status" aria-live="polite">等待设备报告闭环状态。</p>
        <p data-field="error" class="error" role="alert" hidden></p>
        <p class="target-note">命令确认仅代表芯片接收；实际运行、校准完成和故障以实时状态为准。页面关闭或通信中断后，芯片将在 1.5 秒内关闭使能；停止、复位或重连后不自动重启。参数修改需先停止，再手动启动。</p>`;
      this.mode = "position";
      for (const button of element.querySelectorAll("[data-mode]")) button.addEventListener("click", () => this.selectMode(button.dataset.mode));
      for (const button of element.querySelectorAll("[data-preset]")) button.addEventListener("click", () => {
        this.input("target_deg").value = button.dataset.preset;
      });
      element.querySelector('[data-form="limits"]').addEventListener("submit", event => {
        event.preventDefault(); this.submit("limits");
      });
      element.querySelector('[data-form="motion"]').addEventListener("submit", event => {
        event.preventDefault(); this.submit(this.mode);
      });
      for (const action of ["calibrate", "zero", "stop"]) {
        element.querySelector(`[data-action="${action}"]`).addEventListener("click", () => this.submit(action));
      }
      this.selectMode("position");
    }

    input(name) { return this.element.querySelector(`[name="${name}"]`); }
    field(name) { return this.element.querySelector(`[data-field="${name}"]`); }
    selectMode(mode) {
      this.mode = mode;
      for (const button of this.element.querySelectorAll("[data-mode]")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
      for (const pane of this.element.querySelectorAll("[data-pane]")) {
        pane.hidden = pane.dataset.pane !== mode;
        for (const input of pane.querySelectorAll("input")) input.disabled = pane.hidden;
      }
    }

    payload(action) {
      // The HTTP boundary validates numbers independently of browser controls.
      const number = name => {
        const value = this.input(name).value;
        if (!value.trim() || !Number.isFinite(Number(value))) throw new Error("请输入有效数值。");
        return Number(value);
      };
      const data = {action};
      if (action === "limits") Object.assign(data, {min_deg: number("min_deg"), max_deg: number("max_deg")});
      if (action === "position") Object.assign(data, {target_deg: number("target_deg"), speed_rpm: number("speed_rpm")});
      if (action === "velocity") data.rpm = number("rpm");
      return data;
    }

    async submit(action) {
      if (this.busy && action !== "stop") return;
      if (action === "stop") this.lease.clear();
      const sequence = ++this.requestSequence;
      const leaseGeneration = this.lease.token();
      let payload;
      try { payload = this.payload(action); }
      catch (error) { this.error = error.message; this.render(this.state); return; }
      this.busy = true;
      this.error = "";
      this.render(this.state);
      try {
        const state = await this.send(payload);
        if (sequence !== this.requestSequence) return;
        this.onState(state);
        // Arm only our own explicit, matching accepted request. STOP, disconnect,
        // terminal state or pagehide invalidates its pre-request generation.
        this.lease.accept(action, state, leaseGeneration);
      } catch (error) {
        if (sequence !== this.requestSequence) return;
        this.lease.clear();
        this.error = error.message;
      } finally {
        if (sequence === this.requestSequence) { this.busy = false; this.render(this.state); }
      }
    }

    render(state) {
      this.state = state;
      this.lease.observe(state);
      const model = viewModel(state, this.busy);
      const control = state?.closed_loop;
      this.element.hidden = !model.visible;
      this.field("badge").textContent = model.label;
      this.field("enable").textContent = model.enableLabel;
      this.field("badge").className = `motor-badge ${control?.state === "RUNNING" && control.available && control.calibrated && control.sensor_valid && control.enabled ? "enabled" : ""}`;
      for (const action of ["zero", "limits", "start"]) this.element.querySelector(`[data-action="${action}"]`).disabled = !model.ready;
      this.element.querySelector('[data-action="calibrate"]').disabled = !model.calibrate;
      this.element.querySelector('[data-action="stop"]').disabled = !model.stop;
      const format = (value, suffix) => Number.isFinite(value) && control?.available ? `${value.toFixed(1)}${suffix}` : "—";
      this.field("position").textContent = model.hasRelative ? format(control?.relative_deg, "°") : "—";
      this.field("mode").textContent = control?.available ? (MODES[control.mode] || "停止") : "—";
      this.field("velocity").textContent = model.hasRelative ? format(control?.velocity_rpm, " rpm") : "—";
      this.field("limits").textContent = `固件确认的范围：${format(control?.soft_min_deg, "°")} ～ ${format(control?.soft_max_deg, "°")}`;
      let status = "等待设备报告闭环状态。";
      if (!state?.connected) status = "串口未连接，不能确认电机状态。";
      else if (model.busy) status = "命令已发送，等待芯片确认；尚不能据此判断动作完成。";
      else if (!control?.available) status = "闭环状态已超时，禁止启动；可尝试立即停止。";
      else if (control.protocol_version !== 3) status = "当前是旧版闭环固件，仅显示诊断；请升级 v3 后使用持续控制。";
      else if (control.state === "UNCALIBRATED") status = "请先校准 FOC，完成后设零并选择模式。";
      else if (control.state === "CALIBRATING") status = "正在校准传感器方向和电角度零位，请勿转动或阻挡转轴。";
      else if (control.state === "FAULT") status = `固件报告故障：${control.fault || "未知"}；驱动应关闭，请检查实时状态。`;
      else if (control.state === "RUNNING" && control.calibrated && control.sensor_valid && control.enabled) status = this.lease.runId === control.run_id ? "闭环运行中，页面正在维护运动连接。修改参数需停止后重新启动。" : "设备正在运行；本页面未持有该次运动，不会自动接管。";
      else if (state.signal !== "valid") status = "编码器数据无效或超时，暂不能开始。";
      else if (model.ready) status = control.stop_reason === "COMM_TIMEOUT" ? "通信租约已超时，芯片已停止。请手动重新启动。" : control.stop_reason === "LIMIT" ? "已到达软限位并停止。请手动选择新目标启动。" : "已校准并停止。选择模式和参数，再点击启动并保持。";
      else status = "设备反馈尚未满足闭环就绪条件，请检查编码器、校准与使能状态。";
      this.field("status").textContent = status;
      const error = this.error || control?.command?.error || "";
      this.field("error").textContent = error;
      this.field("error").hidden = !error;
    }
  }
  scope.ClosedLoopUI = Object.freeze({ClosedLoopPanel, viewModel});
  if (typeof module !== "undefined") module.exports = scope.ClosedLoopUI;
})(globalThis);
