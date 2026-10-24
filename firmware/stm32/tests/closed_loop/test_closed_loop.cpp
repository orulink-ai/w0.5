#include "closed_loop.h"
#include "closed_protocol.h"
#include "run_lease.h"
#include "position_control.h"
#include "debug_trace.h"
#include "calibration_recovery.h"
#include <cassert>
#include <cmath>

using namespace closed_loop;

void testProtocol() {
  closed_protocol::Receiver receiver;
  auto parse=[&](const char* text) {
    closed_protocol::Parse result{};
    while(*text) result=receiver.feed(*text++);
    return result;
  };
  using closed_protocol::Parse;
  assert(parse("FOC,42,START,POSITION,10,1\n")==Parse::Ready);
  assert(receiver.request().a==10&&receiver.request().b==1);
  assert(receiver.request().motor_id==1);
  assert(parse("FOC2,42,START,POSITION,-10,1\n")==Parse::Ready);
  assert(receiver.request().motor_id==2&&receiver.request().a==-10);
  assert(parse("FOC2,42,KEEPALIVE\n")==Parse::Ready);
  assert(receiver.request().motor_id==2);
  assert(parse("FOC2,43,STOP\n")==Parse::Ready);
  assert(receiver.request().motor_id==2&&receiver.request().action==closed_protocol::Action::Stop);
  assert(parse("FOC3,43,STOP\n")==Parse::Invalid);
  assert(parse("FOC,42,KEEPALIVE\n")==Parse::Ready);
  assert(receiver.request().motor_id==1);
  assert(parse("FOC,42,KEEPALIVE\n")==Parse::Ready);
  assert(receiver.request().action==closed_protocol::Action::Keepalive);
  assert(parse("FOC,43,RESET\n")==Parse::Ready);
  assert(receiver.request().action==closed_protocol::Action::Reset);
  assert(std::strcmp(closed_protocol::name(receiver.request().action),"RESET")==0);
  assert(parse("FOC,43,RESET,1\n")==Parse::Invalid);
  assert(parse("FOC,44,OVERSPEED,0\n")==Parse::Ready);
  assert(receiver.request().action==closed_protocol::Action::Overspeed&&receiver.request().a==0);
  assert(parse("FOC,45,OVERSPEED,1\n")==Parse::Ready);
  for(const char* invalid:{"FOC,44,OVERSPEED,2\n","FOC,44,OVERSPEED,true\n",
      "FOC,44,OVERSPEED,\n","FOC,44,OVERSPEED,0,1\n"}) assert(parse(invalid)==Parse::Invalid);
  for(const char* invalid:{"FOC,4,START,POSITION,10,1,1.2\n","FOC,4,START,POSITION,10\n","FOC,4,START,SPRING,0,.5\n",
      "FOC,4,START,SWEEP,-5,5,1\n","FOC,0,STOP\n","FOC,2147483648,STOP\n",
      "FOC,4,START,POSITION,nan,1\n"}) assert(parse(invalid)==Parse::Invalid);
  assert(parse("FOC,1700000001,TARGET,16777217,-12.5\n")==Parse::Ready);
  assert(receiver.request().action==closed_protocol::Action::Target);
  assert(receiver.request().id==1700000001&&receiver.request().run_id==16777217U);
  assert(receiver.request().a==-12.5f);
  for(const char* invalid:{"FOC,45,TARGET,0,5\n","FOC,45,TARGET,-1,5\n",
      "FOC,45,TARGET,2147483648,5\n","FOC,45,TARGET,42,nan\n",
      "FOC,45,TARGET,42,5,1\n","FOC,45,TARGET,42.0,5\n"}) assert(parse(invalid)==Parse::Invalid);
  const auto wireZero=closed_protocol::zeroDegreesForWire;
  assert(wireZero(kTwoPi-.000001f)==0);
  assert(wireZero(-.001f)>359&&wireZero(-.001f)<360);
}

