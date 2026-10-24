#pragma once
#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_hardware.h"
#include "closed_protocol.h"
#include "run_lease.h"
#ifdef FOC_DEBUG_TRACE
#include "debug_trace.h"
#endif

namespace closed_application {
class Application {
 public:
  explicit Application(HardwareSerial& console):console_(console){}
  void begin();
  void tick();
 private:
  void stop(const char* reason);
  void fail(const char* reason);
  void expireLease(uint32_t now);
  void apply(const closed_protocol::Request& request);
  void receive();
  void report();
  void debug(bool force=false);
  void trace(uint32_t now);
  void telemetry();
  void reply(bool accepted,uint32_t id,const char* text);
  void control();
  HardwareSerial& console_;
  closed_hardware::MotorHardware hardware_;
  closed_loop::Policy policy_;
  closed_loop::Alignment alignment_;
  closed_loop::RunLease lease_;
  closed_protocol::Receiver receiver_;
#ifdef FOC_DEBUG_TRACE
  closed_loop::DebugTrace trace_;
#endif
  uint32_t high_water_=0,report_ms_=0,telemetry_ms_=0;
  float target_deg_=0;
  const char* fault_="NONE";
  const char* stop_reason_="NONE";
};
} // namespace closed_application
#endif
