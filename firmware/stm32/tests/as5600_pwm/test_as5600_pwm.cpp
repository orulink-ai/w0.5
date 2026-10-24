#include "as5600_pwm.h"
#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {
void require(bool result, const char* message) {
  if (!result) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

void near(float actual, float expected, float tolerance, const char* message) {
  require(std::fabs(actual - expected) <= tolerance, message);
}
}

int main() {
  using namespace as5600;
  near(toDegrees(kTwoPi * 0.5f), 180.0f, 0.001f, "half turn is 180 degrees");
  near(toDegrees(kTwoPi), 360.0f, 0.001f, "full turn is 360 degrees");
  const auto loopback = decode({2000, 4000, 100, true}, 100);
  require(loopback.valid, "250 Hz loopback input is decodable");
  near(loopback.frequency_hz, 250.0f, 0.001f, "loopback frequency");
  near(toDegrees(loopback.angle_rad), 179.956f, 0.001f,
       "50 percent duty includes AS5600 header offset");
  PwmCapture capture;
  require(!decode(capture.sample(), 0).valid, "no signal is invalid");
  capture.edge(false, 10); // A falling edge without a rising edge is not a pulse.
  capture.edge(true, 100);
  capture.edge(false, 600);
  require(!decode(capture.sample(), 600).valid, "must measure a full period");
  capture.edge(true, 1100);
  auto sample = capture.sample();
  require(sample.period_us == 1000 && sample.high_us == 500, "paired pulse/period");
  near(decode(sample, 1100).angle_rad, kTwoPi * 0.5f, 0.002f, "half turn");
  require(!decode(sample, 11100).valid, "stale signal is invalid after 3 periods");
  require(decode(sample, 4099).valid, "freshness boundary below 3 periods");
  require(!decode(sample, 4100).valid, "freshness boundary at 3 periods");
  capture.edge(false, 1850);
  require(capture.sample().high_us == 500, "next falling edge cannot overwrite completed frame");
  capture.edge(true, 2100);
  require(capture.sample().high_us == 750, "new period commits matching high width");

  TimerCapture timer_capture;
  timer_capture.frame(500, 1000, 100, true, false);
  require(!timer_capture.sample().complete, "first timer capture is not a full frame");
  timer_capture.frame(500, 1000, 1100, true, false);
  require(decode(timer_capture.sample(), 1100).valid, "paired hardware captures decode");
  timer_capture.frame(500, 1000, 2100, false, false);
  require(!timer_capture.sample().complete, "missing falling capture rejected");
  timer_capture.frame(500, 1000, 3100, true, true);
  require(!timer_capture.sample().complete, "overcapture cannot publish a valid angle");
  timer_capture.frame(750, 1000, 4100, true, false);
  require(timer_capture.sample().sequence == 5, "hardware frames counted including invalid");
  require(timer_capture.sample().complete && timer_capture.sample().high_us == 750,
          "hardware capture recovers and preserves matching widths");

  // Integer-microsecond samples across all AS5600 PWM frequency settings.
  for (const uint32_t period : {8696U, 4348U, 2174U, 1087U}) {
    for (const uint32_t count : {0U, 1024U, 2048U, 3072U, 4095U}) {
      const auto high = static_cast<uint32_t>(std::lround(
          static_cast<double>(128U + count) * period / 4351.0));
      const auto result = decode({high, period, 100, true}, 100);
      require(result.valid, "valid AS5600 pulse");
      near(result.angle_rad, kTwoPi * count / 4096.0f, 0.005f,
           "header-aware angle at every frequency");
      require(result.angle_rad >= 0 && result.angle_rad < kTwoPi, "single-turn range");
    }
  }
  require(!decode({0, 1087, 0, true}, 0).valid, "stuck low");
  require(!decode({1087, 1087, 0, true}, 0).valid, "stuck high");
  require(!decode({1100, 1087, 0, true}, 0).valid, "high greater than period");
  require(!decode({50, 100, 0, true}, 0).valid, "unsupported high frequency");
  require(!decode({10000, 20000, 0, true}, 0).valid, "unsupported low frequency");

  capture.edge(true, 3100); // No falling edge: do not re-use previous high width.
  require(!decode(capture.sample(), 3100).valid, "missing falling edge invalidates frame");
  capture.edge(false, 3600);
  capture.edge(true, 4100);
  require(decode(capture.sample(), 4100).valid, "recovers with complete frame");

  PwmCapture rollover;
  rollover.edge(true, UINT32_MAX - 499);
  rollover.edge(false, 0);
  rollover.edge(true, 500);
  const auto wrapped = rollover.sample();
  require(wrapped.period_us == 1000 && wrapped.high_us == 500, "micros rollover");
  require(decode(wrapped, 600).valid, "freshness survives rollover");
  require(!decode(wrapped, 3500).valid, "timeout survives rollover");

  // Sub-microsecond information must survive the capture/decoder boundary,
  // even when the integer-microsecond telemetry shows identical pulse widths.
  TimerCapture precise;
  precise.frame(6000, 17400, 100, true, false, 8000000);
  precise.frame(6000, 17400, 2275, true, false, 8000000);
  const auto first = precise.sample();
  precise.frame(6004, 17400, 4450, true, false, 8000000);
  const auto second = precise.sample();
  require(first.high_us == second.high_us, "telemetry can share an integer width");
  require(second.high_ticks == 6004 && second.period_ticks == 17400 &&
              second.counter_hz == 8000000, "capture retains raw timer units");
  const auto a = decode(first, 2275);
  const auto b = decode(second, 4450);
  require(a.valid && b.valid, "8 MHz captures decode");
  near(a.frequency_hz, 8000000.0f / 17400, 0.001f, "raw counter frequency");
  near(toDegrees(b.angle_rad - a.angle_rad),
       4351.0f * 4 / 17400 * 360 / 4096, 0.0001f,
       "half-microsecond pulse difference is retained");

  for (const uint32_t period_ticks : {69568U, 34784U, 17392U, 8696U}) {
    for (uint32_t count = 0; count < 4096; ++count) {
      const auto high_ticks = static_cast<uint32_t>(std::lround(
          static_cast<double>(128U + count) * period_ticks / 4351));
      precise.frame(high_ticks, period_ticks, 100, true, false, 8000000);
      const auto result = decode(precise.sample(), 100);
      require(result.valid, "all 4096 positions decode at every PWM frequency");
      const float half_tick_degrees = 0.5f * 4351 / period_ticks * 360 / 4096;
      near(toDegrees(result.angle_rad), count * 360.0f / 4096,
           half_tick_degrees + 0.0001f, "error bounded by timer quantization");
    }
  }
  precise.frame(4000, 8001, UINT32_MAX - 100, true, false, 8000000);
  const auto fractional_period = precise.sample();
  require(decode(fractional_period, 2899).valid,
          "freshness retains fractional period across micros rollover");
  require(!decode(fractional_period, 2900).valid,
          "fractional period expires after three complete periods");
  precise.frame(500, UINT32_MAX, 100, true, false, 8000000);
  require(!decode(precise.sample(), 100).valid, "long raw periods cannot overflow validation");
  precise.frame(8000, 7999, 100, true, false, 8000000);
  require(!decode(precise.sample(), 100).valid, "raw high cannot exceed period");
  precise.frame(4000, 7599, 100, true, false, 8000000);
  require(!decode(precise.sample(), 100).valid, "raw period below supported range");
  precise.frame(40000, 80001, 100, true, false, 8000000);
  require(!decode(precise.sample(), 100).valid, "raw period above supported range");
  precise.frame(4000, 8000, 100, true, true, 8000000);
  require(!decode(precise.sample(), 100).valid, "raw overcapture rejected");
  precise.frame(4000, 8000, 100, true, false, 0);
  require(!decode(precise.sample(), 100).valid, "zero counter rate rejected");
  // Two physical inputs have independent capture state and timer units. TIM4
  // uses 4 MHz so its 16-bit period also fits the slowest 115 Hz PWM setting.
  TimerCapture input_a, input_b;
  const uint32_t ticks_a = 17400, ticks_b = 34784;
  const uint32_t high_a = std::lround((128.0 + 1024) * ticks_a / 4351);
  const uint32_t high_b = std::lround((128.0 + 3072) * ticks_b / 4351);
  for (uint32_t stamp : {100U, 200U}) {
    input_a.frame(high_a, ticks_a, stamp, true, false, 8000000);
    input_b.frame(high_b, ticks_b, stamp, true, false, 4000000);
  }
  near(toDegrees(decode(input_a.sample(), 201).angle_rad), 90, .05,
       "first channel uses its own 8 MHz capture");
  near(toDegrees(decode(input_b.sample(), 201).angle_rad), 270, .05,
       "second channel uses its own 4 MHz capture");
  require(ticks_b <= 65535, "115 Hz input fits the 16 bit secondary timer");
  require(!decode(input_a.sample(), 7000).valid && decode(input_b.sample(), 7000).valid,
          "channel timeouts use each input's independent period");
  input_b.frame(high_b, ticks_b, 300, true, true, 4000000);
  require(!decode(input_b.sample(), 301).valid && decode(input_a.sample(), 301).valid,
          "secondary overcapture never invalidates the primary input");
  std::cout << "PASS: AS5600 PWM decoding, independent inputs, timeout and rollover\n";
}