void testFeedback() {
  AngleTracker forward;
  forward.push(6.27f,1,1000);forward.push(.02f,2,23000);
  assert(forward.angle()>6.28f&&forward.angle()<6.31f);
  AngleTracker reverse;
  reverse.push(.01f,1,1000);reverse.push(kTwoPi-.02f,2,23000);
  assert(reverse.angle()<0&&reverse.angle()>-.03f);
  AngleTracker braking;
  braking.push(0,1,1000);braking.push(.0044f,2,5400);
  const float initial=braking.controlVelocity();
  assert(initial>.5f&&initial<.7f&&braking.velocity()==0);
  braking.push(.0044f,2,5500);assert(braking.controlVelocity()==initial);
  braking.push(.0044f,3,9800);assert(braking.controlVelocity()<initial*.5f);
  assert(braking.velocity()==0);
  braking.push(.0044f,4,14200);braking.push(.0044f,5,18600);braking.push(.0044f,6,23000);
  assert(std::fabs(braking.velocity()-.08f)<.0001f&&braking.controlVelocity()<.02f);
}

void testLease() {
  RunLease lease;
  assert(!lease.active()&&!lease.keepalive(1,0));
  assert(lease.start(11,100)&&lease.remaining(100)==1500);
  assert(!lease.keepalive(12,500));
  assert(lease.keepalive(11,600)&&lease.remaining(600)==1500);
  assert(lease.expire(2100)&&!lease.active());
  assert(!lease.keepalive(11,2100)&&!lease.keepalive(11,2200));
  assert(lease.start(12,2200));lease.stop();
  assert(!lease.keepalive(12,2201));
  assert(lease.start(13,UINT32_MAX-100));
  assert(lease.remaining(399)==1000);assert(lease.expire(1399));
  // Calibration owns the same lease: a browser disappearing must cancel it.
  Alignment calibration;assert(calibration.start(0,0));
  assert(lease.start(14,0));
  if(lease.expire(1500))calibration.abort();
  assert(!calibration.active()&&!calibration.done()&&!lease.keepalive(14,1501));
}

void testPositionComponents() {
  RateLimitedReference reference;
  assert(reference.start(0,1,.2f,UINT32_MAX-100));
  assert(reference.update(399)>.099f&&reference.current()<.101f);
  assert(reference.update(5399)==1);assert(reference.update(6399)==1);
  assert(reference.start(1,-1,.5f,0));assert(reference.update(1000)==.5f);
  assert(!reference.start(0,NAN,.2f,0));
  assert(!reference.start(0,1,INFINITY,0));
  assert(reference.start(1,1e-8f,.2f,0));
  reference.update(10000);
  assert(reference.current()==1e-8f&&reference.velocity()==0);
  assert(reference.start(0,1,.2f,0));
  assert(reference.velocity()>.19f);
  reference.update(6000);
  assert(reference.current()==1&&reference.velocity()==0);

}

