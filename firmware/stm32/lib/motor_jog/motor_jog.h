#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace motor_jog {
enum class State { Ready, Running, Done, Fault };
enum class Command { None, Jog, Stop, Invalid };

// Hardware-independent one-shot policy. A new boot and an explicit command
// are required for every test; repeated commands cannot extend its deadline.
class Guard {
 public:
  void update(uint32_t now_ms, bool valid) {
    observed_ms_ = now_ms;
    if (!valid) {
      qualified_ = false;
      if (running()) fail();
    } else if (!qualified_) {
      valid_since_ms_ = now_ms;
      qualified_ = true;
    }
    if (running() && static_cast<uint32_t>(now_ms - started_ms_) >= 3000U) {
      state_ = State::Done;
    }
  }

  bool start(uint32_t now_ms) {
    if (state_ != State::Ready || !canStart(now_ms)) return false;
    started_ms_ = now_ms;
    state_ = State::Running;
    return true;
  }
  void stop() { if (state_ != State::Fault) state_ = State::Done; }
  // Only the GPIO-controlled, numbered-command policy uses explicit rearming.
  // The original manual-EN bench never calls this and stays one-shot per boot.
  bool rearm(uint32_t now_ms) {
    if (state_ != State::Done || !canStart(now_ms)) return false;
    state_ = State::Ready;
    return true;
  }
  void fail() { state_ = State::Fault; }
  bool running() const { return state_ == State::Running; }
  State state() const { return state_; }

 private:
  bool canStart(uint32_t now_ms) const {
    return qualified_ && static_cast<uint32_t>(now_ms - observed_ms_) < 20U &&
           static_cast<uint32_t>(now_ms - valid_since_ms_) >= 500U;
  }
  State state_ = State::Ready;
  bool qualified_ = false;
  uint32_t observed_ms_ = 0;
  uint32_t valid_since_ms_ = 0;
  uint32_t started_ms_ = 0;
};

class Receiver {
 public:
  Command feed(char byte) {
    if (byte != '\n') {
      if (!overflow_ && length_ < sizeof(line_) - 1) line_[length_++] = byte;
      else overflow_ = true;
      return Command::None;
    }
    if (length_ && line_[length_ - 1] == '\r') --length_;
    line_[length_] = '\0';
    Command command = Command::Invalid;
    if (!overflow_ && std::strlen(line_) == length_) {
      if (std::strcmp(line_, "JOG") == 0) command = Command::Jog;
      else if (std::strcmp(line_, "STOP") == 0) command = Command::Stop;
    }
    length_ = 0;
    overflow_ = false;
    return command;
  }

 private:
  char line_[16]{};
  size_t length_ = 0;
  bool overflow_ = false;
};
} // namespace motor_jog
