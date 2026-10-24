#pragma once
#if defined(CLOSED_LOOP_CONTROL)
#include <Arduino.h>
#include <SimpleFOC.h>
#include "closed_loop.h"
#include "pwm_input.h"

namespace closed_hardware {
struct MotorPins {
  uint8_t id;
  uint32_t phase_a,phase_b,phase_c,enable,fault;
  bool (*capture_begin)();
  as5600::PwmSample (*capture_snapshot)();
};
MotorPins primaryPins();
MotorPins secondaryPins();

// One physical watchdog owns the board; initialize both drivers before arming
// its short runtime deadline. Each motor retains its own fault/enable state.
class BoardWatchdog {
 public:
  bool begin();
  bool arm();
  void poll();
 private:
  bool configure(uint32_t prescaler,uint32_t reload);
  IWDG_HandleTypeDef handle_{};
  bool active_=false;
};

class PwmSensor final : public Sensor {
 public:
  explicit PwmSensor(as5600::PwmSample (*snapshot)()=pwm_input::snapshot):snapshot_(snapshot){}
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
  as5600::PwmSample (*snapshot_)();
  closed_loop::AngleTracker tracker_;
  as5600::PwmSample sample_{};
  as5600::Reading reading_{};
  bool valid_=false;
};

// Owns one configured EN exclusively. Driver has no EN pin, so SimpleFOC
// cannot enable the bridge implicitly during startup or initFOC().
class MotorHardware {
 public:
  explicit MotorHardware(MotorPins pins=primaryPins()): pins_(pins),
      driver_(pins.phase_a,pins.phase_b,pins.phase_c),motor_(7),sensor_(pins.capture_snapshot){}
  bool begin();
  void poll();
  bool enable();
  bool calibrationReady() const;
  bool recoverForCalibration();
  void stop();
  bool enabled()const{return enabled_;}
  bool pinHighReadback()const{return pinHigh();}
  bool faulted()const{return fault_;}
  PwmSensor& sensor(){return sensor_;}
  BLDCMotor& motor(){return motor_;}
 private:
  bool pinHigh()const{return digitalRead(pins_.enable)==HIGH;}
  MotorPins pins_;
  BLDCDriver3PWM driver_;
  BLDCMotor motor_;
  PwmSensor sensor_;
  bool driver_ready_=false,initialized_=false,enabled_=false,fault_=false;
};
} // namespace closed_hardware
#endif
