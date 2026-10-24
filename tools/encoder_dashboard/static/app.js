"use strict";
const $ = (id) => document.getElementById(id);
let connected = false;
let busy = false;
let lastLogKey = "";
let actionError = "";
let commandBusy = false;
let controlError = "";
let lastState = null;
let enableBusy = false;
let enableError = "";
let motorBusy = false;
let motorError = "";

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function setButtons() {
  $("connect").disabled = busy || connected || !$("port").value;
  $("disconnect").disabled = busy || !connected;
  $("port").disabled = busy || connected;
  $("refresh").disabled = busy || connected;
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
    render(await request("/api/motor", {method:"POST",headers:{"Content-Type":"application/json"},
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
    render(await request("/api/enable", {method:"POST", headers:{"Content-Type":"application/json"},
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
    render(await request("/api/target", {
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

async function refreshPorts() {
  try {
    const previous = $("port").value;
    const ports = await request("/api/ports");
    $("port").replaceChildren();
    if (!ports.length) {
      $("port").add(new Option("未检测到串口", ""));
    } else {
      for (const port of ports) {
        const option = new Option(port.device, port.device);
        option.title = port.description;
        $("port").add(option);
      }
      const preferred = ports.find(p => p.device === previous) ||
        ports.find(p => /wchusbserial|usbserial|usbmodem/i.test(p.device)) || ports[0];
      $("port").value = preferred.device;
    }
    setButtons();
  } catch (error) { actionError = error.message; showError(actionError); }
}

const signalText = {
  disconnected: "未连接", waiting: "等待数据", stale: "数据已超时",
  invalid: "PWM 无效", valid: "信号有效",
};
const captions = {
  disconnected: "连接串口后，等待编码器数据",
  waiting: "串口已连接，等待固件输出",
  stale: "超过 1 秒未收到新测量，旧角度已隐藏",
  invalid: "尚未捕获有效 PWM，请检查供电、接线与输出模式",
  valid: "缓慢转动轴，观察机械角度变化",
};

function render(state) {
  lastState = state;
  connected = state.connected;
  if (connected && [...$("port").options].some(option => option.value === state.port)) {
    $("port").value = state.port;
  }
  setButtons();
  $("connection-label").textContent = connected ? "串口已连接" : "未连接";
  $("connection-dot").parentElement.classList.toggle("connected", connected);
  $("active-port").textContent = state.port || "—";
  $("sample-age").textContent = state.age_ms === null ? "—" : `${state.age_ms} ms 前`;
  $("signal-badge").className = `badge ${state.signal}`;
  $("signal-label").textContent = signalText[state.signal];
  $("angle-caption").textContent = captions[state.signal];
  document.body.classList.toggle("live", state.signal === "valid");
  const reading = state.reading;
  const valid = state.signal === "valid" && reading;
  $("angle").textContent = valid ? reading.angle_deg.toFixed(2) : "—";
  $("frequency").textContent = valid ? reading.frequency_hz.toFixed(1) : "—";
  const rawFresh = ["valid", "invalid"].includes(state.signal) && reading;
  $("high").textContent = rawFresh ? reading.high_us.toLocaleString() : "—";
  $("period").textContent = rawFresh ? reading.period_us.toLocaleString() : "—";
  $("needle").hidden = !valid;
  if (valid) $("needle").style.transform = `rotate(${reading.angle_deg}deg)`;
  $("frame-count").textContent = state.samples.toLocaleString();
  $("valid-count").textContent = `有效 ${state.valid_samples} / ${state.samples}`;
  showError(state.error || actionError);
  renderEnable(state);
  renderMotor(state);
  renderControl(state);

  const logs = state.logs.slice(-8);
  const key = JSON.stringify(logs);
  if (key !== lastLogKey) {
    lastLogKey = key;
    $("logs").replaceChildren();
    if (!logs.length) {
      const empty = document.createElement("p");
      empty.className = "empty-log";
      empty.textContent = "连接后，这里将显示固件输出的原始数据。";
      $("logs").append(empty);
    }
    for (const log of logs) {
      const row = document.createElement("div");
      row.className = `log-row ${log.text.startsWith("OK,") ? "ok" : ""}`;
      const time = document.createElement("span");
      time.className = "log-time";
      time.textContent = new Date(log.time_ms).toLocaleTimeString("zh-CN", {hour12: false});
      const text = document.createElement("span");
      text.className = "log-text";
      text.textContent = log.text;
      row.append(time, text);
      $("logs").append(row);
    }
    $("logs").scrollTop = $("logs").scrollHeight;
  }
}

async function changeConnection(action) {
  busy = true;
  actionError = "";
  controlError = "";
  enableError = "";
  motorError = "";
  setButtons();
  showError("");
  try {
    render(await request(`/api/${action}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(action === "connect" ? {port: $("port").value} : {}),
    }));
  } catch (error) { actionError = error.message; showError(actionError); }
  finally { busy = false; setButtons(); }
}

$("refresh").addEventListener("click", refreshPorts);
$("port").addEventListener("change", setButtons);
$("connect").addEventListener("click", () => changeConnection("connect"));
$("disconnect").addEventListener("click", () => changeConnection("disconnect"));
$("enable-on").addEventListener("click", () => setEnable(true));
$("enable-off").addEventListener("click", () => setEnable(false));
$("motor-jog").addEventListener("click", () => commandMotor("jog"));
$("motor-stop").addEventListener("click", () => commandMotor("stop"));
for (const button of document.querySelectorAll(".angle-preset")) {
  button.addEventListener("click", () => sendTarget(Number(button.dataset.angle)));
}

async function start() {
  await refreshPorts();
  const events = new EventSource("/api/events");
  events.onmessage = event => {
    try { render(JSON.parse(event.data)); }
    catch { showError("收到无法解析的页面数据，请刷新页面。"); }
  };
  events.onerror = () => {
    connected = false;
    render({connected: false, port: "", signal: "disconnected", reading: null,
      error: "本地服务连接中断，正在重连。", age_ms: null,
      samples: 0, valid_samples: 0, logs: []});
  };
}
start();
