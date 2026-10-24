#pragma once

#include "as5600_pwm.h"

namespace pwm_input {
// PA0 / TIM2_CH1. Uses a 1 MHz timer and paired hardware input capture.
bool begin();
as5600::PwmSample snapshot();
uint32_t overruns();
} // namespace pwm_input
