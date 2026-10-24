"use strict";
/** Browser-local ownership, never acquired from discovered MCU state. */
(function (scope) {
  class LeaseKeeper {
    constructor({heartbeat, onError = () => {}, clock = globalThis, intervalMs = 300}) {
      this.heartbeat = heartbeat;
      this.onError = onError;
      this.clock = clock;
      this.intervalMs = intervalMs;
      this.runId = null;
      this.generation = 0;
      this.timer = null;
      this.terminalHighwater = 0;
      this.latestHighwater = 0;
      this.latestRunId = 0;
    }

    token() { return this.generation; }

    accept(action, state, generation) {
      if (generation !== this.generation) return false;
      const control = state?.closed_loop;
      const command = control?.command;
      if (!["calibrate", "position", "velocity"].includes(action) ||
          ![3, 4].includes(control?.protocol_version) || command?.status !== "accepted" || command.action !== action ||
          !Number.isInteger(command.id) || command.id <= 0 || command.id > 2147483647 ||
          control.owned_run_id !== command.id || !state.connected ||
          this.terminalHighwater >= command.id || this.latestHighwater > command.id ||
          (this.latestHighwater === command.id && this.latestRunId !== command.id)) return false;
      this.clear();
      this.runId = command.id;
      this.observe(state);
      if (this.runId === null) return false;
      this.pulse(this.generation);
      return true;
    }

    observe(state) {
      const control = state?.closed_loop;
      if (!state?.connected) {
        this.clear();
        this.terminalHighwater = this.latestHighwater = this.latestRunId = 0;
        return;
      }
      if (!control?.available || ![3, 4].includes(control.protocol_version)) { this.clear(); return; }
      if (control.last_id === 0 && control.state === "UNCALIBRATED" &&
          control.enabled === false && control.calibrated === false && this.latestHighwater > 0) {
        this.clear();
        this.terminalHighwater = this.latestHighwater = this.latestRunId = 0;
        return;
      }
      if (control.last_id >= this.latestHighwater) {
        this.latestHighwater = control.last_id;
        this.latestRunId = control.run_id;
      }
      if (["UNCALIBRATED", "READY", "FAULT"].includes(control.state))
        this.terminalHighwater = Math.max(this.terminalHighwater, control.last_id);
      if (this.runId !== null && control.last_id >= this.runId &&
          (control.run_id !== this.runId || !["CALIBRATING", "RUNNING"].includes(control.state))) this.clear();
    }

    clear() {
      this.generation++;
      if (this.timer !== null) this.clock.clearTimeout(this.timer);
      this.timer = null;
      this.runId = null;
    }

    async pulse(generation) {
      const runId = this.runId;
      if (generation !== this.generation || runId === null) return;
      try {
        const reply = await this.heartbeat(runId);
        if (generation !== this.generation) return;
        if (reply?.ok !== true || reply.run_id !== runId) throw new Error("运动心跳未确认。");
        // Schedule only after resolution, so slow transport never overlaps.
        this.timer = this.clock.setTimeout(() => this.pulse(generation), this.intervalMs);
      } catch (error) {
        if (generation !== this.generation) return;
        this.clear();
        this.onError(error.message || "运动连接已中断，请手动重新启动。");
      }
    }
  }
  scope.FOCLeaseKeeper = LeaseKeeper;
  if (typeof module !== "undefined") module.exports = {LeaseKeeper};
})(globalThis);
