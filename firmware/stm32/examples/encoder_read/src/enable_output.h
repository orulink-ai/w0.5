#pragma once
#include <Arduino.h>
#include "enable_control.h"

namespace enable_output {
// Motor builds preserve the already configured TIM1 PWM pin modes.
void begin(bool initialize_phase_pins = true);
// Extend a previously running IWDG before SimpleFOC's blocking startup, while
// PB5 is LOW. begin() restores the ordinary short watchdog afterwards.
bool prepareInitialization();
bool poll(bool sensor_valid);
void receive(char byte, bool sensor_valid, Print& output);
void report(Print& output);
bool enabled();
bool faulted();
enable_control::Result enableForMotion(uint32_t id, bool sensor_valid);
bool forceOff();
} // namespace enable_output
