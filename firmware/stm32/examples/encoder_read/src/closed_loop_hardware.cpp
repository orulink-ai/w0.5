#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_hardware.h"
#include "closed_loop_tuning.h"
#include "pwm_input_secondary.h"
#include <drivers/hardware_specific/stm32/stm32_mcu.h>
namespace closed_hardware {
MotorPins primaryPins(){return {1,PA8,PA9,PA10,PB5,PB4,pwm_input::begin,pwm_input::snapshot};}
MotorPins secondaryPins(){return {2,PA6,PA7,PB0,PB12,PB13,pwm_input_secondary::begin,pwm_input_secondary::snapshot};}
void PwmSensor::update() {
  sample_=snapshot_();
  reading_=as5600::decode(sample_,micros());
  valid_=reading_.valid;
  if(valid_) tracker_.push(reading_.angle_rad,sample_.sequence,sample_.captured_us);
}
bool BoardWatchdog::configure(uint32_t prescaler,uint32_t reload) {
  RCC_OscInitTypeDef clock{};
  clock.OscillatorType=RCC_OSCILLATORTYPE_LSI;
  clock.LSIState=RCC_LSI_ON; clock.PLL.PLLState=RCC_PLL_NONE;
  if(HAL_RCC_OscConfig(&clock)!=HAL_OK) return false;
  handle_.Instance=IWDG;handle_.Init.Prescaler=prescaler;
  handle_.Init.Reload=reload;handle_.Init.Window=IWDG_WINDOW_DISABLE;
  active_=HAL_IWDG_Init(&handle_)==HAL_OK;
  return active_;
}
bool BoardWatchdog::begin() {
  const bool reset_fault=__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST);
  __HAL_RCC_CLEAR_RESET_FLAGS();
  return configure(IWDG_PRESCALER_256,4095)&&!reset_fault;
}
bool BoardWatchdog::arm(){return configure(IWDG_PRESCALER_32,99);}
void BoardWatchdog::poll(){if(active_)HAL_IWDG_Refresh(&handle_);}

namespace {
bool expectedTimer(const BLDCDriver3PWM& driver,uint8_t motor) {
  const auto* params=static_cast<const STM32DriverParams*>(driver.params);
  auto* expected=motor==1?TIM1:TIM3;
  if(!params||params->num_timers!=1)return false;
  for(unsigned index=0;index<3;++index) {
    if(!params->timers_handle[index]||params->timers_handle[index]->Instance!=expected||
       params->channels[index]!=index+1)return false;
  }
  return true;
}
}
bool MotorHardware::begin() {
  digitalWrite(pins_.enable,LOW);pinMode(pins_.enable,OUTPUT);
  for(const auto pin:{pins_.phase_a,pins_.phase_b,pins_.phase_c}){digitalWrite(pin,LOW);pinMode(pin,OUTPUT);}
  pinMode(pins_.fault,INPUT_PULLUP);
  // SimpleFOC init has a blocking 1s startup, exclusively with bridge disabled.
  const bool capture_ready=pins_.capture_begin();
  // Input capture timers cannot be selected by SimpleFOC's PWM pin search.
  if(!stm32_isTimerReserved(TIM2))stm32_reserveTimer(TIM2);
  if(!stm32_isTimerReserved(TIM4))stm32_reserveTimer(TIM4);
  driver_.voltage_power_supply=12;driver_.voltage_limit=12;driver_.pwm_frequency=25000;
  if(capture_ready&&(driver_ready_=driver_.init())&&expectedTimer(driver_,pins_.id)) {
    motor_.linkDriver(&driver_);motor_.linkSensor(&sensor_);
    motor_.torque_controller=TorqueControlType::voltage;
    motor_.controller=MotionControlType::angle;
    motor_.voltage_limit=closed_loop::tuning::kMotorVoltageLimit;motor_.voltage_sensor_align=1;
    motor_.velocity_limit=closed_loop::tuning::kVelocityLimitRadS;
    const auto control=closed_loop::tuning::controllerFor(pins_.id);
    motor_.PID_velocity.P=control.velocity_p;
    motor_.PID_velocity.I=control.velocity_i;
    motor_.PID_velocity.D=control.velocity_d;
    motor_.PID_velocity.output_ramp=control.voltage_ramp;
    motor_.LPF_velocity.Tf=control.velocity_filter_seconds;
    motor_.P_angle.P=control.angle_p;
    initialized_=motor_.init();
  }
  stop();
  fault_=!initialized_;
  return !fault_;
}
void MotorHardware::poll() {
  sensor_.update();
  if(digitalRead(pins_.fault)==LOW || (enabled_&&!sensor_.valid()) || pinHigh()!=enabled_) {
    fault_=true;stop();
  }
}
bool MotorHardware::enable() {
  if(fault_||!initialized_||!sensor_.valid()||enabled_)return false;
  // Zero phase vector before EN. Calibration/application supplies the next
  // bounded vector only after this explicit transition.
  motor_.enable();
  motor_.current_sp=0;motor_.voltage.q=0;motor_.voltage.d=0;
  driver_.setPwm(0,0,0);
  digitalWrite(pins_.enable,HIGH);__DSB();
  enabled_=pinHigh();
  if(!enabled_){fault_=true;stop();}
  return enabled_;
}
bool MotorHardware::calibrationReady() const {
  return initialized_&&driver_ready_&&!enabled_&&!pinHigh()&&sensor_.valid()&&
      digitalRead(pins_.fault)==HIGH;
}
bool MotorHardware::recoverForCalibration() {
  if(!calibrationReady())return false;
  fault_=false; // Clear only a recovered runtime latch, never initialization.
  return true;
}
void MotorHardware::stop() {
  digitalWrite(pins_.enable,LOW);__DSB();enabled_=false;
  if(initialized_)motor_.disable();
  if(driver_ready_)driver_.setPwm(0,0,0);
  if(pinHigh())fault_=true;
}
} // namespace closed_hardware
#endif
