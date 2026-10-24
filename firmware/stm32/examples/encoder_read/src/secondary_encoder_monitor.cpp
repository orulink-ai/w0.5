#if defined(CLOSED_LOOP_CONTROL)
#include "secondary_encoder_monitor.h"
#include "pwm_input_secondary.h"

namespace {
// Use Arduino's existing float formatter, matching primary telemetry. The
// embedded nano printf build omits %f support. No heap or UART waits here.
class RecordBuffer final : public Print {
 public:
  size_t write(uint8_t byte) override {
    if (length >= sizeof(bytes)) { overflow = true; return 0; }
    bytes[length++] = byte;
    return 1;
  }
  uint8_t bytes[144]{};
  size_t length = 0;
  bool overflow = false;
};
} // namespace

void SecondaryEncoderMonitor::begin() {
  // The second driver remains disabled; only its encoder is used in this build.
  digitalWrite(PB12, LOW);
  pinMode(PB12, OUTPUT);
  ready_ = pwm_input_secondary::begin();
}

void SecondaryEncoderMonitor::tick(HardwareSerial& console) {
  const auto sample = pwm_input_secondary::snapshot();
  const auto reading = as5600::decode(sample, micros());
  const bool valid = ready_ && reading.valid;
  if (valid) tracker_.push(reading.angle_rad, sample.sequence, sample.captured_us);
  const uint32_t now = millis();
  if (static_cast<uint32_t>(now - report_ms_) < 100) return;
  report_ms_ = now;
  RecordBuffer line;
  line.print("#ENCODER_AUX,1,2,");
  if (valid) {
    line.print("OK,"); line.print(as5600::toDegrees(reading.angle_rad), 2);
    line.print(','); line.print(tracker_.velocity(), 3);
    line.print(','); line.print(reading.frequency_hz, 1); line.print(',');
  } else line.print("NO_PWM_OR_INVALID,nan,nan,nan,");
  line.print(sample.high_us); line.print(','); line.print(sample.period_us); line.print('\n');
  // Auxiliary telemetry never waits for UART space or delays primary control.
  // Congestion drops one display frame; the next 100ms slot retries fresh data.
  if (!line.overflow && console.availableForWrite() >= static_cast<int>(line.length)) {
    console.write(line.bytes, line.length);
  }
}
#endif
