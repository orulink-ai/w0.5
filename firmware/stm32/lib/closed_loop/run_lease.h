#pragma once
#include <cstdint>

namespace closed_loop {
// Shared by calibration and runtime. A pulse can refresh an existing lease;
// it cannot acquire ownership or resurrect an expired/stopped run.
class RunLease {
 public:
  static constexpr uint32_t kTimeoutMs = 1500;
  bool start(uint32_t run_id, uint32_t now) {
    if (run_id == 0 || run_id > 2147483647U || active()) return false;
    run_id_ = run_id;
    refreshed_ms_ = now;
    return true;
  }
  bool active() const { return run_id_ != 0; }
  uint32_t runId() const { return run_id_; }
  bool owns(uint32_t run_id, uint32_t now) const {
    return active() && run_id==run_id_ && remaining(now)>0;
  }
  uint32_t remaining(uint32_t now) const {
    if (!active()) return 0;
    const uint32_t age = now - refreshed_ms_;
    return age >= kTimeoutMs ? 0 : kTimeoutMs - age;
  }
  bool expire(uint32_t now) {
    if (!active() || remaining(now) != 0) return false;
    stop();
    return true;
  }
  bool keepalive(uint32_t run_id, uint32_t now) {
    expire(now); // Late matching pulses never revive the old run.
    if (!active() || run_id != run_id_) return false;
    refreshed_ms_ = now;
    return true;
  }
  void stop() { run_id_ = 0; }
 private:
  uint32_t run_id_ = 0;
  uint32_t refreshed_ms_ = 0;
};
} // namespace closed_loop
