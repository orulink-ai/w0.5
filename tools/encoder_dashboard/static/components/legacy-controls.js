"use strict";
/** Legacy firmware controls are isolated from the closed-loop workstation. */
class LegacyControls {
  constructor(onState) {
    const $ = id => document.getElementById(id);
    let busy = false;
    let commandBusy = false, controlError = "", lastState = null;
    let enableBusy = false, enableError = "", motorBusy = false, motorError = "";
    const render = state => onState(state);
    function setButtons() {
  const control = lastState?.control;
  const ready = control?.available && lastState?.signal === "valid";
  for (const button of document.querySelectorAll(".angle-preset")) {
    button.disabled = busy || commandBusy || !ready || control.command.status === "pending";
  }
  const enable = lastState?.enable;
  $("enable-on").disabled = busy || enableBusy || !enable?.ready ||
    lastState?.signal !== "valid" || enable?.enabled !== false || enable?.command?.status === "pending" ||
    lastState?.motor?.state === "RUNNING" || motorBusy;
  $("enable-off").disabled = busy || enableBusy || !enable?.off_available;
  const motor = lastState?.motor;
  $("motor-jog").disabled = busy || motorBusy || enableBusy || !motor?.ready ||
    lastState?.signal !== "valid" || !enable?.ready || enable?.enabled !== false ||
    motor?.command?.status === "pending";
  $("motor-stop").disabled = busy || !motor?.stop_available;
    }
function renderMotor(state) {
  const motor = state.motor;
  const labels = {READY:"准备就绪",RUNNING:"正在点动",DONE:"本次已停止",FAULT:"故障已锁定"};
  $("motion-badge").textContent = motor?.available ? labels[motor.state] : "状态未知";
  $("motion-badge").className = `motor-badge ${motor?.state === "RUNNING" ? "enabled" : ""}`;
  let message = "等待电机点动固件状态。";
  if (!state.connected) message = "串口未连接，无法确认运动状态。";
  else if (motorBusy || motor?.command?.status === "pending") message = "请求已发送，等待 STM32 确认…";
  else if (motor?.state === "FAULT") message = "点动故障已锁定；请关闭 12V 后检查接线和编码器。";
  else if (motor?.state === "RUNNING") message = "已收到开始确认，约三秒后自动停止；可点击“立即停止”提前结束。";
  else if (motor?.ready && state.signal !== "valid") message = "编码器数据无效或超时，暂不能开始。";
  else if (motor?.ready && state.enable?.enabled !== false) message = "请先关闭使能并等待低电平确认；点动按钮会自动开启使能。";
  else if (motor?.ready) message = motor.state === "DONE" ? "本次测试已停止；可再次点击按钮，开始新的三秒点动。" :
    "准备就绪。点击“低速转动”开始，观察转轴和上方编码器读数。";
  else if (motor?.stop_available) message = "运动状态已超时；可尝试停止，不能据旧状态判断电机是否已停。";
  $("motion-status").textContent = message;
  const error = motorError || motor?.command?.error || "";
  $("motion-error").textContent = error;
  $("motion-error").hidden = !error;
}

async function commandMotor(action) {
  if (motorBusy && action === "jog") return;
  motorBusy = true;
  motorError = "";
  setButtons();
  renderMotor(lastState);
  try {
    render(await DashboardAPI.request("/api/motor", {method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action})}));
  } catch (error) { motorError = error.message; }
  finally {
    motorBusy = false;
    setButtons();
    if (lastState) renderMotor(lastState);
  }
}

function renderEnable(state) {
  const enable = state.enable;
  const level = enable?.enabled;
  const badge = $("enable-badge");
  badge.textContent = level === true ? "PB5 高电平" : level === false ? "PB5 低电平" : "状态未知";
  badge.className = `motor-badge ${level === true ? "enabled" : level === false ? "disabled" : ""}`;
  let message = "等待 PB5 使能固件状态。";
  if (!state.connected) message = "串口未连接，无法确认引脚电平。";
  else if (enableBusy || enable?.command?.status === "pending") message = "正在发送请求，等待 STM32 引脚读回确认…";
  else if (enable?.state === "FAULT") message = level === true ?
    "程序报告故障且 PB5 仍读为高；请关闭 12V 并检查接线。" :
    "程序报告故障，暂不能开启；仍可发送关闭请求。";
  else if (level === true) message = "STM32 已确认 PB5 为高电平，本次开启最多持续 5 秒。";
  else if (level === false) message = "STM32 已确认 PB5 为低电平，驱动使能已关闭。";
  else if (enable?.off_available) message = "引脚状态已超时；可尝试关闭，不能据旧数据判断电平。";
  $("enable-status").textContent = message;
  const error = enableError || enable?.command?.error || "";
  $("enable-error").textContent = error;
  $("enable-error").hidden = !error;
}

