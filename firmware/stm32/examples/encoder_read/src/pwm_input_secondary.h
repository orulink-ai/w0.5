#pragma once
#include "as5600_pwm.h"

namespace pwm_input_secondary {
// TIM4 is 16 bit. 4 MHz keeps the full 115..920 Hz AS5600 range within ARR.
constexpr uint32_t kCounterHz = 4000000U;
bool begin();
as5600::PwmSample snapshot();
} // namespace pwm_input_secondary
