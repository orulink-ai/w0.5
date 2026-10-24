#pragma once

#include "motor_jog.h"
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace motor_gpio {
enum class Action { Jog, Stop };
struct Request { uint32_t id; Action action; };
enum class ParseResult { None, Ready, Invalid };
enum class Result { Started, Stopped, NotReady, AlreadyEnabled, AlreadyUsed, Fault };

// Hardware-independent motion policy. Only a new explicit command may rearm
// DONE; fault recovery and an EN lease changing state never start motion.
class Controller {
 public:
  void update(uint32_t now, bool sensor_valid, bool enabled, bool output_fault) {
    guard_.update(now, sensor_valid);
    if (output_fault) guard_.fail();
    else if (guard_.running() && !enabled) guard_.stop();
  }

  Result apply(Request request, uint32_t now, bool sensor_valid,
               bool enabled, bool output_fault) {
    // STOP always succeeds and never clears a latched fault.
    if (request.action == Action::Stop) {
      guard_.stop();
      // A stale STOP still stops, but cannot roll back replay protection.
      if (request.id > last_id_) last_id_ = request.id;
      return Result::Stopped;
    }
    if (output_fault || guard_.state() == motor_jog::State::Fault) return Result::Fault;
    if (guard_.running() || request.id <= last_id_) return Result::AlreadyUsed;
    if (enabled) return Result::AlreadyEnabled;
    guard_.update(now, sensor_valid);
    if (guard_.state() == motor_jog::State::Done && !guard_.rearm(now)) return Result::NotReady;
    if (!guard_.start(now)) return Result::NotReady;
    last_id_ = request.id;
    return Result::Started;
  }

  void fail() { guard_.fail(); }
  bool running() const { return guard_.running(); }
  motor_jog::State state() const { return guard_.state(); }
  uint32_t lastId() const { return last_id_; }

 private:
  motor_jog::Guard guard_;
  uint32_t last_id_ = 0;
};

class Receiver {
 public:
  ParseResult feed(char byte) {
    if (byte != '\n') {
      if (!overflow_ && length_ < sizeof(line_) - 1) line_[length_++] = byte;
      else overflow_ = true;
      return ParseResult::None;
    }
    if (length_ && line_[length_ - 1] == '\r') --length_;
    line_[length_] = '\0';
    const bool valid_length = !overflow_ && std::strlen(line_) == length_;
    length_ = 0;
    overflow_ = false;
    if (!valid_length || std::strncmp(line_, "MOTOR,", 6) != 0) return ParseResult::Invalid;
    const char* cursor = line_ + 6;
    uint32_t id = 0;
    if (*cursor < '0' || *cursor > '9') return ParseResult::Invalid;
    while (*cursor >= '0' && *cursor <= '9') {
      const uint32_t digit = *cursor++ - '0';
      if (id > (0x7FFFFFFFU - digit) / 10U) return ParseResult::Invalid;
      id = 10U * id + digit;
    }
    if (!id || *cursor++ != ',') return ParseResult::Invalid;
    if (std::strcmp(cursor, "JOG") == 0) request_ = {id, Action::Jog};
    else if (std::strcmp(cursor, "STOP") == 0) request_ = {id, Action::Stop};
    else return ParseResult::Invalid;
    return ParseResult::Ready;
  }
  Request request() const { return request_; }

 private:
  char line_[40]{};
  size_t length_ = 0;
  bool overflow_ = false;
  Request request_{};
};
} // namespace motor_gpio
