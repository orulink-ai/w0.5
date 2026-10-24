#include "closed_loop.h"
#include "closed_protocol.h"
#include "run_lease.h"
#include "position_control.h"
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
  assert(parse("FOC,42,KEEPALIVE\n")==Parse::Ready);
  assert(receiver.request().action==closed_protocol::Action::Keepalive);
  for(const char* invalid:{"FOC,4,START,POSITION,10,1,1.2\n","FOC,4,START,POSITION,10\n","FOC,4,START,SPRING,0,.5\n",
      "FOC,4,START,SWEEP,-5,5,1\n","FOC,0,STOP\n","FOC,2147483648,STOP\n",
      "FOC,4,START,POSITION,nan,1\n"}) assert(parse(invalid)==Parse::Invalid);
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
  p.tick(10001,true,false,-2.01f);assert(p.faulted()&&!p.running());
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
int main() {
  testProtocol();testFeedback();testLease();testPositionComponents();testPolicy();testAlignment();
}