void testPolicy() {
  Policy p;
  assert(!p.running()&&!p.calibrated());
  assert(!p.startPosition(.2f,.2f,0,true,0));
  p.setCalibrated(-1);assert(p.zero(20));
  assert(p.startPosition(.5f,.2f,100,true,20));
  assert(p.requestedTarget()==.5f);
  auto initial=p.output(20,0,100);
  assert(initial.target==-20&&initial.velocity_feedforward>.19f);
  const auto normal=p.output(20,0,1100);
  assert(std::fabs(normal.target+19.8f)<.0001f);
  // Manual movement does not redefine the requested or absolute shaft target.
  const auto deflected=p.output(20.2f,0,1100);
  assert(deflected.target==normal.target&&p.requestedTarget()==.5f);
  auto arrived=p.output(20,0,3100);
  assert(std::fabs(arrived.target+19.5f)<.0001f&&arrived.velocity_feedforward==0);
  p.tick(10100,true,false,0);
  assert(p.running()&&p.output(20,0,10100).target==arrived.target);
  p.stop();assert(p.output(20,0,10101).stop);
  assert(!p.startPosition(.5f,0,0,true,20));
  assert(!p.startPosition(NAN,.2f,0,true,20));
  assert(!p.startPosition(.5f,INFINITY,0,true,20));
  assert(!p.startVelocity(.2f,0,true,22));
  assert(p.startVelocity(.2f,0,true,20));
  p.tick(10000,true,false,.2f);assert(p.running());
  p.tick(10001,true,false,-13);assert(p.faulted()&&!p.running());
  Policy cw;cw.setCalibrated(1);cw.zero(6.27f);
  assert(cw.startPosition(.3f,.2f,0,true,6.27f));
  assert(std::fabs(cw.output(6.27f,0,1000).target-6.47f)<.0001f);
  Policy limited;limited.setCalibrated(1);limited.zero(0);
  assert(limited.startVelocity(.2f,0,true,0));
  assert(limited.output(kHalfPi-.01f,0,1).stop&&!limited.faulted());
  assert(limited.startPosition(0,.2f,0,true,0));
  assert(limited.output(kHalfPi+.1f,0,1).fault);
  for(float bad:{NAN,INFINITY}) {
    Policy invalid;invalid.setCalibrated(1);invalid.zero(0);
    assert(invalid.startVelocity(.2f,0,true,0));
    invalid.tick(1,true,false,bad);assert(invalid.faulted());
  }
}

void testSpeedBounds() {
  auto rad_s=[](float rpm){return rpm*kTwoPi/60;};
  Policy p;p.setCalibrated(1);assert(p.zero(0));
  assert(p.startPosition(.5f,rad_s(10),0,true,0));p.stop();
  assert(!p.startPosition(.5f,rad_s(10.01f),0,true,0));
  assert(p.startPosition(.5f,rad_s(.1f),0,true,0));p.stop();
  assert(!p.startPosition(.5f,rad_s(.09f),0,true,0));
  for(float sign:{-1.f,1.f}) {
    assert(p.startVelocity(rad_s(sign*10),0,true,0));p.stop();
    assert(!p.startVelocity(rad_s(sign*10.01f),0,true,0));
    assert(p.startVelocity(rad_s(sign*.1f),0,true,0));p.stop();
    assert(!p.startVelocity(rad_s(sign*.09f),0,true,0));
  }
  assert(!p.startVelocity(NAN,0,true,0));
  assert(!p.startPosition(.5f,INFINITY,0,true,0));
}

void testRetargetPosition() {
  Policy p;p.setCalibrated(-1);assert(p.zero(20));
  assert(!p.retargetPosition(.5f,0)); // A target update cannot arm the controller.
  assert(p.startPosition(1,.2f,100,true,20));
  p.output(20,0,600);
  // Bring the original trajectory to now before changing its destination.
  assert(p.retargetPosition(-.5f,1100));
  const auto changed=p.output(20.8f,0,1100);
  assert(std::fabs(changed.target+19.8f)<.0001f); // Ignores measured deflection.
  assert(p.requestedTarget()==-.5f&&p.positionSpeed()==.2f);
  assert(changed.velocity_feedforward<0);
  const auto next=p.output(20,0,1600);
  assert(std::fabs(next.target+19.9f)<.0001f); // Still moves only .1rad per .5s.
  assert(!p.retargetPosition(2,1600)&&!p.retargetPosition(NAN,1600));
  assert(p.requestedTarget()==-.5f);
  p.stop();assert(!p.retargetPosition(0,1601));
  assert(p.startVelocity(.2f,1700,true,20));
  assert(!p.retargetPosition(0,1701)&&p.mode()==Mode::Velocity);
  p.tick(1800,false,false);assert(!p.retargetPosition(0,1800));
  RunLease lease;assert(lease.start(42,100));
  assert(lease.owns(42,500)&&!lease.owns(43,500));
  assert(lease.remaining(500)==1100); // Admission checks do not renew the lease.
  assert(!lease.owns(42,1600)&&lease.expire(1600));
  assert(!lease.owns(42,1601)&&!lease.keepalive(42,1601));
  assert(lease.start(43,1700)&&!lease.owns(42,1700));
  lease.stop();assert(!lease.owns(43,1701));
}

