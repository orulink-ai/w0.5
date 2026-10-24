#pragma once
#include <cstdint>

namespace closed_loop {
namespace tuning {
// Initial low-inertia GB2806 candidate. These values require hardware tuning;
// voltage torque mode provides no measured phase-current regulation.
constexpr float kVelocityP = 0.20f;
constexpr float kVelocityI = 0.5f;
constexpr float kVelocityD = 0.0f;
constexpr float kVelocityFilterSeconds = 0.002f;

// First-axis baseline. Second-axis hardware tuning is selected independently.
constexpr float kVelocityVoltageRamp = 10.0f;
constexpr float kAngleP = 8.0f;
struct ControllerConfig {
  float velocity_p;
  float velocity_i;
  float velocity_d;
  float velocity_filter_seconds;
  float voltage_ramp;
  float angle_p;
};
constexpr ControllerConfig controllerFor(uint8_t motor_id) {
  // Axis 2 bench tuning: remove the slew-induced limit cycle, then reduce
  // proportional gain to suppress the remaining faster oscillation.
  // Axis 1 and both voltage/overspeed limits retain their existing values.
  return {motor_id==2?0.10f:kVelocityP,kVelocityI,kVelocityD,kVelocityFilterSeconds,
          motor_id==2?100.0f:kVelocityVoltageRamp,kAngleP};
}
constexpr float kMinSpeedRpm = 0.1f;
constexpr float kMaxSpeedRpm = 10.0f;
constexpr float rpmToRadiansPerSecond(float rpm) {
  return rpm * 6.28318530718f / 60;
}
constexpr float kMinSpeedRadS = rpmToRadiansPerSecond(kMinSpeedRpm);
constexpr float kMaxSpeedRadS = rpmToRadiansPerSecond(kMaxSpeedRpm);
constexpr float kVelocityLimitRadS = kMaxSpeedRadS;
constexpr float kOverspeedSoftRpm = 60.0f;
constexpr float kOverspeedHardRpm = 120.0f;
constexpr float kOverspeedSoftRadS = rpmToRadiansPerSecond(kOverspeedSoftRpm);
constexpr float kOverspeedHardRadS = rpmToRadiansPerSecond(kOverspeedHardRpm);
constexpr uint32_t kOverspeedHoldMs = 100;
constexpr float kMotorVoltageLimit = 6.0f;
} // namespace tuning
} // namespace closed_loop
