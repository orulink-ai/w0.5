#if defined(MOTOR_BENCH_JOG)
#include <Arduino.h>
#include <SimpleFOC.h>
#include "motor_jog.h"
#include "pwm_input.h"

namespace {
HardwareSerial console(PA3_ALT1, PA2_ALT1);
// Deliberately NO GPIO enable pin: the unmodified board's 100-ohm EN load
// must be supplied externally, never from PB5. This does NOT provide Hi-Z stop.
BLDCDriver3PWM driver(PA8, PA9, PA10);
BLDCMotor motor(7);
motor_jog::Guard guard;
motor_jog::Receiver commands;
float readSensorAngle() {
  const auto reading = as5600::decode(pwm_input::snapshot(), micros());
  return reading.valid ? reading.angle_rad : -1.0f;
}
GenericSensor monitor(readSensorAngle); // Telemetry only; not linked to the motor.
IWDG_HandleTypeDef watchdog{};
bool driver_ready = false;
bool watchdog_ready = false;

const char* stateName() {
  switch (guard.state()) {
    case motor_jog::State::Ready: return "READY";
    case motor_jog::State::Running: return "RUNNING";
    case motor_jog::State::Done: return "DONE";
    default: return "FAULT";
  }
}

void report() {
  console.print("#JOG_STATUS,1,");
  console.print(stateName());
  console.println(",MANUAL_EN,1.0V,0.5rad_s,3000ms");
}

void stopPwm() {
  if (driver_ready) motor.disable(); // Three low-side switches on; NOT Hi-Z.
}

bool beginWatchdog() {
  RCC_OscInitTypeDef clock{};
  clock.OscillatorType = RCC_OSCILLATORTYPE_LSI;
  clock.LSIState = RCC_LSI_ON;
  clock.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&clock) != HAL_OK) return false;
  watchdog.Instance = IWDG;
  watchdog.Init.Prescaler = IWDG_PRESCALER_32;
  watchdog.Init.Reload = 99; // ~100ms at nominal 32kHz LSI; tolerance applies.
  watchdog.Init.Window = IWDG_WINDOW_DISABLE;
  return HAL_IWDG_Init(&watchdog) == HAL_OK;
}
} // namespace

void setup() {
  // The test cannot software-enable PB5, even if the old wire remains attached.
  digitalWrite(PB5, LOW);
  pinMode(PB5, OUTPUT);
  for (const auto pin : {PA8, PA9, PA10}) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  const bool watchdog_reset = __HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST);
  __HAL_RCC_CLEAR_RESET_FLAGS();
  console.begin(115200);
  const bool capture_ready = pwm_input::begin();
  driver.voltage_power_supply = 12.0f;
  driver.voltage_limit = 12.0f; // Preserve the SinePWM common-mode headroom.
  driver.pwm_frequency = 25000;
  driver_ready = driver.init();
  if (driver_ready) {
    motor.linkDriver(&driver);
    motor.controller = MotionControlType::velocity_openloop;
    motor.torque_controller = TorqueControlType::voltage;
    motor.voltage_limit = 1.0f;
    motor.velocity_limit = 0.5f;
    // init() contains 1s of delays. On a watchdog reset it must be skipped:
    // IWDG is already running and a fault must never re-enable the motor.
    if (watchdog_reset) guard.fail();
    else if (!motor.init()) guard.fail();
    stopPwm();
  } else {
    guard.fail();
  }
  watchdog_ready = beginWatchdog();
  if (!capture_ready || !watchdog_ready || watchdog_reset) guard.fail();
  console.println("#JOG_BENCH,manual EN external 3.3V; PB5 always LOW; NO hardware shutdown");
  console.println("#JOG_BENCH,one JOG per boot; STOP/timeout/invalid PWM -> low-side brake");
  console.println("#JOG_BENCH,nFAULT not monitored; voltage mode is not current limiting");
  report();
}

void loop() {
  if (watchdog_ready) HAL_IWDG_Refresh(&watchdog);
  const auto sample = pwm_input::snapshot();
  const auto reading = as5600::decode(sample, micros());
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
  const bool was_running = guard.running();
  guard.update(millis(), reading.valid);
  if (was_running && !guard.running()) { stopPwm(); report(); }

  // One byte per pass: bursts of invalid commands must not hold this loop in
  // synchronous ACK/log writes while an old phase vector remains energized.
  if (console.available()) {
    switch (commands.feed(static_cast<char>(console.read()))) {
      case motor_jog::Command::Jog:
        if (driver_ready && watchdog_ready && guard.start(millis())) {
          // No initFOC or sensor alignment in this open-loop wiring test.
          motor.shaft_angle = 0.0f;
          motor.enable();
          console.println("#JOG_ACK,STARTED");
        } else {
          console.println("#JOG_NACK,NOT_READY_OR_ALREADY_USED");
        }
        report();
        break;
      case motor_jog::Command::Stop:
        guard.stop(); stopPwm();
        console.println("#JOG_ACK,STOPPED"); report();
        break;
      case motor_jog::Command::Invalid:
        console.println("#JOG_NACK,UNKNOWN_COMMAND");
        break;
      default: break;
    }
  }

  if (guard.running()) {
    const auto current = as5600::decode(pwm_input::snapshot(), micros());
    guard.update(millis(), current.valid); // Recheck after UART processing.
    if (!guard.running()) {
      stopPwm(); report();
    } else {
      // SimpleFOC 2.4 move() updates open-loop state; loopFOC() writes the PWM.
      motor.move(0.5f);
      motor.loopFOC();
    }
  }
  static uint32_t printed_ms = 0;
  const uint32_t now = millis();
  if (static_cast<uint32_t>(now - printed_ms) >= 100U) {
    printed_ms = now;
    if (reading.valid) {
      console.print("OK,"); console.print(as5600::toDegrees(reading.angle_rad), 2);
      console.print(','); console.print(velocity, 3); console.print(',');
      console.print(reading.frequency_hz, 1); console.print(',');
    } else {
      console.print("NO_PWM_OR_INVALID,nan,nan,nan,");
    }
    console.print(sample.high_us); console.print(','); console.println(sample.period_us);
  }
  static uint32_t status_ms = 0;
  if (static_cast<uint32_t>(now - status_ms) >= 1000U) {
    status_ms = now; report();
  }
}
#endif
