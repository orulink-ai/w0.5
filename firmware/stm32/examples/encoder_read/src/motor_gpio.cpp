#if defined(MOTOR_GPIO_CONTROL)
#include <Arduino.h>
#include <SimpleFOC.h>
#include "enable_output.h"
#include "motor_gpio.h"
#include "pwm_input.h"

namespace {
HardwareSerial console(PA3_ALT1, PA2_ALT1);
// PB5 is owned by enable_output. SimpleFOC init/enable must never raise it.
BLDCDriver3PWM driver(PA8, PA9, PA10);
BLDCMotor motor(7);
motor_gpio::Controller motion;
motor_gpio::Receiver receiver;
bool driver_ready = false;
bool motor_initialized = false;

float readSensorAngle() {
  const auto reading = as5600::decode(pwm_input::snapshot(), micros());
  return reading.valid ? reading.angle_rad : -1.0f;
}
GenericSensor monitor(readSensorAngle); // Independent telemetry, not motor feedback.

const char* stateName() {
  switch (motion.state()) {
    case motor_jog::State::Ready: return "READY";
    case motor_jog::State::Running: return "RUNNING";
    case motor_jog::State::Done: return "DONE";
    default: return "FAULT";
  }
}
void report() {
  console.print("#MOTOR_STATUS,1,");
  console.print(stateName()); console.print(','); console.println(motion.lastId());
}
bool stopOutputs() {
  // Drop the hardware enable before changing the bridge input vector.
  const bool off_confirmed = enable_output::forceOff();
  if (driver_ready) motor.disable();
  if (!off_confirmed) motion.fail();
  return off_confirmed;
}
void updateSafety(bool sensor_valid) {
  const bool old_running = motion.running();
  const bool enable_changed = enable_output::poll(sensor_valid);
  motion.update(millis(), sensor_valid, enable_output::enabled(), enable_output::faulted());
  if (old_running && !motion.running()) {
    stopOutputs();
    report();
    enable_output::report(console);
  } else if (enable_changed) {
    enable_output::report(console);
  }
}
const char* rejection(motor_gpio::Result result) {
  switch (result) {
    case motor_gpio::Result::NotReady: return "SENSOR_NOT_READY";
    case motor_gpio::Result::AlreadyEnabled: return "ALREADY_ENABLED";
    case motor_gpio::Result::AlreadyUsed: return "STALE_ID_OR_RUNNING";
    default: return "FAULT";
  }
}
void applyMotor(motor_gpio::Request request, bool sensor_valid) {
  const auto result = motion.apply(request, millis(), sensor_valid,
                                   enable_output::enabled(), enable_output::faulted());
  bool accepted = false;
  const char* reply = nullptr;
  if (result == motor_gpio::Result::Stopped) {
    accepted = stopOutputs() && !enable_output::faulted();
    if (!accepted) motion.fail();
    reply = accepted ? "STOPPED" : "PIN_READBACK";
  } else if (result == motor_gpio::Result::Started && motor_initialized) {
    // Establish a bounded phase vector while EN is still LOW. No initFOC or
    // sensor alignment occurs in this intentionally open-loop wiring test.
    motor.shaft_angle = 0.0f;
    motor.enable();
    motor.move(0.5f);
    motor.loopFOC();
    if (enable_output::enableForMotion(request.id, sensor_valid) == enable_control::Result::Accepted) {
      accepted = true;
      reply = "STARTED";
    } else {
      motion.fail(); stopOutputs(); reply = "ENABLE_FAILED";
    }
  } else {
    reply = rejection(result);
    if (result == motor_gpio::Result::Started) {
      motion.fail(); stopOutputs(); reply = "NOT_INITIALIZED";
    }
  }
  console.print(accepted ? "#MOTOR_ACK," : "#MOTOR_NACK,");
  console.print(request.id); console.print(','); console.println(reply);
  report();
  enable_output::report(console);
}

void receiveCommand() {
  // Route one bounded complete line per iteration. ENABLE and MOTOR have
  // independent request-id namespaces and cannot parse each other's packets.
  static char line[48]{};
  static size_t length = 0;
  static bool overflow = false;
  for (uint8_t count = 0; count < 64 && console.available(); ++count) {
    const char byte = static_cast<char>(console.read());
    if (byte != '\n') {
      if (!overflow && length < sizeof(line) - 1) line[length++] = byte;
      else overflow = true;
      continue;
    }
    const auto reading = as5600::decode(pwm_input::snapshot(), micros());
    if (!overflow && length >= 7 && std::memcmp(line, "ENABLE,", 7) == 0) {
      for (size_t i = 0; i < length; ++i) enable_output::receive(line[i], reading.valid, console);
      enable_output::receive('\n', reading.valid, console);
    } else if (!overflow && length >= 6 && std::memcmp(line, "MOTOR,", 6) == 0) {
      for (size_t i = 0; i < length; ++i) receiver.feed(line[i]);
      if (receiver.feed('\n') == motor_gpio::ParseResult::Ready) {
        applyMotor(receiver.request(), reading.valid);
      } else console.println("#MOTOR_NACK,0,MALFORMED");
    } else console.println("#MOTOR_NACK,0,MALFORMED");
    length = 0;
    overflow = false;
    return;
  }
}
} // namespace

