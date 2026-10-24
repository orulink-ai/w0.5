#if defined(DUAL_ENCODER_DIAGNOSTIC)
#include <Arduino.h>
#include "pwm_input.h"
#include "pwm_input_secondary.h"
#include "closed_loop.h" // Reuse the hardware-independent angle/velocity tracker.

namespace {
HardwareSerial console(PA3_ALT1, PA2_ALT1);
closed_loop::AngleTracker trackers[2];
bool ready[2]{};
uint32_t printed_ms = 0;

void report(unsigned index, const as5600::PwmSample& sample,
            const as5600::Reading& reading) {
  console.print("#ENCODER,1,"); console.print(index + 1); console.print(',');
  if (ready[index] && reading.valid) {
    console.print("OK,"); console.print(as5600::toDegrees(reading.angle_rad), 2);
    console.print(','); console.print(trackers[index].velocity(), 3);
    console.print(','); console.print(reading.frequency_hz, 1); console.print(',');
  } else console.print("NO_PWM_OR_INVALID,nan,nan,nan,");
  console.print(sample.high_us); console.print(','); console.println(sample.period_us);
}
} // namespace

void setup() {
  // This entry never creates a driver or accepts motion commands.
  for (const auto pin : {PB5, PB12, PA8, PA9, PA10, PA6, PA7, PB0}) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  console.begin(115200);
  ready[0] = pwm_input::begin();
  ready[1] = pwm_input_secondary::begin();
  console.println("#ENCODER_DIAG,1,PA0,PB7,EN_OFF");
  if (!ready[0]) console.println("#ENCODER_INIT_FAILED,1,TIM2");
  if (!ready[1]) console.println("#ENCODER_INIT_FAILED,2,TIM4");
}

void loop() {
  const as5600::PwmSample samples[] = {pwm_input::snapshot(), pwm_input_secondary::snapshot()};
  const uint32_t now_us = micros();
  const as5600::Reading readings[] = {as5600::decode(samples[0], now_us),
                                     as5600::decode(samples[1], now_us)};
  for (unsigned index = 0; index < 2; ++index) {
    if (readings[index].valid) trackers[index].push(readings[index].angle_rad,
        samples[index].sequence, samples[index].captured_us);
  }
  if (static_cast<uint32_t>(millis() - printed_ms) >= 100) {
    printed_ms = millis();
    report(0, samples[0], readings[0]);
    report(1, samples[1], readings[1]);
  }
  // Drain any late commands from a prior control session without acting on them.
  for (unsigned count = 0; count < 64 && console.available(); ++count) console.read();
}
#endif
