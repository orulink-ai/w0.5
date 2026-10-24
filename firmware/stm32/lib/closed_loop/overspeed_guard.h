#pragma once
#include <cmath>
#include <cstdint>
#include "closed_loop_tuning.h"

namespace closed_loop {
// Each motor owns its own consecutive-exceedance window. No UART or hardware
// dependency; the policy still handles invalid feedback and hardware faults.
class OverspeedGuard {
 public:
  void reset(){pending_=false;since_ms_=0;}
  bool update(uint32_t now,float velocity,bool active) {
    if(!active||!std::isfinite(velocity)){reset();return false;}
    const float speed=std::fabs(velocity);
    if(speed>tuning::kOverspeedHardRadS){reset();return true;}
    if(speed<=tuning::kOverspeedSoftRadS){reset();return false;}
    if(!pending_){since_ms_=now;pending_=true;}
    return static_cast<uint32_t>(now-since_ms_)>=tuning::kOverspeedHoldMs;
  }
 private:
  bool pending_=false;
  uint32_t since_ms_=0;
};
} // namespace closed_loop
