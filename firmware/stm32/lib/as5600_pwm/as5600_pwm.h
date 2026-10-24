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
  // Optional hardware timer units. The *_us fields remain telemetry only when
  // counter_hz is nonzero; decode must not discard sub-microsecond information.
  uint32_t high_ticks = 0;
  uint32_t period_ticks = 0;
  uint32_t counter_hz = 0;
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
  void frame(uint32_t high_ticks, uint32_t period_ticks, uint32_t now_us,
             bool falling_captured, bool overcapture,
             uint32_t counter_hz = 1000000U) {
    // Convert telemetry once per frame, keeping the interrupt-masked snapshot
    // a plain copy even when the motor loop polls much faster than the sensor.
    high_us_ = toMicroseconds(high_ticks, counter_hz);
    period_us_ = toMicroseconds(period_ticks, counter_hz);
    high_ticks_ = high_ticks;
    period_ticks_ = period_ticks;
    counter_hz_ = counter_hz;
    captured_us_ = now_us;
    complete_ = primed_ && falling_captured && !overcapture && counter_hz != 0;
    primed_ = true;
    ++sequence_;
  }

  PwmSample sample() const {
    return {high_us_, period_us_, captured_us_, complete_, sequence_,
            high_ticks_, period_ticks_, counter_hz_};
  }

 private:
  static uint32_t toMicroseconds(uint32_t ticks, uint32_t hz) {
    if (hz == 0) return 0;
    if (hz % 1000000U == 0) return ticks / (hz / 1000000U);
    return static_cast<uint32_t>(std::min<uint64_t>(
        UINT32_MAX, static_cast<uint64_t>(ticks) * 1000000U / hz));
  }
  bool primed_ = false;
  volatile uint32_t high_us_ = 0;
  volatile uint32_t period_us_ = 0;
  volatile uint32_t high_ticks_ = 0;
  volatile uint32_t period_ticks_ = 0;
  volatile uint32_t counter_hz_ = 0;
  volatile uint32_t captured_us_ = 0;
  volatile uint32_t sequence_ = 0;
  volatile bool complete_ = false;
};

inline Reading decode(const PwmSample& sample, uint32_t now_us) {
  const bool raw = sample.counter_hz != 0;
  if (!raw && (sample.high_ticks != 0 || sample.period_ticks != 0)) return {};
  const uint32_t high = raw ? sample.high_ticks : sample.high_us;
  const uint32_t period = raw ? sample.period_ticks : sample.period_us;
  const uint32_t hz = raw ? sample.counter_hz : 1000000U;
  const uint64_t period_scaled = static_cast<uint64_t>(period) * 1000000U;
  const uint64_t age_scaled =
      static_cast<uint64_t>(static_cast<uint32_t>(now_us - sample.captured_us)) * hz;
  // AS5600 nominal frequencies: 115, 230, 460, 920 Hz (allow oscillator error).
  if (!sample.complete || period_scaled < static_cast<uint64_t>(hz) * 950 ||
      period_scaled > static_cast<uint64_t>(hz) * 10000 ||
      high == 0 || high >= period || age_scaled >= 3 * period_scaled) {
    return {};
  }
  // Full-range output: 128 high header clocks, 0..4095 angle clocks,
  // and a low trailer within a total of 4351 clocks. Allow edge timestamp jitter.
  const float clocks = 4351.0f * high / period;
  if (clocks < 96.0f || clocks > 4255.0f) {
    return {};
  }
  const float count = std::max(0.0f, std::min(4095.0f, clocks - 128.0f));
  return {true, count * kTwoPi / 4096.0f, static_cast<float>(hz) / period};
}

} // namespace as5600
