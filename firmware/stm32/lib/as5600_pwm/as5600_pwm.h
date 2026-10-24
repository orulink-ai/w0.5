#pragma once

#include <algorithm>
#include <cstdint>

namespace as5600 {

constexpr float kTwoPi = 6.2831853071795864769f;
constexpr float toDegrees(float radians) { return radians * 360.0f / kTwoPi; }

struct PwmSample {
  uint32_t high_us = 0;
  uint32_t period_us = 0;
  uint32_t captured_us = 0;
  bool complete = false;
  uint32_t sequence = 0;
};

struct Reading {
  bool valid = false;
  float angle_rad = 0;
  float frequency_hz = 0;
};

// Hardware-independent capture. Call edge() from a CHANGE interrupt, and copy
// sample() with that interrupt masked. A frame closes on its next rising edge.
class PwmCapture {
 public:
  void edge(bool high, uint32_t now_us) {
    if (high) {
      period_us_ = now_us - rising_us_;
      complete_ = have_rising_ && have_falling_;
      high_us_ = pending_high_us_;
      captured_us_ = now_us;
      ++sequence_;
      rising_us_ = now_us;
      have_rising_ = true;
      have_falling_ = false;
    } else if (have_rising_ && !have_falling_) {
      pending_high_us_ = now_us - rising_us_;
      have_falling_ = true;
    }
  }

  PwmSample sample() const {
    return {high_us_, period_us_, captured_us_, complete_, sequence_};
  }

 private:
  uint32_t rising_us_ = 0;
  uint32_t pending_high_us_ = 0;
  bool have_rising_ = false;
  bool have_falling_ = false;
  volatile uint32_t high_us_ = 0;
  volatile uint32_t period_us_ = 0;
  volatile uint32_t captured_us_ = 0;
  volatile uint32_t sequence_ = 0;
  volatile bool complete_ = false;
};

// Publishes a timer's paired CCR high/period readings. The first rising capture
// starts a frame; missing falls and hardware overcapture invalidate that frame.
// Call frame() in the timer ISR and sample() with interrupts masked.
class TimerCapture {
 public:
  void frame(uint32_t high_us, uint32_t period_us, uint32_t now_us,
             bool falling_captured, bool overcapture) {
    high_us_ = high_us;
    period_us_ = period_us;
    captured_us_ = now_us;
    complete_ = primed_ && falling_captured && !overcapture;
    primed_ = true;
    ++sequence_;
  }

  PwmSample sample() const {
    return {high_us_, period_us_, captured_us_, complete_, sequence_};
  }

 private:
  bool primed_ = false;
  volatile uint32_t high_us_ = 0;
  volatile uint32_t period_us_ = 0;
  volatile uint32_t captured_us_ = 0;
  volatile uint32_t sequence_ = 0;
  volatile bool complete_ = false;
};

inline Reading decode(const PwmSample& sample, uint32_t now_us) {
  // AS5600 nominal frequencies: 115, 230, 460, 920 Hz (allow oscillator error).
  if (!sample.complete || sample.period_us < 950 || sample.period_us > 10000 ||
      sample.high_us == 0 || sample.high_us >= sample.period_us ||
      static_cast<uint32_t>(now_us - sample.captured_us) >= 3 * sample.period_us) {
    return {};
  }
  // Full-range output: 128 high header clocks, 0..4095 angle clocks,
  // and a low trailer within a total of 4351 clocks. Allow edge timestamp jitter.
  const float clocks = 4351.0f * sample.high_us / sample.period_us;
  if (clocks < 96.0f || clocks > 4255.0f) {
    return {};
  }
  const float count = std::max(0.0f, std::min(4095.0f, clocks - 128.0f));
  return {true, count * kTwoPi / 4096.0f, 1000000.0f / sample.period_us};
}

} // namespace as5600