void setup() {
  digitalWrite(PB5, LOW); pinMode(PB5, OUTPUT);
  for (const auto pin : {PA8, PA9, PA10}) {
    digitalWrite(pin, LOW); pinMode(pin, OUTPUT);
  }
  const bool watchdog_reset = __HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST);
  // IWDG may already be running after an ST-Link software reset. Temporarily
  // extend it before motor.init()'s 1-second delay; PB5 remains LOW throughout.
  const bool startup_watchdog_ready = watchdog_reset || enable_output::prepareInitialization();
  console.begin(115200);
  const bool capture_ready = pwm_input::begin();
  driver.voltage_power_supply = 12.0f;
  driver.voltage_limit = 12.0f;
  driver.pwm_frequency = 25000;
  driver_ready = driver.init();
  if (driver_ready) {
    motor.linkDriver(&driver);
    motor.controller = MotionControlType::velocity_openloop;
    motor.torque_controller = TorqueControlType::voltage;
    motor.voltage_limit = 1.0f;
    motor.velocity_limit = 0.5f;
    // A genuine watchdog fault stays locked off and skips blocking init.
    if (!watchdog_reset && startup_watchdog_ready) motor_initialized = motor.init();
    motor.disable();
  }
  // Preserve TIM1 alternate functions; restore the short (~100ms) watchdog.
  // This also consumes the original reset flags and latches IWDG faults.
  enable_output::begin(false);
  if (!capture_ready || !motor_initialized || !startup_watchdog_ready ||
      watchdog_reset || enable_output::faulted()) {
    motion.fail(); stopOutputs();
  }
  console.println("#MOTOR_BENCH,PB5 gated; explicit numbered JOG; 1V,0.5rad_s,about_3000ms");
  console.println("#MOTOR_BENCH,nFAULT not monitored; voltage mode is not current limiting");
  report();
  enable_output::report(console);
}

void loop() {
  auto sample = pwm_input::snapshot();
  auto reading = as5600::decode(sample, micros());
  updateSafety(reading.valid);
  receiveCommand();
  sample = pwm_input::snapshot();
  reading = as5600::decode(sample, micros());
  updateSafety(reading.valid); // Recheck after bounded UART acknowledgement work.
  if (motion.running()) {
    motor.move(0.5f);
    motor.loopFOC();
  }

  static bool monitor_ready = false;
  static uint32_t monitored_sequence = 0;
  static float velocity = 0.0f;
  if (!reading.valid) monitor_ready = false;
  else if (sample.sequence != monitored_sequence) {
    if (!monitor_ready) {
      monitor = GenericSensor(readSensorAngle);
      monitor.init();
      monitor_ready = true;
    }
    monitor.update();
    velocity = monitor.getVelocity();
    monitored_sequence = sample.sequence;
  }
  static uint32_t printed_ms = 0;
  const uint32_t now = millis();
  if (static_cast<uint32_t>(now - printed_ms) >= 100U) {
    printed_ms = now;
    if (reading.valid) {
      console.print("OK,"); console.print(as5600::toDegrees(reading.angle_rad), 2);
      console.print(','); console.print(velocity, 3); console.print(',');
      console.print(reading.frequency_hz, 1); console.print(',');
    } else console.print("NO_PWM_OR_INVALID,nan,nan,nan,");
    console.print(sample.high_us); console.print(','); console.println(sample.period_us);
  }
  static uint32_t status_ms = 0;
  if (static_cast<uint32_t>(now - status_ms) >= 500U) {
    status_ms = now; report(); enable_output::report(console);
  }
}
#endif
