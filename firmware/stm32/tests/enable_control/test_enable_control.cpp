#include "enable_control.h"
#include <cstdlib>
#include <iostream>
#include <string>

void require(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

enable_control::ParseResult send(enable_control::Receiver& receiver, const std::string& line) {
  auto result = enable_control::ParseResult::None;
  for (char byte : line) result = receiver.feed(byte);
  return result;
}

int main() {
  using namespace enable_control;
  Controller controller;
  require(!controller.enabled() && controller.lastId() == 0, "boot defaults off");
  require(controller.apply({1, true}, 10, false) == Result::SensorInvalid,
          "invalid sensor cannot enable");
  require(controller.apply({2, true}, 10, true) == Result::Accepted, "explicit enable");
  require(controller.enabled(), "enable changes desired output");
  require(controller.apply({2, true}, 1000, true) == Result::Accepted, "duplicate accepted");
  require(controller.apply({3, true}, 1000, true) == Result::Busy, "new enable cannot extend");
  require(controller.apply({2, false}, 1000, true) == Result::Conflict,
          "request id cannot change meaning");
  controller.update(5009, true);
  require(controller.enabled(), "on through original duration");
  controller.update(5010, true);
  require(!controller.enabled(), "off at five second deadline");
  require(controller.apply({2, true}, 5011, true) == Result::Expired,
          "late duplicate cannot re-enable");
  require(controller.apply({4, true}, 5011, true) == Result::Accepted, "new explicit run");
  require(controller.apply({5, false}, 5012, false) == Result::Accepted,
          "off works even with missing feedback");
  require(!controller.enabled(), "off immediately clears desired output");
  require(controller.faulted(), "lost feedback latches fault");
  require(controller.apply({6, true}, 5013, true) == Result::Fault,
          "feedback recovery cannot auto clear fault");
  require(controller.apply({7, false}, 5013, false) == Result::Accepted,
          "fault still allows off");
  Controller watchdog;
  watchdog.fail();
  require(watchdog.apply({1, true}, 0, true) == Result::Fault, "watchdog reset is locked off");
  Controller motion;
  require(motion.apply({20, false}, 0, true) == Result::Accepted, "record independent ENABLE id");
  require(motion.startForMotion(10, true) == Result::Accepted, "motion acquires a fresh bounded lease");
  require(motion.lastId() == 20, "motion does not consume ENABLE namespace");
  require(motion.startForMotion(100, true) == Result::Busy, "motion cannot extend active lease");
  require(motion.apply({20, false}, 101, true) == Result::Accepted,
          "replayed serial OFF remains accepted after internal motion enable");
  require(!motion.enabled(), "replayed OFF physically clears the new motion lease");
  require(motion.startForMotion(10, true) == Result::Accepted, "new independent expiry scenario");
  motion.update(5010, true);
  require(!motion.enabled(), "motion lease expires at original five second bound");
  require(motion.startForMotion(5011, true) == Result::Accepted, "new motion may acquire after off");
  motion.stop();
  require(!motion.enabled() && motion.lastId() == 20, "internal stop preserves ENABLE id");
  require(motion.startForMotion(5012, false) == Result::SensorInvalid, "motion also requires sensor");
  motion.fail();
  require(motion.startForMotion(5013, true) == Result::Fault, "motion cannot bypass latched fault");
  Controller rollover;
  require(rollover.apply({1, true}, 0xFFFFFF00U, true) == Result::Accepted, "enable near rollover");
  rollover.update(4744, true);
  require(!rollover.enabled(), "five second deadline survives millis rollover");

  Receiver receiver;
  require(send(receiver, "ENABLE,12,") == ParseResult::None, "no action on partial input");
  require(send(receiver, "1\r\n") == ParseResult::Ready, "fragmented CRLF command");
  require(receiver.request().id == 12 && receiver.request().enabled, "exact values");
  for (const std::string line : {"ENABLE,0,1\n", "ENABLE,2147483648,1\n",
       "ENABLE,1,2\n", "ENABLE,1,true\n", "ENABLE,1,1,0\n", "JOG\n"}) {
    require(send(receiver, line) == ParseResult::Invalid, "reject malformed commands");
  }
  require(send(receiver, std::string(100, 'X') + "ENABLE,1,1\n") == ParseResult::Invalid,
          "discard whole overlong command");
  require(send(receiver, std::string("ENABLE,1,1\0", 11) + "\n") == ParseResult::Invalid,
          "reject hidden NUL suffix");
  require(send(receiver, "ENABLE,13,0\n") == ParseResult::Ready && !receiver.request().enabled,
          "recover with off command");
  std::cout << "PASS: default off, explicit enable, five second bound, replay, loss, off and parsing\n";
}
