"use strict";
/** Small transport boundary. Neither reconnect nor render sends motion commands. */
window.DashboardAPI = Object.freeze({
  async request(path, options = {}) {
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "请求失败");
    return data;
  },
  post(path, payload) {
    return this.request(path, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)});
  },
});
