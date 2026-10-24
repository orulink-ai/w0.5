#pragma once
#if defined(CLOSED_LOOP_CONTROL)
#include <Arduino.h>
#include <SimpleFOC.h>
#include "closed_loop.h"
#include "pwm_input.h"

namespace closed_hardware {
class PwmSensor final : public Sensor {
 public:
  void update() override;
  float getMechanicalAngle() override {return tracker_.mechanical();}
  float getAngle() override {return tracker_.angle();}
  double getPreciseAngle() override {return tracker_.angle();}
  // SimpleFOC closes its speed loop on the responsive estimate. The slow
  // measurement channel remains explicit for telemetry and the run guard.
  float getVelocity() override {return tracker_.controlVelocity();}
  float measurementVelocity() const {return tracker_.velocity();}
  float fastVelocity() const {return tracker_.fastVelocity();}
  bool valid() const {return valid_;}
  const as5600::PwmSample& sample()const{return sample_;}
  const as5600::Reading& reading()const{return reading_;}
 protected:
  float getSensorAngle() override {return getMechanicalAngle();}
 private:
  closed_loop::AngleTracker tracker_;
  as5600::PwmSample sample_{};
  as5600::Reading reading_{};
  bool valid_=false;
};

// Owns PB5 exclusively. Driver intentionally has no EN pin, so SimpleFOC
// cannot enable the bridge implicitly during startup or initFOC().
class MotorHardware {
 public:
  MotorHardware(): driver_(PA8,PA9,PA10),motor_(7){}
  bool begin();
  void poll();
  bool enable();
  void stop();
  bool enabled()const{return enabled_;}
  bool pinHighReadback()const{return pinHigh();}
  bool faulted()const{return fault_;}
  PwmSensor& sensor(){return sensor_;}
  BLDCMotor& motor(){return motor_;}
 private:
  bool watchdog(uint32_t prescaler,uint32_t reload);
  bool pinHigh()const{return (GPIOB->IDR&GPIO_IDR_ID5)!=0;}
  BLDCDriver3PWM driver_;
  BLDCMotor motor_;
  PwmSensor sensor_;
  IWDG_HandleTypeDef watchdog_{};
  bool driver_ready_=false,initialized_=false,watchdog_ready_=false,enabled_=false,fault_=false;
};
} // namespace closed_hardware
#endif
