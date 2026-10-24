#include <Arduino.h>
#include <SimpleFOC.h>
#include "as5600_pwm.h"
#include "pwm_input.h"
#include "pwm_loopback.h"
#include "angle_target.h"
#include "enable_output.h"

namespace {
constexpr uint32_t kPrintIntervalMs = 100;
#if defined(USBCON) && defined(USBD_USE_CDC)
auto& console = SerialUSB;
#else
// The generic G431 map defaults these pins to LPUART1. ALT1 selects USART2.
HardwareSerial console(PA3_ALT1, PA2_ALT1); // RX, TX; 3.3V USB-UART adapter.
#endif
float readAngle() {
  // Read capture state on every callback, including calls from blocking
  // SimpleFOC initialization/alignment where loop() cannot refresh a cache.
  const auto reading = as5600::decode(pwm_input::snapshot(), micros());
  // SimpleFOC reserves negative sensor angles for invalid readings. Motor
  // operation will additionally need an independent feedback timeout shutdown.
  return reading.valid ? reading.angle_rad : -1.0f;
}
GenericSensor sensor(readAngle);
angle_target::Receiver targets;

void printControlStatus() {
#if defined(ENABLE_PIN_CONTROL)
  enable_output::report(console);
#else
  console.print("#CONTROL,1,DISABLED,");
  console.print(targets.requestId());
  console.print(',');
  console.println(targets.target());
#endif
}

void receiveTargets() {
  // Bound UART work so command bursts cannot starve sensor processing.
  for (uint8_t bytes = 0; bytes < 64 && console.available(); ++bytes) {
#if defined(ENABLE_PIN_CONTROL)
    const auto reading = as5600::decode(pwm_input::snapshot(), micros());
    enable_output::receive(static_cast<char>(console.read()), reading.valid, console);
    if (enable_output::poll(reading.valid)) printControlStatus();
#else
    const auto result = targets.feed(static_cast<char>(console.read()));
    if (result == angle_target::Result::Accepted) {
      console.print("#TARGET_ACK,");
      console.print(targets.replyId());
      console.print(",STAGED,");
      console.println(targets.target());
    } else if (result != angle_target::Result::None) {
      console.print("#TARGET_NACK,");
      console.print(targets.replyId());
      console.println(result == angle_target::Result::Conflict ? ",ID_CONFLICT" : ",MALFORMED");
    }
#endif
  }
}

} // namespace

// Also visible in an ST-Link debugger when no USB-UART adapter is available.
struct EncoderDebug {
  uint32_t valid;
  uint32_t high_us;
  uint32_t period_us;
  float frequency_hz;
  float angle_deg;
  float velocity_rad_s;
  uint32_t frames;
};
volatile EncoderDebug encoder_debug{};

void setup() {
  // No motor/driver objects. Only the explicit loopback build drives PA8.
  // Ordinary encoder builds never enable PB5. The dedicated enable build only
  // raises it after an explicit, bounded and acknowledged ENABLE command.
  digitalWrite(PB5, LOW);
  pinMode(PB5, OUTPUT);
  console.begin(115200);
  if (!pwm_input::begin()) {
    console.println("#ERROR,TIM2_CONFIG_FAILED");
  }
#if defined(ENABLE_PIN_CONTROL)
  enable_output::begin();
  console.println("#ENABLE_BENCH,PB5; max_on_ms=5000; phases PA8/PA9/PA10 static LOW");
#endif
#if defined(ENCODER_PWM_LOOPBACK)
  pwm_loopback::begin();
  console.println("#LOOPBACK,PA8->PA0,250Hz,high_us=2000,period_us=4000,angle_deg=179.96");
#endif
  console.println("AS5600 PWM / PA0 TIM2 hardware capture, filter 16us / SimpleFOC GenericSensor");
  console.println("status,angle_deg,velocity_rad_s,frequency_hz,high_us,period_us");
  printControlStatus();
}

void loop() {
  receiveTargets();
  static bool initialized = false;
  static uint32_t processed_sequence = 0;
  static uint32_t printed_ms = 0;
  const auto sample = pwm_input::snapshot();
  const auto reading = as5600::decode(sample, micros());
#if defined(ENABLE_PIN_CONTROL)
  if (enable_output::poll(reading.valid)) printControlStatus();
#endif

  if (!reading.valid) {
    // A disconnected sensor must not keep reporting its last angle as live.
    initialized = false;
    encoder_debug.valid = 0;
  } else if (sample.sequence != processed_sequence) {
    if (!initialized) {
      // Reset turn/velocity history after a lost signal: motion during the gap
      // is unknown. Subsequent readings use SimpleFOC's Sensor base class.
      sensor = GenericSensor(readAngle);
      sensor.init();
      initialized = true;
    }
    sensor.update();
    processed_sequence = sample.sequence;
    encoder_debug.valid = 1;
    encoder_debug.high_us = sample.high_us;
    encoder_debug.period_us = sample.period_us;
    encoder_debug.frequency_hz = reading.frequency_hz;
    encoder_debug.angle_deg = as5600::toDegrees(sensor.getMechanicalAngle());
    encoder_debug.velocity_rad_s = sensor.getVelocity();
    encoder_debug.frames = sample.sequence;
  }

  const uint32_t now_ms = millis();
  if (static_cast<uint32_t>(now_ms - printed_ms) < kPrintIntervalMs) {
    return;
  }
  printed_ms = now_ms;
#if defined(USBCON) && defined(USBD_USE_CDC)
  // Continue capturing even when no USB terminal is connected.
  if (!console) {
    return;
  }
#endif
  if (!reading.valid || !initialized) {
    console.print("NO_PWM_OR_INVALID,nan,nan,nan,");
  } else {
    console.print("OK,");
    console.print(encoder_debug.angle_deg, 2);
    console.print(',');
    console.print(encoder_debug.velocity_rad_s, 3);
    console.print(',');
    console.print(reading.frequency_hz, 1);
    console.print(',');
  }
  console.print(sample.high_us);
  console.print(',');
  console.println(sample.period_us);
  static uint32_t diagnostic_ms = 0;
  if (static_cast<uint32_t>(now_ms - diagnostic_ms) >= 1000) {
    diagnostic_ms = now_ms;
    console.print("#CAPTURE,frames=");
    console.print(sample.sequence);
    console.print(",overruns=");
    console.print(pwm_input::overruns());
    console.print(",complete=");
    console.print(sample.complete);
    console.print(",PA0=");
    console.println((GPIOA->IDR & GPIO_IDR_ID0) ? 1 : 0);
    printControlStatus();
  }
}
