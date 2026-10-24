#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include "position_control.h"
#include "closed_loop_tuning.h"
#include "overspeed_guard.h"

namespace closed_loop {
constexpr float kTwoPi = 6.28318530718f;
constexpr float kHalfPi = kTwoPi / 4;
inline float normalize(float a) { a=std::fmod(a,kTwoPi); return a<0?a+kTwoPi:a; }
inline float clamp(float a,float lo,float hi) { return std::max(lo,std::min(a,hi)); }

// Only new capture frames change the tracker; encoder PWM is slower than FOC.
class AngleTracker {
 public:
  void push(float mechanical,uint32_t sequence,uint32_t captured_us) {
    if (!std::isfinite(mechanical) || (ready_ && sequence==sequence_)) return;
    if (!ready_) { angle_=mechanical; previous_=mechanical; velocity_angle_=angle_; velocity_us_=captured_us; fast_angle_=angle_; fast_us_=captured_us; ready_=true; }
    else {
      float delta=mechanical-previous_;
      if (delta>kTwoPi/2) delta-=kTwoPi;
      if (delta<-kTwoPi/2) delta+=kTwoPi;
      angle_+=delta; previous_=mechanical;
      // Separate damping estimate. Keep the slower telemetry/overspeed path
      // intact; the controller needs less phase delay on a low-inertia rotor.
      const uint32_t fast_elapsed=captured_us-fast_us_;
      if(fast_elapsed>=4000) {
        const float raw=(angle_-fast_angle_)*1e6f/fast_elapsed;
        fast_velocity_+=.6f*(raw-fast_velocity_);
        fast_angle_=angle_;fast_us_=captured_us;
      }
      const uint32_t elapsed=captured_us-velocity_us_;
      if(elapsed>=20000) {
        const float raw=(angle_-velocity_angle_)*1e6f/elapsed;
        velocity_+=.4f*(raw-velocity_);
        velocity_angle_=angle_; velocity_us_=captured_us;
      }
    }
    sequence_=sequence;
  }
  float angle() const {return angle_;}
  float mechanical() const {return normalize(angle_);}
  float velocity() const {return velocity_;}
  float controlVelocity() const {return fast_velocity_;}
  float fastVelocity() const {return controlVelocity();}
 private:
  bool ready_=false;
  uint32_t sequence_=0,velocity_us_=0,fast_us_=0;
  float angle_=0,previous_=0,velocity_=0,velocity_angle_=0;
  float fast_velocity_=0,fast_angle_=0;
};

enum class FeedbackFault { None, SensorInvalid, Hardware, Overspeed };
enum class Mode { Position, Velocity };
struct Output { Mode mode=Mode::Position; float target=0; bool stop=false; bool fault=false; float velocity_feedforward=0; };

class Policy {
 public:
  bool calibrated() const { return direction_ != 0; }
  bool running() const { return running_; }
  bool faulted() const { return fault_; }
  bool overspeedEnabled() const { return overspeed_enabled_; }
  bool setOverspeedEnabled(bool enabled) {
    if (running_ || (fault_ && feedback_fault_ != FeedbackFault::Overspeed)) return false;
    overspeed_enabled_ = enabled;
    overspeed_guard_.reset();
    return true;
  }
  FeedbackFault feedbackFault() const { return feedback_fault_; }
  Mode mode() const { return mode_; }
  float relative(float raw) const { return direction_ * raw - zero_; }
  float lower() const { return lower_; }
  float upper() const { return upper_; }
  float requestedTarget() const { return requested_; }
  float positionSpeed() const { return position_speed_; }
  float plannedRelative() const { return reference_.current(); }
  float zeroRaw() const { return calibrated() ? zero_ / direction_ : 0; }
  void setCalibrated(int direction) {
    direction_ = direction == -1 || direction == 1 ? direction : 0;
    stop();
  }
  void invalidate() { direction_ = 0; stop(); }
  bool zero(float raw) {
    if (running_ || !calibrated() || !std::isfinite(raw)) return false;
    zero_ = direction_ * raw;
    zero_ready_ = true;
    return true;
  }
  bool setLimits(float lo, float hi) {
    if (running_ || !std::isfinite(lo) || !std::isfinite(hi) || lo >= hi ||
        lo > 0 || hi < 0 || lo < -kTwoPi/2 || hi > kTwoPi/2 || hi-lo < kTwoPi/36) return false;
    lower_ = lo; upper_ = hi;
    return true;
  }
  bool insideLimits(float raw) const {
    const float position = relative(raw);
    return std::isfinite(raw) && position >= lower_ && position <= upper_;
  }
  bool startPosition(float target, float speed_rad_s,
                     uint32_t now, bool valid, float current_raw) {
    if (!ready(valid, current_raw) || !std::isfinite(target) || target < lower_ ||
        target > upper_ || !std::isfinite(speed_rad_s) || speed_rad_s < tuning::kMinSpeedRadS ||
        speed_rad_s > tuning::kMaxSpeedRadS) return false;
    if (!reference_.start(relative(current_raw), target, speed_rad_s, now)) return false;
    mode_ = Mode::Position; requested_ = target;
    position_speed_ = speed_rad_s;
    overspeed_guard_.reset();
    running_ = true;
    return true;
  }
  bool retargetPosition(float target, uint32_t now) {
    if(!running_||fault_||mode_!=Mode::Position||!std::isfinite(target)||
       target<lower_||target>upper_)return false;
    if(!reference_.retarget(target,now))return false;
    requested_=target;
    return true;
  }
  bool startVelocity(float velocity_rad_s, uint32_t, bool valid, float current_raw) {
    if (!ready(valid, current_raw) || !std::isfinite(velocity_rad_s) ||
        std::fabs(velocity_rad_s) > tuning::kMaxSpeedRadS || std::fabs(velocity_rad_s) < tuning::kMinSpeedRadS) return false;
    mode_ = Mode::Velocity; velocity_ = velocity_rad_s;
    requested_ = relative(current_raw); overspeed_guard_.reset(); running_ = true;
    return true;
  }
  void stop() { running_ = false; overspeed_guard_.reset(); }
  void fail() { stop(); fault_ = true; }
  // A manual acknowledgement clears only the overspeed latch. Calibration and
  // origin survive, but the previous move never resumes without a new START.
  bool resetOverspeed(bool sensor_valid, float raw_velocity) {
    if (running_ || !fault_ || feedback_fault_ != FeedbackFault::Overspeed ||
        !sensor_valid || !std::isfinite(raw_velocity) || std::fabs(raw_velocity) > .2f) return false;
    fault_ = false;
    feedback_fault_ = FeedbackFault::None;
    return true;
  }
  // Only the application's explicit CALIBRATE path may call this, after live
  // hardware checks. Clearing the latch invalidates old calibration and never
  // starts a position/velocity move or resumes an earlier target.
  bool resetForCalibration() {
    if(running_)return false;
    stop();fault_=false;feedback_fault_=FeedbackFault::None;
    direction_=0;zero_ready_=false;
    return true;
  }
  void tick(uint32_t now, bool sensor_valid, bool hardware_fault, float raw_velocity=0) {
    if (hardware_fault) { feedback_fault_=FeedbackFault::Hardware; fail(); }
    if (running_ && (!sensor_valid || !std::isfinite(raw_velocity))) {
      feedback_fault_=FeedbackFault::SensorInvalid; fail();
    }
    if (overspeed_guard_.update(now,raw_velocity,running_&&overspeed_enabled_)) {
      feedback_fault_=FeedbackFault::Overspeed; fail();
    }
  }
  Output output(float raw, float fast_velocity, uint32_t now) {
    if (!running_) return {mode_, 0, true};
    const float position = relative(raw);
    if (!std::isfinite(position) || !std::isfinite(fast_velocity)) {
      feedback_fault_=FeedbackFault::SensorInvalid; fail();
      return {mode_, 0, true, true};
    }
    if (position < lower_-.035f || position > upper_+.035f) {
      fail(); return {mode_, 0, true, true};
    }
    if (mode_ == Mode::Velocity) {
      if ((velocity_<0 && position<=lower_+.035f) ||
          (velocity_>0 && position>=upper_-.035f)) {
        stop(); return {mode_, 0, true};
      }
      return {mode_, velocity_, false};
    }
    const float reference = reference_.update(now);
    return {mode_, zero_ + reference, false, false, reference_.velocity()};
  }
 private:
  bool ready(bool valid, float current_raw) const {
    return !running_ && !fault_ && calibrated() && zero_ready_ && valid && insideLimits(current_raw);
  }
  RateLimitedReference reference_;
  OverspeedGuard overspeed_guard_;
  FeedbackFault feedback_fault_=FeedbackFault::None;
  int direction_=0;
  bool running_=false, fault_=false, zero_ready_=false;
  bool overspeed_enabled_=true; // Per-boot setting, never restored from browser state.
  float zero_=0, lower_=-kHalfPi, upper_=kHalfPi;
  float requested_=0, velocity_=0, position_speed_=.1f;
  Mode mode_=Mode::Position;
};

// Cooperative equivalent of SimpleFOC2.4 alignSensor: q-axis at 3PI/2,
// one electrical revolution each direction, then hold to establish zero.
// All durations use elapsed time, never delay(); STOP can abort each tick.
struct AlignmentOutput {bool energize=false; float electrical_angle=0;};
class Alignment {
 public:
  bool start(uint32_t now,float raw) {
    if(active_) return false;
    started_=now; mid_=end_=raw; active_=true;done_=failed_=false;direction_=0;phase_=0;return true;
  }
  void abort() {active_=false;failed_=true;}
  void tick(uint32_t now,float raw) {
    if(!active_) return;
    const uint32_t t=now-started_;
    if(t>=4000) {abort();return;}
    if(phase_==0&&t>=1000) {mid_=raw;phase_=1;}
    if(phase_==1&&t>=2002) {end_=raw;phase_=2;}
    if(phase_==2&&t>=2202) {
      const float moved=mid_-end_;
      // Reject stalled rotor and wrong pp rather than accepting a guess.
      if(std::fabs(std::fabs(moved)*7-kTwoPi)>.8f) {abort();return;}
      direction_=moved>0?1:-1;phase_=3;
    }
    if(phase_==3&&t>=2902) {
      zero_=normalize(direction_*7*normalize(raw));
      active_=false;done_=true;
    }
  }
  AlignmentOutput output(uint32_t now=0) const {
    if(!active_) return {};
    const uint32_t t=now-started_;
    float fraction=0;
    if(t<=1000) fraction=t/1000.f;
    else if(t<=2002) fraction=(2002-t)/1000.f;
    return {true,3*kHalfPi+kTwoPi*fraction};
  }
  bool active()const{return active_;}
  bool done()const{return done_;}
  bool failed()const{return failed_;}
  int direction()const{return direction_;}
  float zeroElectrical()const{return zero_;}
 private:
  bool active_=false,done_=false,failed_=false;
  unsigned phase_=0;int direction_=0;uint32_t started_=0;
  float mid_=0,end_=0,zero_=0;
};
} // namespace closed_loop
