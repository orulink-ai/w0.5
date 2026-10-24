#pragma once

#if defined(ENCODER_PWM_LOOPBACK)
namespace pwm_loopback {
// Bench only: PA8 must be isolated from the motor driver and encoder OUT.
void begin();
}
#endif
