#pragma once

namespace closed_loop {
namespace tuning {
// Initial low-inertia GB2806 candidate. These values require hardware tuning;
// voltage torque mode provides no measured phase-current regulation.
constexpr float kVelocityP = 0.20f;
constexpr float kVelocityI = 0.5f;
constexpr float kVelocityD = 0.0f;
constexpr float kVelocityFilterSeconds = 0.002f;

// Kept unchanged while evaluating the velocity feedback/gain candidate.
constexpr float kVelocityVoltageRamp = 10.0f;
constexpr float kAngleP = 8.0f;
constexpr float kMinSpeedRpm = 0.1f;
constexpr float kMaxSpeedRpm = 10.0f;
constexpr float rpmToRadiansPerSecond(float rpm) {
  return rpm * 6.28318530718f / 60;
}
constexpr float kMinSpeedRadS = rpmToRadiansPerSecond(kMinSpeedRpm);
constexpr float kMaxSpeedRadS = rpmToRadiansPerSecond(kMaxSpeedRpm);
constexpr float kVelocityLimitRadS = kMaxSpeedRadS;
constexpr float kMotorVoltageLimit = 6.0f;
} // namespace tuning
} // namespace closed_loop
