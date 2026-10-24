#pragma once
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace closed_loop {
struct TraceFrame {
  uint32_t mcu_ms=0,last_target_id=0,target_received_ms=0;
  float relative_deg=0,requested_deg=0,planned_relative_deg=0;
  float signed_velocity_rpm=0,actual_uq=0,limit_v=0;

  // Integer fixed-point formatting avoids embedded printf's optional floating
  // point support. A bounded line is either emitted whole or discarded.
  size_t format(char* output,size_t capacity) const {
    if(!output||capacity==0)return 0;
    int count=std::snprintf(output,capacity,"#FOC_TRACE,1,%lu,%lu,%lu",
        static_cast<unsigned long>(mcu_ms),static_cast<unsigned long>(last_target_id),
        static_cast<unsigned long>(target_received_ms));
    if(count<0||static_cast<size_t>(count)>=capacity)return 0;
    size_t used=static_cast<size_t>(count);
    const float values[]={relative_deg,requested_deg,planned_relative_deg,
                          signed_velocity_rpm,actual_uq,limit_v};
    for(float value:values) {
      if(!std::isfinite(value)||std::fabs(value)>1000000)return 0;
      const int32_t scaled=static_cast<int32_t>(value*1000+(value<0?-.5f:.5f));
      const uint32_t magnitude=static_cast<uint32_t>(scaled<0?-scaled:scaled);
      count=std::snprintf(output+used,capacity-used,",%s%lu.%03lu",scaled<0?"-":"",
          static_cast<unsigned long>(magnitude/1000),static_cast<unsigned long>(magnitude%1000));
      if(count<0||static_cast<size_t>(count)>=capacity-used)return 0;
      used+=static_cast<size_t>(count);
    }
    if(used+2>capacity)return 0;
    output[used++]='\n';output[used]='\0';
    return used;
  }
};

class DebugTrace {
 public:
  void acceptedTarget(uint32_t id,uint32_t received_ms) {
    last_target_id_=id;target_received_ms_=received_ms;
  }
  bool due(uint32_t now,bool running) {
    if(!running){scheduled_=false;return false;}
    if(scheduled_&&static_cast<uint32_t>(now-last_emitted_ms_)<50)return false;
    scheduled_=true;last_emitted_ms_=now;return true;
  }
  TraceFrame frame(uint32_t now,float relative,float requested,float planned,
                   float velocity_rpm,float actual_uq,float limit_v) const {
    return {now,last_target_id_,target_received_ms_,relative,requested,planned,
            velocity_rpm,actual_uq,limit_v};
  }
 private:
  uint32_t last_target_id_=0,target_received_ms_=0,last_emitted_ms_=0;
  bool scheduled_=false;
};
} // namespace closed_loop
