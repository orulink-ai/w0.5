#pragma once

#include "as5600_pwm.h"

namespace pwm_input {
// PA0 / TIM2_CH1. Uses an 8 MHz timer and paired hardware input capture.
constexpr uint32_t kCounterHz = 8000000U;
bool begin();
as5600::PwmSample snapshot();
uint32_t overruns();
} // namespace pwm_input
