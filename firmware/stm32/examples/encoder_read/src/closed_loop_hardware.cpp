#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_hardware.h"
#include "closed_loop_tuning.h"
namespace closed_hardware {
void PwmSensor::update() {
  sample_=pwm_input::snapshot();
  reading_=as5600::decode(sample_,micros());
  valid_=reading_.valid;
  if(valid_) tracker_.push(reading_.angle_rad,sample_.sequence,sample_.captured_us);
}
bool MotorHardware::watchdog(uint32_t prescaler,uint32_t reload) {
  RCC_OscInitTypeDef clock{};
  clock.OscillatorType=RCC_OSCILLATORTYPE_LSI;
  clock.LSIState=RCC_LSI_ON; clock.PLL.PLLState=RCC_PLL_NONE;
  if(HAL_RCC_OscConfig(&clock)!=HAL_OK) return false;
  watchdog_.Instance=IWDG;watchdog_.Init.Prescaler=prescaler;
  watchdog_.Init.Reload=reload;watchdog_.Init.Window=IWDG_WINDOW_DISABLE;
  return HAL_IWDG_Init(&watchdog_)==HAL_OK;
}
bool MotorHardware::begin() {
  digitalWrite(PB5,LOW);pinMode(PB5,OUTPUT);
  for(const auto pin:{PA8,PA9,PA10}){digitalWrite(pin,LOW);pinMode(pin,OUTPUT);}
  pinMode(PB4,INPUT_PULLUP);
  const bool reset_fault=__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST);
  __HAL_RCC_CLEAR_RESET_FLAGS();
  // SimpleFOC init has a blocking 1s startup, exclusively with bridge disabled.
  const bool startup_watchdog=watchdog(IWDG_PRESCALER_256,4095);
  const bool capture_ready=pwm_input::begin();
  driver_.voltage_power_supply=12;driver_.voltage_limit=12;driver_.pwm_frequency=25000;
  if(startup_watchdog&&capture_ready&&!reset_fault&&(driver_ready_=driver_.init())) {
    motor_.linkDriver(&driver_);motor_.linkSensor(&sensor_);
    motor_.torque_controller=TorqueControlType::voltage;
    motor_.controller=MotionControlType::angle;
    motor_.voltage_limit=closed_loop::tuning::kMotorVoltageLimit;motor_.voltage_sensor_align=1;
    motor_.velocity_limit=closed_loop::tuning::kVelocityLimitRadS;
    motor_.PID_velocity.P=closed_loop::tuning::kVelocityP;
    motor_.PID_velocity.I=closed_loop::tuning::kVelocityI;
    motor_.PID_velocity.D=closed_loop::tuning::kVelocityD;
    motor_.PID_velocity.output_ramp=closed_loop::tuning::kVelocityVoltageRamp;
    motor_.LPF_velocity.Tf=closed_loop::tuning::kVelocityFilterSeconds;
    motor_.P_angle.P=closed_loop::tuning::kAngleP;
    initialized_=motor_.init();
  }
  stop();
  watchdog_ready_=watchdog(IWDG_PRESCALER_32,99);
  fault_=!initialized_||!watchdog_ready_||reset_fault;
  return !fault_;
}
void MotorHardware::poll() {
  if(watchdog_ready_) HAL_IWDG_Refresh(&watchdog_);
  sensor_.update();
  if(digitalRead(PB4)==LOW || (enabled_&&!sensor_.valid()) || pinHigh()!=enabled_) {
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
  digitalWrite(PB5,HIGH);__DSB();
  enabled_=pinHigh();
  if(!enabled_){fault_=true;stop();}
  return enabled_;
}
void MotorHardware::stop() {
  digitalWrite(PB5,LOW);__DSB();enabled_=false;
  if(initialized_)motor_.disable();
  if(driver_ready_)driver_.setPwm(0,0,0);
  if(pinHigh())fault_=true;
}
} // namespace closed_hardware
#endif