void testDebugTrace() {
  DebugTrace trace;
  assert(!trace.due(0,false));
  trace.acceptedTarget(17,100);
  assert(trace.due(100,true));
  assert(!trace.due(149,true)&&trace.due(150,true));
  trace.acceptedTarget(18,160);
  assert(!trace.due(170,true)); // Drag updates never restart the 20Hz clock.
  auto frame=trace.frame(200,-1.2345f,10.5f,2.25f,-.125f,2.999f,3);
  assert(frame.last_target_id==18&&frame.target_received_ms==160&&frame.mcu_ms==200);
  char line[160]{};
  assert(frame.format(line,sizeof(line))>0);
  assert(std::strcmp(line,"#FOC_TRACE,1,200,18,160,-1.235,10.500,2.250,-0.125,2.999,3.000\n")==0);
  assert(frame.format(line,10)==0);
  frame.actual_uq=NAN;assert(frame.format(line,sizeof(line))==0);
  assert(trace.due(1000,true)&&!trace.due(1001,true)); // No catch-up burst.
  assert(!trace.due(1002,false)&&trace.due(UINT32_MAX-20,true));
  assert(!trace.due(28,true)&&trace.due(29,true)); // 50ms across rollover.
}

void testAlignment() {
  for(int direction:{-1,1}) {
    Alignment a;assert(a.start(0,2.3f));
    for(unsigned t=0;t<=1000;t+=2)a.tick(t,2.3f+static_cast<float>(direction)*t/1000.f*kTwoPi/7);
    for(unsigned t=1002;t<=2002;t+=2)a.tick(t,2.3f+static_cast<float>(direction)*(2002-t)/1000.f*kTwoPi/7);
    a.tick(2204,2.3f);a.tick(2905,2.3f);
    assert(a.done()&&a.direction()==direction);
    assert(std::fabs(a.zeroElectrical()-normalize(direction*7*2.3f))<.0001f);
  }
  Alignment stalled;stalled.start(0,0);
  for(unsigned t=0;t<3300;t+=2)stalled.tick(t,0);
  assert(stalled.failed());
}

