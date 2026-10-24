"use strict";
const $ = (id) => document.getElementById(id);
let connected = false;
let busy = false;
let lastLogKey = "";
let actionError = "";
let lastState = null;

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

const request = (...args) => DashboardAPI.request(...args);
const legacy = new LegacyControls(state => render(state));
const closedLoop = new ClosedLoopUI.ClosedLoopPanel($("closed-loop-panel"), {
  send: payload => DashboardAPI.post("/api/foc", payload), onState: state => render(state),
});

function setButtons() {
  $("connect").disabled = busy || connected || !$("port").value;
  $("disconnect").disabled = busy || !connected;
  $("port").disabled = busy || connected;
  $("refresh").disabled = busy || connected;
  if (lastState) legacy.render(lastState, busy);
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
  legacy.render(state, busy);
  closedLoop.render(state);
  if (state.closed_loop?.supported) $("motor-footer").textContent = "编码器闭环 · 电压模式 · 手动开始 · 页面连接有效时持续保持";

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
  legacy.resetErrors();
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
