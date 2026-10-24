#if defined(DUAL_ENCODER_DIAGNOSTIC) || defined(CLOSED_LOOP_CONTROL)
#include <Arduino.h>
#include <HardwareTimer.h>
#include "pwm_input_secondary.h"

namespace {
HardwareTimer timer(TIM4);
as5600::TimerCapture capture;

void onRisingCapture() {
  auto* registers = timer.getHandle()->Instance;
  const uint32_t flags = registers->SR;
  const bool overrun = (flags & (TIM_FLAG_CC1OF | TIM_FLAG_CC2OF)) != 0;
  const uint32_t period = registers->CCR2;
  const uint32_t high = registers->CCR1;
  __HAL_TIM_CLEAR_FLAG(timer.getHandle(), TIM_FLAG_CC1 | TIM_FLAG_CC1OF | TIM_FLAG_CC2OF);
  capture.frame(high, period, micros(), (flags & TIM_FLAG_CC1) != 0,
                overrun, pwm_input_secondary::kCounterHz);
}
} // namespace

namespace pwm_input_secondary {
bool begin() {
  timer.pause();
  const uint32_t clock_hz = timer.getTimerClkFreq();
  if (clock_hz < kCounterHz || clock_hz % kCounterHz != 0) return false;
  timer.setPrescaleFactor(clock_hz / kCounterHz);
  timer.setOverflow(65536U, TICK_FORMAT);
  // PB7_ALT1 selects TIM4_CH2 rather than the pin map's default TIM3_CH4.
  timer.setMode(2, TIMER_INPUT_CAPTURE_RISING, PB7_ALT1, FILTER_DTS2_N8);
  timer.setMode(1, TIMER_INPUT_CAPTURE_FALLING);
  auto* handle = timer.getHandle();
  TIM_IC_InitTypeDef falling{};
  falling.ICPolarity = TIM_INPUTCHANNELPOLARITY_FALLING;
  falling.ICSelection = TIM_ICSELECTION_INDIRECTTI; // CH1 reads PB7 / TI2 too.
  falling.ICPrescaler = TIM_ICPSC_DIV1;
  falling.ICFilter = FILTER_DTS2_N8;
  TIM_SlaveConfigTypeDef reset{};
  reset.SlaveMode = TIM_SLAVEMODE_RESET;
  reset.InputTrigger = TIM_TS_TI2FP2;
  reset.TriggerPolarity = TIM_INPUTCHANNELPOLARITY_RISING;
  reset.TriggerPrescaler = TIM_ICPSC_DIV1;
  reset.TriggerFilter = FILTER_DTS2_N8;
  if (HAL_TIM_IC_ConfigChannel(handle, &falling, TIM_CHANNEL_1) != HAL_OK ||
      HAL_TIM_SlaveConfigSynchro(handle, &reset) != HAL_OK) return false;
  MODIFY_REG(GPIOB->PUPDR, GPIO_PUPDR_PUPD7_Msk, 0);
  timer.refresh();
  __HAL_TIM_CLEAR_FLAG(handle, TIM_FLAG_UPDATE | TIM_FLAG_CC1 | TIM_FLAG_CC2 |
                               TIM_FLAG_CC1OF | TIM_FLAG_CC2OF);
  timer.attachInterrupt(2, onRisingCapture);
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
} // namespace pwm_input_secondary
#endif