void testManualFaultReset() {
  Policy p;p.setCalibrated(1);assert(p.zero(.5f));
  assert(!p.resetOverspeed(true,0)); // Not a fault: RESET is not START.
  assert(p.startPosition(.3f,.2f,0,true,.5f));
  p.tick(1,true,false,13);
  assert(p.faulted()&&!p.running());
  assert(!p.resetOverspeed(false,0));
  for(float velocity:{NAN,INFINITY,.21f,-.21f}) {
    assert(!p.resetOverspeed(true,velocity));
    assert(p.faulted()&&!p.running());
  }
  assert(p.resetOverspeed(true,0));
  assert(!p.faulted()&&!p.running()&&p.calibrated());
  assert(p.feedbackFault()==FeedbackFault::None&&p.zeroRaw()==.5f);
  assert(p.output(.5f,0,2).stop); // No implicit return to the old target.
  assert(p.startPosition(.1f,.2f,3,true,.5f)); // Explicit START is required.
  p.tick(4,false,false,0);
  assert(p.faulted()&&!p.resetOverspeed(true,0));
  Policy hardware;hardware.setCalibrated(1);hardware.zero(0);
  assert(hardware.startVelocity(.2f,0,true,0));
  hardware.tick(1,true,true,0);
  assert(!hardware.resetOverspeed(true,0));
}
void testOverspeedSwitch() {
  Policy p;assert(p.overspeedEnabled());p.setCalibrated(1);assert(p.zero(0));
  assert(p.startVelocity(.2f,0,true,0));
  assert(!p.setOverspeedEnabled(false)); // Configuration requires a stop.
  p.stop();assert(p.setOverspeedEnabled(false)&&!p.overspeedEnabled());
  assert(!p.running()&&p.startVelocity(.2f,1,true,0));
  p.tick(2,true,false,13);assert(!p.faulted()&&p.running());
  p.tick(3,false,false,13);assert(p.faulted()&&!p.running());
  assert(!p.setOverspeedEnabled(true)); // Does not bypass other fault latches.
  Policy q;q.setCalibrated(1);q.zero(0);
  assert(q.startVelocity(.2f,0,true,0));q.tick(1,true,false,13);
  assert(q.faulted()&&q.setOverspeedEnabled(false));
  assert(q.faulted()&&!q.running()); // Switching does not acknowledge the fault.
  assert(q.resetOverspeed(true,0));
  assert(q.setOverspeedEnabled(true));
  assert(q.startVelocity(.2f,2,true,0));q.tick(3,true,false,13);
  assert(q.faulted());
  Policy limits;limits.setCalibrated(1);limits.zero(0);
  assert(limits.setOverspeedEnabled(false)&&limits.startVelocity(.2f,0,true,0));
  assert(limits.output(kHalfPi+.1f,0,1).fault);
  Policy hardware;hardware.setCalibrated(1);hardware.zero(0);
  assert(hardware.setOverspeedEnabled(false)&&hardware.startVelocity(.2f,0,true,0));
  hardware.tick(1,true,true,0);assert(hardware.faulted()&&!hardware.running());
  Policy reboot;assert(reboot.overspeedEnabled()); // No persistent bypass.
}
void testRelaxedOverspeed() {
  auto rpm=[](float value){return tuning::rpmToRadiansPerSecond(value);};
  auto running=[](){Policy p;p.setCalibrated(1);assert(p.zero(0));
    assert(p.startVelocity(.2f,0,true,0));return p;};
  Policy normal=running();
  normal.tick(0,true,false,rpm(50));normal.tick(1000,true,false,rpm(-60));
  assert(normal.running()&&!normal.faulted());
  for(float sign:{-1.f,1.f}) {
    Policy timed=running();timed.tick(0,true,false,rpm(sign*90));
    timed.tick(99,true,false,rpm(sign*90));assert(timed.running());
    timed.tick(100,true,false,rpm(sign*90));
    assert(timed.faulted()&&timed.feedbackFault()==FeedbackFault::Overspeed);
    Policy hard=running();hard.tick(0,true,false,rpm(sign*121));
    assert(hard.faulted()&&!hard.running());
  }
  Policy boundary=running();boundary.tick(0,true,false,rpm(120));
  assert(boundary.running());boundary.tick(100,true,false,rpm(120));assert(boundary.faulted());
  Policy spikes=running();spikes.tick(0,true,false,rpm(90));
  spikes.tick(99,true,false,rpm(60)); // Recovering to the boundary clears the window.
  spikes.tick(100,true,false,rpm(-90));spikes.tick(199,true,false,rpm(-90));
  assert(spikes.running());spikes.tick(200,true,false,rpm(-90));assert(spikes.faulted());
  Policy restart=running();restart.tick(0,true,false,rpm(90));restart.stop();
  assert(restart.startVelocity(.2f,1000,true,0));
  restart.tick(1000,true,false,rpm(90));assert(restart.running());
  restart.tick(1099,true,false,rpm(90));assert(restart.running());
  restart.tick(1100,true,false,rpm(90));assert(restart.faulted());
  Policy wrap=running();wrap.tick(UINT32_MAX-50,true,false,rpm(90));
  wrap.tick(48,true,false,rpm(90));assert(wrap.running());
  wrap.tick(49,true,false,rpm(90));assert(wrap.faulted());
  Policy first=running(),second=running();first.tick(0,true,false,rpm(90));
  second.tick(50,true,false,rpm(90));first.tick(100,true,false,rpm(90));
  second.tick(100,true,false,rpm(90));assert(first.faulted()&&second.running());
  for(bool hardware:{false,true}) {
    Policy immediate=running();immediate.tick(0,true,false,rpm(90));
    immediate.tick(1,!hardware?false:true,hardware,rpm(90));
    assert(immediate.faulted()&&immediate.feedbackFault()==
        (hardware?FeedbackFault::Hardware:FeedbackFault::SensorInvalid));
  }
}
void testCalibrationRecovery() {
  CalibrationReadiness state{"ALIGNMENT_FAILED",false,false,true,true,0};
  for(const char* fault:{"NONE","ALIGNMENT_FAILED","FOC_INIT_FAILED","OVERSPEED",
      "SOFT_LIMIT","SENSOR_INVALID","HARDWARE_OR_FEEDBACK","ENABLE_FAILED"}) {
    state.fault=fault;assert(canRecalibrate(state));
  }
  for(const char* fault:{"INIT_FAILED","WATCHDOG_INIT_FAILED","UNKNOWN"}) {
    state.fault=fault;assert(!canRecalibrate(state));
  }
  state.fault=nullptr;assert(!canRecalibrate(state));
  state.fault="ALIGNMENT_FAILED";
  state.active=true;assert(!canRecalibrate(state));state.active=false;
  state.enabled=true;assert(!canRecalibrate(state));state.enabled=false;
  state.sensor_valid=false;assert(!canRecalibrate(state));state.sensor_valid=true;
  state.hardware_ready=false;assert(!canRecalibrate(state));state.hardware_ready=true;
  for(float speed:{.21f,-.21f,NAN,INFINITY}){state.velocity=speed;assert(!canRecalibrate(state));}
  state.velocity=.2f;assert(canRecalibrate(state));
  Policy one,two;
  one.setCalibrated(1);assert(one.zero(0));
  two.setCalibrated(-1);assert(two.zero(2));
  assert(one.startVelocity(.2f,0,true,0));
  assert(!one.resetForCalibration());
  one.tick(1,true,true,0);assert(one.faulted());
  assert(one.resetForCalibration());
  assert(!one.faulted()&&!one.calibrated()&&!one.running());
  assert(one.feedbackFault()==FeedbackFault::None);
  assert(!one.startPosition(0,.2f,2,true,0)); // Recalibration cannot resume motion.
  assert(two.calibrated()&&two.zeroRaw()==2&&!two.faulted());
}
void testMotorTuningIsolation() {
  const auto primary=tuning::controllerFor(1);
  const auto secondary=tuning::controllerFor(2);
  // Tuning the second axis must preserve the accepted first-axis response.
  assert(primary.voltage_ramp==10.0f);
  assert(secondary.voltage_ramp==100.0f);
  assert(primary.velocity_p==0.20f);
  assert(secondary.velocity_p==0.10f);
  assert(primary.velocity_i==secondary.velocity_i);
  assert(primary.velocity_d==secondary.velocity_d);
  assert(primary.velocity_filter_seconds==secondary.velocity_filter_seconds);
  assert(primary.angle_p==secondary.angle_p);
  assert(tuning::controllerFor(1).voltage_ramp==primary.voltage_ramp);
}

int main() {
  testMotorTuningIsolation();
  testCalibrationRecovery();
  testRelaxedOverspeed();
  DebugTrace dualTrace;
  assert(dualTrace.due(0,true,100));
  assert(!dualTrace.due(50,true,100));
  assert(dualTrace.due(100,true,100));
  testProtocol();testFeedback();testLease();testPositionComponents();testPolicy();testSpeedBounds();testRetargetPosition();testDebugTrace();testAlignment();testManualFaultReset();testOverspeedSwitch();
}
