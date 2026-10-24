#pragma once

namespace closed_loop {
namespace tuning {
// Initial low-inertia GB2806 candidate. These values require hardware tuning;
// voltage torque mode provides no measured phase-current regulation.
constexpr float kVelocityP = 0.08f;
constexpr float kVelocityI = 1.0f;
constexpr float kVelocityD = 0.0f;
constexpr float kVelocityFilterSeconds = 0.002f;

// Kept unchanged while evaluating the velocity feedback/gain candidate.
constexpr float kVelocityVoltageRamp = 10.0f;
constexpr float kAngleP = 3.0f;
constexpr float kVelocityLimitRadS = 0.5f;
constexpr float kMotorVoltageLimit = 1.0f;
} // namespace tuning
} // namespace closed_loop
