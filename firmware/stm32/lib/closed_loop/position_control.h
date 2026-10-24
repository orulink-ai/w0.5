#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace closed_loop {
// A trajectory is independent of the measured angle after explicit START.
// Feedback movement must never redefine the requested trajectory target.
class RateLimitedReference {
 public:
  bool start(float current, float target, float speed_rad_s, uint32_t now) {
    if (!std::isfinite(current) || !std::isfinite(target) ||
        !std::isfinite(speed_rad_s) || speed_rad_s <= 0) return false;
    reference_ = current;
    requested_ = target;
    speed_ = speed_rad_s;
    updated_ms_ = now;
    return true;
  }
  float update(uint32_t now) {
    const float step = static_cast<uint32_t>(now - updated_ms_) * .001f * speed_;
    updated_ms_ = now;
    const float remaining = requested_ - reference_;
    if(std::fabs(remaining)<=step) reference_=requested_;
    else reference_+=std::copysign(step,remaining);
    return reference_;
  }
  float current() const { return reference_; }
  float velocity() const {
    if(reference_==requested_)return 0;
    return reference_<requested_?speed_:-speed_;
  }
 private:
  float reference_ = 0, requested_ = 0, speed_ = 0;
  uint32_t updated_ms_ = 0;
};

} // namespace closed_loop
