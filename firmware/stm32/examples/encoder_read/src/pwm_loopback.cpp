#include "pwm_loopback.h"

#if defined(ENCODER_PWM_LOOPBACK)
#include <Arduino.h>
#include <HardwareTimer.h>

namespace {
HardwareTimer source(TIM1);
}

namespace pwm_loopback {
void begin() {
  // Keep the test source independent of the TIM2 receiver and main loop timing.
  source.pause();
  source.setMode(1, TIMER_OUTPUT_COMPARE_PWM1, PA8);
  source.setOverflow(250, HERTZ_FORMAT);
  source.setCaptureCompare(1, 50, PERCENT_COMPARE_FORMAT);
  source.refresh();
  source.resume();
}
}
#endif
