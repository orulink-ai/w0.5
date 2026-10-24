#pragma once
#include <cmath>
#include <cstring>
#include <initializer_list>

namespace closed_loop {
struct CalibrationReadiness {
  const char* fault;
  bool active,enabled,sensor_valid,hardware_ready;
  float velocity;
};
inline bool recoverableCalibrationFault(const char* fault) {
  if(!fault)return false;
  for(const char* allowed:{"NONE","ALIGNMENT_FAILED","FOC_INIT_FAILED","OVERSPEED",
      "SOFT_LIMIT","SENSOR_INVALID","HARDWARE_OR_FEEDBACK","ENABLE_FAILED"}) {
    if(std::strcmp(fault,allowed)==0)return true;
  }
  return false;
}
inline bool canRecalibrate(const CalibrationReadiness& state) {
  return recoverableCalibrationFault(state.fault)&&!state.active&&!state.enabled&&
      state.sensor_valid&&state.hardware_ready&&std::isfinite(state.velocity)&&
      std::fabs(state.velocity)<=.2f;
}
} // namespace closed_loop
