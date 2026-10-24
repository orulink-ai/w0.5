#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_app.h"
#include "closed_loop_tuning.h"

namespace closed_application {
namespace {
constexpr float toRadians(float degrees) { return degrees*closed_loop::kTwoPi/360; }
constexpr float toDegrees(float rad) { return rad*360/closed_loop::kTwoPi; }
constexpr float radiansPerSecond(float rpm) { return closed_loop::tuning::rpmToRadiansPerSecond(rpm); }
const char* modeName(closed_loop::Mode mode) {
  return mode==closed_loop::Mode::Position ? "POSITION" : "VELOCITY";
}
}
void Application::begin() {
  console_.begin(115200);
  if(!hardware_.begin()) fail("INIT_FAILED");
  console_.println("#FOC_INFO,v4 position servo/velocity; live TARGET; 6V; explicit calibration; 1500ms owner lease");
  console_.println("#FOC_INFO,PB4 nFAULT protects only a physically connected fault wire");
  console_.println("#FOC_INFO,DEBUG v1: shaft_rad,target_rad,velocity_sp_rad_s,Uq_V,electrical_rad,zero_electrical_rad,direction,measurement_rad_s");
  report();
}
void Application::stop(const char* reason) {
  hardware_.stop(); // Hardware off before bookkeeping or UART work.
  hardware_.motor().feed_forward_velocity=0;
  lease_.stop();
  policy_.stop();
  if(alignment_.active()) {
    alignment_.abort();
    policy_.invalidate();
  }
  stop_reason_=reason;
}
void Application::fail(const char* reason) {
  const bool first_fault=std::strcmp(fault_,"NONE")==0;
  stop("FAULT");
  policy_.fail();
  fault_=reason;
  if(first_fault) debug(true);
}
void Application::expireLease(uint32_t now) {
  if(lease_.expire(now)) {
    stop("COMM_TIMEOUT");
    report();
  }
}
void Application::reply(bool accepted,uint32_t id,const char* text) {
  console_.print(accepted?"#FOC_ACK,":"#FOC_NACK,");
  console_.print(id); console_.print(','); console_.println(text);
}
void Application::apply(const closed_protocol::Request& r) {
  using closed_protocol::Action;
  // Expiry must win over an arriving late KEEPALIVE, even if UART processing
  // crossed the deadline after this loop's earlier safety check.
  const uint32_t received_ms=millis();
  expireLease(received_ms);
  if(r.action==Action::Keepalive) {
    lease_.keepalive(r.id,received_ms);
    return; // No ACK, highwater mutation, acquisition, or automatic restart.
  }
  if(r.action==Action::Stop) {
    stop("USER_STOP");
    high_water_=std::max(high_water_,r.id);
    reply(true,r.id,"STOP"); report(); return;
  }
  if(r.id<=high_water_) { reply(false,r.id,"STALE_ID"); return; }
  high_water_=r.id;
  if(r.action==Action::Target) {
    // Retarget only the existing position run. This path never enables the
    // driver, changes mode/PI state, or refreshes the communication lease.
    const bool accepted=!policy_.faulted()&&!hardware_.faulted()&&
        !alignment_.active()&&lease_.owns(r.run_id,received_ms)&&
        hardware_.sensor().valid()&&hardware_.enabled()&&hardware_.pinHighReadback()&&
        policy_.retargetPosition(toRadians(r.a),received_ms);
    if(accepted) {
      target_deg_=r.a;
#ifdef FOC_DEBUG_TRACE
      trace_.acceptedTarget(r.id,received_ms);
#endif
    }
    reply(accepted,r.id,accepted?"TARGET":"TARGET_NOT_READY");
    report(); return;
  }
  if(r.action==Action::Overspeed) {
    const bool stopped=!alignment_.active()&&!policy_.running()&&
                       !hardware_.enabled()&&!hardware_.pinHighReadback();
    const bool accepted=stopped&&!hardware_.faulted()&&hardware_.sensor().valid()&&
        policy_.setOverspeedEnabled(r.a==1);
    if(accepted) lease_.stop(); // Configuration never acquires a motion lease.
    reply(accepted,r.id,accepted?"OVERSPEED":"OVERSPEED_CONFIG_NOT_READY");
    report(); return;
  }
  if(r.action==Action::Reset) {
    // Never reset hardware/init faults or enable the bridge as a side effect.
    const bool stopped=!alignment_.active()&&!policy_.running()&&
                       !hardware_.enabled()&&!hardware_.pinHighReadback();
    const bool accepted=stopped&&!hardware_.faulted()&&
        std::strcmp(fault_,"OVERSPEED")==0&&
        policy_.resetOverspeed(hardware_.sensor().valid(),hardware_.sensor().measurementVelocity());
    if(accepted) {
      stop("USER_STOP");
      fault_="NONE";
      hardware_.motor().PID_velocity.reset();
      hardware_.motor().P_angle.reset();
    }
    reply(accepted,r.id,accepted?"RESET":"RESET_NOT_READY");
    report(); return;
  }
  if(policy_.faulted()||hardware_.faulted()) { reply(false,r.id,"FAULT"); return; }
  if(alignment_.active()||policy_.running()||hardware_.enabled()) {
    reply(false,r.id,"BUSY"); return;
  }
  if(!hardware_.sensor().valid()) { reply(false,r.id,"SENSOR_INVALID"); return; }
  const float raw=hardware_.sensor().getAngle();
  bool accepted=false;
  if(r.action==Action::Calibrate) {
    policy_.invalidate();
    accepted=alignment_.start(millis(),raw);
    if(accepted && (!hardware_.enable()||!lease_.start(r.id,millis()))) {
      fail("ENABLE_FAILED"); accepted=false;
    }
  } else if(!policy_.calibrated()) {
    reply(false,r.id,"NOT_CALIBRATED"); return;
  } else if(r.action==Action::Zero) {
    accepted=policy_.zero(raw);
    if(accepted) target_deg_=0;
  } else if(r.action==Action::Limits) {
    const float relative=policy_.relative(raw);
    accepted=relative>=toRadians(r.a)&&relative<=toRadians(r.b)&&
             policy_.setLimits(toRadians(r.a),toRadians(r.b));
  } else {
    if(!policy_.insideLimits(raw)) { reply(false,r.id,"OUTSIDE_SOFT_LIMIT"); return; }
    if(r.action==Action::Position) {
      accepted=policy_.startPosition(toRadians(r.a),radiansPerSecond(r.b),
                                     millis(),true,raw);
    } else if(r.action==Action::Velocity) {
      accepted=policy_.startVelocity(radiansPerSecond(r.a),millis(),true,raw);
    }
    if(accepted) {
      auto& motor=hardware_.motor();
      motor.updateMotionControlType(r.action==Action::Position
          ? MotionControlType::angle : MotionControlType::velocity);
      motor.updateVelocityLimit(r.action==Action::Position
          ? policy_.positionSpeed() : closed_loop::tuning::kVelocityLimitRadS);
      motor.feed_forward_velocity=0;
      motor.PID_velocity.reset(); motor.P_angle.reset();
      if(!hardware_.enable()||!lease_.start(r.id,millis())) {
        fail("ENABLE_FAILED"); accepted=false;
      }
      target_deg_=toDegrees(policy_.requestedTarget());
#ifdef FOC_DEBUG_TRACE
      if(accepted)trace_.acceptedTarget(r.id,received_ms);
#endif
    }
  }
  if(accepted&&(r.action==Action::Calibrate||r.action==Action::Position||r.action==Action::Velocity)) {
    stop_reason_="NONE";
  }
  reply(accepted,r.id,accepted?closed_protocol::name(r.action):"INVALID_OR_ENABLE_FAILED");
  report();
}
void Application::receive() {
  for(unsigned count=0;count<128&&console_.available();++count) {
    const auto parsed=receiver_.feed(static_cast<char>(console_.read()));
    if(parsed==closed_protocol::Parse::Ready) { apply(receiver_.request()); return; }
    if(parsed==closed_protocol::Parse::Invalid) { reply(false,0,"MALFORMED"); return; }
  }
}
void Application::control() {
  auto& sensor=hardware_.sensor();
  auto& motor=hardware_.motor();
  const uint32_t now=millis();
  if(hardware_.faulted()) {
    if(!policy_.faulted()) fail("HARDWARE_OR_FEEDBACK");
    return;
  }
  if((alignment_.active()||policy_.running())&&!sensor.valid()) {
    fail("SENSOR_INVALID"); return;
  }
  if(alignment_.active()) {
    alignment_.tick(now,sensor.getAngle());
    if(alignment_.failed()) { fail("ALIGNMENT_FAILED"); return; }
    if(alignment_.done()) {
      hardware_.stop();
      lease_.stop();
      motor.sensor_direction=alignment_.direction()>0?Direction::CW:Direction::CCW;
      motor.zero_electric_angle=alignment_.zeroElectrical();
      if(!motor.initFOC()) { fail("FOC_INIT_FAILED"); return; }
      policy_.setCalibrated(alignment_.direction());
      policy_.zero(sensor.getAngle());
      target_deg_=0;
      stop_reason_="NONE";
      report(); return;
    }
    motor.setPhaseVoltage(1,0,alignment_.output(now).electrical_angle);
    return;
  }
  if(!policy_.running()) return;
  policy_.tick(now,sensor.valid(),false,sensor.measurementVelocity());
  if(policy_.faulted()) {
    fail(policy_.feedbackFault()==closed_loop::FeedbackFault::Overspeed?"OVERSPEED":"SENSOR_INVALID");
    report(); return;
  }
  const auto output=policy_.output(sensor.getAngle(),motor.sensor_direction*sensor.fastVelocity(),now);
  if(output.stop) {
    if(output.fault) {
      fail(policy_.feedbackFault()==closed_loop::FeedbackFault::SensorInvalid?"SENSOR_INVALID":"SOFT_LIMIT");
    } else stop("LIMIT");
    report(); return;
  }
  motor.controller=output.mode==closed_loop::Mode::Position
      ? MotionControlType::angle : MotionControlType::velocity;
  motor.feed_forward_velocity=output.velocity_feedforward;
  // The domain supplies an absolute signed shaft reference for angle cascade;
  // SimpleFOC closes position/velocity with live sensor commutation feedback.
  motor.loopFOC();
  motor.move(output.target);
}
void Application::report() {
  const bool faulted=policy_.faulted()||hardware_.faulted();
  const char* state=faulted?"FAULT":alignment_.active()?"CALIBRATING":
      policy_.running()?"RUNNING":policy_.calibrated()?"READY":"UNCALIBRATED";
  console_.print("#FOC_STATUS,4,"); console_.print(state); console_.print(',');
  console_.print(policy_.running()?modeName(policy_.mode()):"STOP"); console_.print(',');
  console_.print(high_water_); console_.print(','); console_.print(policy_.calibrated()?1:0); console_.print(',');
  console_.print(hardware_.pinHighReadback()?1:0); console_.print(','); console_.print(hardware_.sensor().valid()?1:0); console_.print(',');
  console_.print(toDegrees(policy_.relative(hardware_.sensor().getAngle())),3); console_.print(',');
  console_.print(target_deg_,3); console_.print(',');
  console_.print(hardware_.sensor().measurementVelocity()*hardware_.motor().sensor_direction*60/closed_loop::kTwoPi,3); console_.print(',');
  console_.print(closed_protocol::zeroDegreesForWire(policy_.zeroRaw()),3); console_.print(',');
  console_.print(toDegrees(policy_.lower()),3); console_.print(','); console_.print(toDegrees(policy_.upper()),3); console_.print(',');
  console_.print(fault_); console_.print(','); console_.print(lease_.runId()); console_.print(',');
  console_.print(lease_.remaining(millis())); console_.print(','); console_.print(stop_reason_);
  console_.print(','); console_.println(policy_.overspeedEnabled()?1:0);
}
void Application::debug(bool force) {
  if(!force&&!policy_.running()) return;
  const auto& motor=hardware_.motor();
  console_.print("#FOC_DEBUG,1,"); console_.print(motor.shaft_angle,6); console_.print(',');
  console_.print(motor.shaft_angle_sp,6); console_.print(','); console_.print(motor.shaft_velocity_sp,6); console_.print(',');
  console_.print(motor.current_sp,6); console_.print(','); console_.print(motor.electrical_angle,6); console_.print(',');
  console_.print(motor.zero_electric_angle,6); console_.print(','); console_.print(static_cast<int>(motor.sensor_direction)); console_.print(',');
  console_.println(hardware_.sensor().measurementVelocity(),6);
}
void Application::trace(uint32_t now) {
#ifdef FOC_DEBUG_TRACE
  if(!trace_.due(now,policy_.running()))return;
  const auto& sensor=hardware_.sensor();
  const auto& motor=hardware_.motor();
  const float relative=toDegrees(policy_.relative(hardware_.sensor().getAngle()));
  const float planned=policy_.mode()==closed_loop::Mode::Position
      ? toDegrees(policy_.plannedRelative()) : relative;
  const auto frame=trace_.frame(now,relative,target_deg_,planned,
      sensor.measurementVelocity()*motor.sensor_direction*60/closed_loop::kTwoPi,
      motor.voltage.q,motor.voltage_limit);
  char line[160];
  const size_t length=frame.format(line,sizeof(line));
  // Never wait for trace output: protect control/lease/watchdog cadence under
  // transport pressure. The 256-byte TX buffer fits one entire trace record.
  if(length&&console_.availableForWrite()>=static_cast<int>(length)) {
    console_.write(reinterpret_cast<const uint8_t*>(line),length);
  }
#else
  (void)now;
#endif
}
void Application::telemetry() {
  const auto& sensor=hardware_.sensor();
  const auto& sample=sensor.sample();
  if(sensor.valid()) {
    console_.print("OK,"); console_.print(toDegrees(sensor.reading().angle_rad),2); console_.print(',');
    console_.print(sensor.measurementVelocity(),3); console_.print(','); console_.print(sensor.reading().frequency_hz,1); console_.print(',');
  } else console_.print("NO_PWM_OR_INVALID,nan,nan,nan,");
  console_.print(sample.high_us); console_.print(','); console_.println(sample.period_us);
}
void Application::tick() {
  hardware_.poll(); expireLease(millis()); control(); receive();
  hardware_.poll(); expireLease(millis()); control();
  const auto now=millis();
  if(static_cast<uint32_t>(now-telemetry_ms_)>=100) { telemetry_ms_=now; telemetry(); }
  if(static_cast<uint32_t>(now-report_ms_)>=200) {
    report_ms_=now; report();
#ifndef FOC_DEBUG_TRACE
    debug();
#endif
  }
  trace(millis());
}
} // namespace closed_application
#endif
