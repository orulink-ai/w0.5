#if defined(ENABLE_PIN_CONTROL)
#include "enable_output.h"
#include "enable_control.h"

namespace {
enable_control::Controller controller;
enable_control::Receiver receiver;
IWDG_HandleTypeDef watchdog{};
bool watchdog_ready = false;

bool pinHigh() { return (GPIOB->IDR & GPIO_IDR_ID5) != 0; }

bool driveOutput() {
  digitalWrite(PB5, controller.enabled() ? HIGH : LOW);
  __DSB();
  if (pinHigh() == controller.enabled()) return true;
  controller.fail();
  digitalWrite(PB5, LOW);
  return false;
}

bool beginWatchdog(uint32_t prescaler, uint32_t reload) {
  RCC_OscInitTypeDef clock{};
  clock.OscillatorType = RCC_OSCILLATORTYPE_LSI;
  clock.LSIState = RCC_LSI_ON;
  clock.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&clock) != HAL_OK) return false;
  watchdog.Instance = IWDG;
  watchdog.Init.Prescaler = prescaler;
  watchdog.Init.Reload = reload;
  watchdog.Init.Window = IWDG_WINDOW_DISABLE;
  return HAL_IWDG_Init(&watchdog) == HAL_OK;
}

const char* errorName(enable_control::Result result) {
  switch (result) {
    case enable_control::Result::SensorInvalid: return "SENSOR_INVALID";
    case enable_control::Result::Busy: return "ALREADY_ENABLED";
    case enable_control::Result::Conflict: return "ID_CONFLICT";
    case enable_control::Result::Expired: return "EXPIRED";
    default: return "FAULT";
  }
}
} // namespace

namespace enable_output {
bool prepareInitialization() {
  digitalWrite(PB5, LOW);
  pinMode(PB5, OUTPUT);
  return beginWatchdog(IWDG_PRESCALER_256, 4095);
}

void begin(bool initialize_phase_pins) {
  // The standalone enable test keeps all bridge inputs static LOW. Motor
  // builds call begin(false) after configuring TIM1, with PB5 still LOW.
  if (initialize_phase_pins) {
    for (const auto pin : {PA8, PA9, PA10}) {
      digitalWrite(pin, LOW);
      pinMode(pin, OUTPUT);
    }
  }
  const bool watchdog_reset = __HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST);
  __HAL_RCC_CLEAR_RESET_FLAGS();
  watchdog_ready = beginWatchdog(IWDG_PRESCALER_32, 99);
  if (!watchdog_ready || watchdog_reset) controller.fail();
  driveOutput();
}

bool enabled() { return controller.enabled() && pinHigh(); }
bool faulted() { return controller.faulted() || !watchdog_ready; }

enable_control::Result enableForMotion(uint32_t, bool sensor_valid) {
  if (!watchdog_ready) return enable_control::Result::Fault;
  if (controller.enabled() || pinHigh()) return enable_control::Result::Busy;
  const auto result = controller.startForMotion(millis(), sensor_valid);
  if (!driveOutput()) return enable_control::Result::Fault;
  return result;
}

bool forceOff() {
  controller.stop();
  return driveOutput();
}

bool poll(bool sensor_valid) {
  if (watchdog_ready) HAL_IWDG_Refresh(&watchdog);
  const bool previous_enabled = controller.enabled();
  const bool previous_fault = controller.faulted();
  controller.update(millis(), sensor_valid);
  driveOutput();
  return previous_enabled != controller.enabled() || previous_fault != controller.faulted();
}

void report(Print& output) {
  output.print("#ENABLE_STATUS,1,");
  output.print(controller.faulted() ? "FAULT," : "READY,");
  output.print(pinHigh() ? 1 : 0);
  output.print(',');
  output.println(controller.lastId());
}

void receive(char byte, bool sensor_valid, Print& output) {
  const auto parsed = receiver.feed(byte);
  if (parsed == enable_control::ParseResult::None) return;
  if (parsed == enable_control::ParseResult::Invalid) {
    output.println("#ENABLE_NACK,0,MALFORMED");
    return;
  }
  const auto request = receiver.request();
  const auto result = controller.apply(request, millis(), sensor_valid);
  const bool readback_ok = driveOutput();
  const bool accepted = result == enable_control::Result::Accepted && readback_ok;
  output.print(accepted ? "#ENABLE_ACK," : "#ENABLE_NACK,");
  output.print(request.id);
  output.print(',');
  if (accepted) output.println(pinHigh() ? 1 : 0);
  else output.println(readback_ok ? errorName(result) : "PIN_READBACK");
  report(output);
}
} // namespace enable_output
#endif
