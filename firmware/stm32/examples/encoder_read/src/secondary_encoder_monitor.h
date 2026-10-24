#pragma once
#if defined(CLOSED_LOOP_CONTROL)
#include <Arduino.h>
#include "closed_loop.h"

// Auxiliary feedback is display-only: it has no reference to MotorHardware,
// the motion policy, calibration, or the command/lease state.
class SecondaryEncoderMonitor {
 public:
  void begin();
  void tick(HardwareSerial& console);
 private:
  closed_loop::AngleTracker tracker_;
  uint32_t report_ms_ = 0;
  bool ready_ = false;
};
#endif