async function setEnable(enabled) {
  if (enableBusy) return;
  enableBusy = true;
  enableError = "";
  setButtons();
  renderEnable(lastState);
  try {
    render(await DashboardAPI.request("/api/enable", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({enabled})}));
  } catch (error) { enableError = error.message; }
  finally {
    enableBusy = false;
    setButtons();
    if (lastState) renderEnable(lastState);
  }
}

function renderControl(state) {
  const control = state.control;
  const jog = state.jog;
  const pinControl = state.enable?.off_available;
  const motionControl = state.motor?.stop_available;
  $("motor-badge").textContent = motionControl ? "低速开环测试" : pinControl ? "使能开关测试" : jog ? (jog.state === "RUNNING" ? "开环点动中" : "EN 手动常高") :
    (control?.available ? "电机未使能" : "状态待确认");
  $("target-note").textContent = motionControl ? "当前支持手动低速点动；四个角度按钮待接入闭环定位后使用。" : pinControl ? "当前仅测试 PB5 使能；四个角度按钮待接入定位固件后使用。" : jog ?
    "当前为三秒开环点动测试，四个定位按钮不可用。停止为三相归零，驱动仍有电。" :
    "目标暂存固件仅接收并确认角度；尚未接入定位控制。";
  $("motor-footer").textContent = motionControl ? "手动低速点动 · 每次约三秒 · 停止后 EN 关闭" : pinControl ? "EN 由 PB5 控制 · 当前仅测试使能开关" : jog ? "手动 EN 常高 · 三相归零不等于切断 12V" :
    (control?.available ? "目标命令需芯片确认 · 当前固件不驱动电机" : "未收到新鲜的控制状态");
  const target = control?.available ? control.target_deg : null;
  $("target-value").textContent = target === null || target === undefined ? "—" : `${target}°`;
  for (const button of document.querySelectorAll(".angle-preset")) {
    button.setAttribute("aria-pressed", String(target === Number(button.dataset.angle)));
  }
  const command = control?.command;
  let message = "等待目标命令固件状态；串口 TXD 接 PA3。";
  if (!state.connected) message = "连接串口后可选择目标角度。";
  else if (motionControl) message = "请使用上方“手动低速转动”；角度定位功能尚未启用。";
  else if (pinControl) message = "使能开关已单独接入，角度定位功能尚未启用。";
  else if (jog) message = ({READY: "点动程序就绪，等待单次测试命令。",
    RUNNING: "低速开环点动中，约三秒后结束。", DONE: "本次点动已结束，三相已归零。",
    FAULT: "点动程序报告故障，三相归零；请先关闭 12V。"})[jog.state];
  else if (control?.available) {
    if (state.signal !== "valid") message = "编码器数据无效或已超时，暂停下发目标。";
    else if (commandBusy || command?.status === "pending") message = "正在下发目标，等待芯片确认…";
    else if (command?.status === "accepted") message = `芯片已接收 ${command.angle_deg}°；电机未使能。`;
    else message = "选择预设发送目标；电机保持未使能。";
  }
  $("target-status").textContent = message;
  const error = controlError || command?.error || "";
  $("target-error").textContent = error;
  $("target-error").hidden = !error;
}

async function sendTarget(angle) {
  if (commandBusy) return;
  commandBusy = true;
  controlError = "";
  setButtons();
  renderControl(lastState);
  try {
    render(await DashboardAPI.request("/api/target", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({angle_deg: angle}),
    }));
  } catch (error) { controlError = error.message; }
  finally {
    commandBusy = false;
    setButtons();
    if (lastState) renderControl(lastState);
  }
}


    $("enable-on").addEventListener("click", () => setEnable(true));
    $("enable-off").addEventListener("click", () => setEnable(false));
    $("motor-jog").addEventListener("click", () => commandMotor("jog"));
    $("motor-stop").addEventListener("click", () => commandMotor("stop"));
    for (const button of document.querySelectorAll(".angle-preset")) {
      button.addEventListener("click", () => sendTarget(Number(button.dataset.angle)));
    }
    this.render = (state, connectionBusy = false) => {
      lastState = state;
      busy = connectionBusy || Boolean(state.closed_loop?.supported);
      for (const section of document.querySelectorAll("[data-legacy-control]")) section.hidden = Boolean(state.closed_loop?.supported);
      renderEnable(state); renderMotor(state); renderControl(state); setButtons();
    };
    this.resetErrors = () => { controlError = enableError = motorError = ""; };
  }
}
