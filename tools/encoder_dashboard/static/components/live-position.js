"use strict";
/** Explicit user target edits; rendering and reconnection never create work. */
(function (scope) {
  function canSendTarget(state, runId, mode) {
    const control = state?.closed_loop;
    return Boolean(mode === "position" && state?.connected && state.signal === "valid" &&
      control?.available && control.protocol_version === 4 && control.state === "RUNNING" &&
      control.mode === "POSITION" && control.enabled === true && control.calibrated === true &&
      control.sensor_valid === true && Number.isInteger(runId) && runId > 0 &&
      control.run_id === runId && control.owned_run_id === runId);
  }

  class LivePositionQueue {
    constructor({send, onState = () => {}, onError = () => {}, clock = globalThis, intervalMs = 200}) {
      this.send = send;
      this.onState = onState;
      this.onError = onError;
      this.clock = clock;
      this.intervalMs = intervalMs;
      this.generation = 0;
      this.timer = null;
      this.pending = null;
      this.inflight = false;
      this.lastSentAt = -Infinity;
      this.context = null;
    }

    now() { return typeof this.clock.now === "function" ? this.clock.now() : Date.now(); }

    observe(state, runId, mode) {
      const eligible = canSendTarget(state, runId, mode);
      if (!eligible || this.context?.runId !== runId) this.clear();
      this.context = eligible ? {state, runId} : null;
      // Deliberately no schedule here: observed RUNNING never sends a target.
    }

    clear() {
      this.generation++;
      if (this.timer !== null) this.clock.clearTimeout(this.timer);
      this.timer = null;
      this.pending = null;
      this.context = null;
    }

    input(value) {
      const control = this.context?.state?.closed_loop;
      if (!control || typeof value !== "number" || !Number.isFinite(value) ||
          value < control.soft_min_deg || value > control.soft_max_deg) return false;
      this.pending = value;
      this.schedule();
      return true;
    }

    release(value) { return this.input(value); }

    schedule() {
      if (!this.context || this.pending === null || this.inflight || this.timer !== null) return;
      const wait = Math.max(0, this.lastSentAt + this.intervalMs - this.now());
      if (wait === 0) { this.pump(); return; }
      const generation = this.generation;
      this.timer = this.clock.setTimeout(() => {
        this.timer = null;
        if (generation === this.generation) this.pump();
      }, wait);
    }

    async pump() {
      if (!this.context || this.pending === null || this.inflight) return;
      const generation = this.generation;
      const runId = this.context.runId;
      const target = this.pending;
      this.pending = null;
      this.inflight = true;
      this.lastSentAt = this.now();
      try {
        const state = await this.send({action: "target", run_id: runId, target_deg: target});
        if (generation !== this.generation) return;
        const command = state?.closed_loop?.command;
        if (command?.status !== "accepted" || command.action !== "target")
          throw new Error("实时目标未获得芯片确认。");
        this.onState(state);
      } catch (error) {
        if (generation !== this.generation) return;
        this.clear();
        this.onError(error.message || "实时目标发送失败，运动连接已释放。");
      } finally {
        this.inflight = false;
        this.schedule();
      }
    }
  }
  scope.FOCLivePosition = Object.freeze({LivePositionQueue, canSendTarget});
  if (typeof module !== "undefined") module.exports = scope.FOCLivePosition;
})(globalThis);
