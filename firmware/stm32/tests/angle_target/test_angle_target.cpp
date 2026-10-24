#include "angle_target.h"
#include <cstdlib>
#include <iostream>
#include <string>

void require(bool value, const char* message) {
  if (!value) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

angle_target::Result send(angle_target::Receiver& receiver, const std::string& line) {
  auto result = angle_target::Result::None;
  for (char c : line) result = receiver.feed(c);
  return result;
}

int main() {
  using namespace angle_target;
  Receiver receiver;
  require(receiver.target() == -1 && receiver.requestId() == 0, "no target on boot");
  for (const int degrees : {0, 90, 180, 270}) {
    const std::string line = "TARGET," + std::to_string(degrees + 1) + "," +
                             std::to_string(degrees) + "\r\n";
    require(send(receiver, line) == Result::Accepted, "accept four presets");
    require(receiver.target() == degrees, "stage exact degrees");
  }
  require(send(receiver, "TARGET,271,270\n") == Result::Accepted, "duplicate is idempotent");
  require(send(receiver, "TARGET,271,90\n") == Result::Conflict, "same id different angle rejected");
  require(receiver.target() == 270, "conflict preserves confirmed target");
  for (const std::string line : {"TARGET,0,90\n", "TARGET,-1,90\n", "TARGET,1,-90\n",
       "TARGET,1,360\n", "TARGET,1,nan\n", "TARGET,1,90.5\n", "TARGET,1,90,0\n",
       "TARGET,2147483648,90\n", "TARGET,1\n", "ARM,1\n", "TARGET,1_0,90\n"}) {
    require(send(receiver, line) == Result::Malformed, "malformed/unsupported command rejected");
    require(receiver.target() == 270, "bad commands cannot mutate target");
  }
  require(send(receiver, std::string(100, 'X') + "TARGET,2,0\n") == Result::Malformed,
          "discard whole oversized line");
  require(send(receiver, "TARGET,2,") == Result::None, "partial line cannot stage target");
  require(send(receiver, "0\n") == Result::Accepted && receiver.target() == 0,
          "recover after overflow and fragmented command");
  std::cout << "PASS: bounded target parsing, presets, duplicate, conflict and overflow\n";
}
