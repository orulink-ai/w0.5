#include "motor_jog.h"
#include <cstdlib>
#include <iostream>
#include <initializer_list>
#include <string>

void require(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

motor_jog::Command send(motor_jog::Receiver& input, const std::string& line) {
  auto result = motor_jog::Command::None;
  for (char byte : line) result = input.feed(byte);
  return result;
}

int main() {
  using namespace motor_jog;
  Guard guard;
  require(!guard.running(), "boot never starts motion");
  require(!guard.start(0), "no start without sensor history");
  guard.update(10, true);
  require(!guard.start(509), "require 500ms valid feedback");
  guard.update(510, true);
  require(guard.start(510), "explicit command after valid history starts");
  require(!guard.start(1000), "repeat start cannot extend run");
  guard.update(3509, true);
  require(guard.running(), "run until original deadline");
  guard.update(3510, true);
  require(guard.state() == State::Done, "three second deadline stops");
  require(!guard.start(4000), "one run per boot even after success");

  Guard lost;
  lost.update(0, true); lost.update(500, true);
  require(lost.start(500), "start second independent scenario");
  lost.update(501, false);
  require(lost.state() == State::Fault, "bad feedback stops immediately");
  lost.update(1001, true);
  require(!lost.start(1501), "feedback recovery cannot restart a fault");

  Guard stale;
  stale.update(0, true); stale.update(500, true);
  require(!stale.start(600), "old observation cannot authorize start");
  stale.update(600, false); stale.update(700, true);
  require(!stale.start(700), "bad feedback resets stable history");

  Guard stopped;
  stopped.stop(); stopped.update(500, true); stopped.update(1000, true);
  require(!stopped.start(1000), "stop before start prevents queued start");

  Guard rollover;
  rollover.update(0xFFFFFF00U, true); rollover.update(244, true);
  require(rollover.start(244), "sensor qualification survives millis rollover");
  rollover.update(3244, true);
  require(!rollover.running(), "deadline after rollover stops");

  Receiver input;
  require(send(input, "JO") == Command::None, "partial command cannot start");
  require(send(input, "G\r\n") == Command::Jog, "fragmented exact JOG accepted");
  require(send(input, "STOP\n") == Command::Stop, "stop accepted");
  for (const std::string& line : std::initializer_list<std::string>{"JOG,100\n", "TARGET,1,90\n", "ENABLE\n", "\n",
                                std::string(40, 'X') + "JOG\n"}) {
    require(send(input, line) == Command::Invalid, "reject unknown/oversized input");
  }
  require(send(input, std::string("JOG\0", 4) + "\n") == Command::Invalid,
          "embedded NUL cannot hide command suffix");
  require(send(input, "STOP\n") == Command::Stop, "recover after malformed command");
  std::cout << "PASS: no autostart, one-shot deadline, feedback loss, stop and bounded commands\n";
}
