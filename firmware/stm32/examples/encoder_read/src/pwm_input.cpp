#include <Arduino.h>
#include <HardwareTimer.h>
#include "pwm_input.h"

namespace {
HardwareTimer timer(TIM2);
as5600::TimerCapture capture;
volatile uint32_t overrun_count = 0;

void onRisingCapture() {
  auto* handle = timer.getHandle();
  const uint32_t flags = handle->Instance->SR;
  const uint32_t period = handle->Instance->CCR1;
  const uint32_t high = handle->Instance->CCR2;
  const bool overrun = (flags & (TIM_FLAG_CC1OF | TIM_FLAG_CC2OF)) != 0;
  if (overrun) {
    ++overrun_count;
  }
  // CH2 has no interrupt: its flag records whether the previous frame had a fall.
  __HAL_TIM_CLEAR_FLAG(handle, TIM_FLAG_CC2 | TIM_FLAG_CC1OF | TIM_FLAG_CC2OF);
  capture.frame(high, period, micros(), (flags & TIM_FLAG_CC2) != 0, overrun,
                pwm_input::kCounterHz);
}
} // namespace

namespace pwm_input {
bool begin() {
  timer.pause();
  const uint32_t clock_hz = timer.getTimerClkFreq();
  if (clock_hz < kCounterHz || clock_hz % kCounterHz != 0) {
    return false;
  }
  timer.setPrescaleFactor(clock_hz / kCounterHz);
  // TIM2 is 32 bit. A long timeout must not wrap into a plausible PWM period.
  timer.setOverflow(0xFFFFFFFFU, TICK_FORMAT);
  // At HSI16 / CKD_DIV1: sample at 8 MHz and require eight equal samples
  // (~1 us qualification). The old fDTS/32 filter quantized edges to 2 us,
  // defeating the finer counter. Both edges and reset need the same filter.
  timer.setMode(1, TIMER_INPUT_CAPTURE_RISING, PA0, FILTER_DTS2_N8);
  timer.setMode(2, TIMER_INPUT_CAPTURE_FALLING);
  auto* handle = timer.getHandle();
  TIM_IC_InitTypeDef falling{};
  falling.ICPolarity = TIM_INPUTCHANNELPOLARITY_FALLING;
  falling.ICSelection = TIM_ICSELECTION_INDIRECTTI; // CH2 captures PA0 / TI1 too.
  falling.ICPrescaler = TIM_ICPSC_DIV1;
  falling.ICFilter = FILTER_DTS2_N8;
  TIM_SlaveConfigTypeDef reset{};
  reset.SlaveMode = TIM_SLAVEMODE_RESET;
  reset.InputTrigger = TIM_TS_TI1FP1;
  reset.TriggerPolarity = TIM_INPUTCHANNELPOLARITY_RISING;
  reset.TriggerPrescaler = TIM_ICPSC_DIV1;
  reset.TriggerFilter = FILTER_DTS2_N8;
  if (HAL_TIM_IC_ConfigChannel(handle, &falling, TIM_CHANNEL_2) != HAL_OK ||
      HAL_TIM_SlaveConfigSynchro(handle, &reset) != HAL_OK) {
    return false;
  }
  // Keep the AF1 configuration but remove the pin-map's implicit pull resistor.
  MODIFY_REG(GPIOA->PUPDR, GPIO_PUPDR_PUPD0_Msk, 0);
  timer.refresh();
  __HAL_TIM_CLEAR_FLAG(handle, TIM_FLAG_UPDATE | TIM_FLAG_CC1 | TIM_FLAG_CC2 |
                               TIM_FLAG_CC1OF | TIM_FLAG_CC2OF);
  timer.attachInterrupt(1, onRisingCapture);
  timer.resume();
  return true;
}

as5600::PwmSample snapshot() {
  const uint32_t mask = __get_PRIMASK();
  __disable_irq();
  const auto result = capture.sample();
  __set_PRIMASK(mask);
  return result;
}

uint32_t overruns() { return overrun_count; }
} // namespace pwm_input
