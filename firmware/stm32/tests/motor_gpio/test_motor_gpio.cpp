#include "motor_gpio.h"
#include <cstdlib>
#include <iostream>
#include <string>

void require(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
motor_gpio::ParseResult send(motor_gpio::Receiver& receiver, const std::string& line) {
  auto result = motor_gpio::ParseResult::None;
  for (char byte : line) result = receiver.feed(byte);
  return result;
}
int main() {
  using namespace motor_gpio;
  Receiver receiver;
  require(send(receiver, "MOTOR,12,") == ParseResult::None, "partial packet cannot move");
  require(send(receiver, "JOG\r\n") == ParseResult::Ready, "fragmented numbered command");
  require(receiver.request().id == 12 && receiver.request().action == Action::Jog,
          "parse numbered JOG");
  require(send(receiver, "MOTOR,2147483647,STOP\n") == ParseResult::Ready,
          "largest request id");
  for (const std::string line : {"JOG\n", "STOP\n", "MOTOR,0,JOG\n",
       "MOTOR,2147483648,JOG\n", "MOTOR,-1,JOG\n", "MOTOR,1,JOG,x\n",
       "MOTOR,1,ENABLE\n", "ENABLE,1,1\n", "MOTOR,1,STOP\rX\n"}) {
    require(send(receiver, line) == ParseResult::Invalid, "reject malformed command");
  }
  require(send(receiver, std::string(80, 'X') + "MOTOR,1,JOG\n") == ParseResult::Invalid,
          "overlong line cannot reveal a command suffix");
  require(send(receiver, std::string("MOTOR,1,JOG\0", 12) + "\n") == ParseResult::Invalid,
          "reject hidden NUL suffix");
  require(send(receiver, "MOTOR,13,STOP\n") == ParseResult::Ready, "recover after bad input");

  Controller controller;
  require(controller.state() == motor_jog::State::Ready && controller.lastId() == 0,
          "boot is ready without energizing");
  controller.update(0, true, false, false);
  require(controller.apply({1, Action::Jog}, 10, true, false, false) == Result::NotReady,
          "require qualified sensor before explicit JOG");
  controller.update(500, true, false, false);
  require(controller.apply({2, Action::Jog}, 500, true, true, false) == Result::AlreadyEnabled,
          "reject pre-existing enable lease");
  require(controller.apply({3, Action::Jog}, 500, true, false, false) == Result::Started,
          "valid command reserves a single run");
  require(controller.lastId() == 3 && controller.running(), "track acknowledged JOG id");
  require(controller.apply({3, Action::Jog}, 1000, true, true, false) == Result::AlreadyUsed,
          "duplicate JOG never renews deadline");
  require(controller.apply({4, Action::Jog}, 1100, true, true, false) == Result::AlreadyUsed,
          "new JOG id also cannot renew run");
  controller.update(3499, true, true, false);
  require(controller.running(), "run ends at original deadline");
  controller.update(3500, true, true, false);
  require(controller.state() == motor_jog::State::Done, "three second bound");
  require(controller.apply({3, Action::Jog}, 3501, true, false, false) == Result::AlreadyUsed,
          "same JOG id cannot replay after completion");
  require(controller.apply({5, Action::Jog}, 3501, true, false, false) == Result::Started,
          "new explicit JOG after completion can run");
  require(controller.apply({6, Action::Stop}, 3501, false, false, false) == Result::Stopped,
          "numbered STOP accepted without sensor");
  require(controller.lastId() == 6, "STOP becomes latest accepted command");
  require(controller.apply({2, Action::Stop}, 3501, false, false, false) == Result::Stopped,
          "stale numbered STOP still stops");
  require(controller.lastId() == 6, "stale STOP cannot roll back command high-water mark");
  controller.update(3502, true, false, false); controller.update(4002, true, false, false);
  require(controller.apply({5, Action::Jog}, 4002, true, false, false) == Result::AlreadyUsed,
          "STOP id cannot erase replay protection");
  require(controller.apply({7, Action::Jog}, 4002, true, false, false) == Result::Started,
          "new command after STOP can run");
  require(controller.apply({8, Action::Stop}, 4003, true, true, false) == Result::Stopped,
          "stop a second run");
  controller.update(4004, true, false, false);
  require(controller.apply({3, Action::Jog}, 4004, true, false, false) == Result::AlreadyUsed,
          "older than most recent JOG remains blocked");

  Controller cut;
  cut.update(0, true, false, false); cut.update(500, true, false, false);
  require(cut.apply({1, Action::Jog}, 500, true, false, false) == Result::Started, "start cut test");
  cut.update(501, true, false, false);
  require(!cut.running(), "ENABLE 0 or lease loss stops motion");
  require(cut.state() == motor_jog::State::Done, "enable recovery cannot automatically restart");
  require(cut.apply({2, Action::Jog}, 502, true, false, false) == Result::Started,
          "new explicit JOG after output off can run");

  Controller fault;
  fault.update(0, true, false, false); fault.update(500, true, false, false);
  require(fault.apply({1, Action::Jog}, 500, true, false, false) == Result::Started, "start fault test");
  fault.update(501, false, false, true);
  require(fault.state() == motor_jog::State::Fault, "output or sensor fault latches");
  require(fault.apply({2, Action::Stop}, 502, false, false, true) == Result::Stopped,
          "stop always works in fault");
  require(fault.state() == motor_jog::State::Fault, "stop never clears latched fault");
  Controller watchdog; watchdog.fail();
  require(watchdog.apply({1, Action::Jog}, 0, true, false, false) == Result::Fault,
          "watchdog reset cannot start");
  std::cout << "PASS: numbered commands, stable feedback, EN lease, one shot, deadlines and fault stops\n";
}
