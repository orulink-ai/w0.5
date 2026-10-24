#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace enable_control {
struct Request { uint32_t id; bool enabled; };
enum class ParseResult { None, Ready, Invalid };
enum class Result { Accepted, SensorInvalid, Busy, Conflict, Expired, Fault };

class Controller {
 public:
  static constexpr uint32_t kMaxOnMs = 5000;
  void update(uint32_t now, bool sensor_valid) {
    if (enabled_ && !sensor_valid) fail();
    if (enabled_ && static_cast<uint32_t>(now - started_ms_) >= kMaxOnMs) enabled_ = false;
  }
  Result apply(Request request, uint32_t now, bool sensor_valid) {
    update(now, sensor_valid);
    if (request.id == last_id_) {
      if (request.enabled != last_requested_) return Result::Conflict;
      // An internal motion lease can have raised EN since this OFF was last
      // acknowledged. Replaying OFF must still physically stop that lease.
      if (!request.enabled) enabled_ = false;
      return request.enabled && !enabled_ ? Result::Expired : Result::Accepted;
    }
    if (request.enabled) {
      if (faulted_) return Result::Fault;
      if (!sensor_valid) return Result::SensorInvalid;
      if (enabled_) return Result::Busy;
      started_ms_ = now;
    }
    enabled_ = request.enabled;
    last_requested_ = request.enabled;
    last_id_ = request.id;
    return Result::Accepted;
  }
  // Motion uses its own numbered protocol; do not consume/reinterpret an
  // ENABLE request id when it acquires the same bounded hardware lease.
  Result startForMotion(uint32_t now, bool sensor_valid) {
    update(now, sensor_valid);
    if (faulted_) return Result::Fault;
    if (!sensor_valid) return Result::SensorInvalid;
    if (enabled_) return Result::Busy;
    started_ms_ = now;
    enabled_ = true;
    return Result::Accepted;
  }
  void fail() { enabled_ = false; faulted_ = true; }
  // Internal motion stop must not reinterpret or consume a serial request id.
  void stop() { enabled_ = false; }
  bool enabled() const { return enabled_; }
  bool faulted() const { return faulted_; }
  uint32_t lastId() const { return last_id_; }

 private:
  bool enabled_ = false;
  bool faulted_ = false;
  bool last_requested_ = false;
  uint32_t started_ms_ = 0;
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
    if (!valid_length || std::strncmp(line_, "ENABLE,", 7) != 0) return ParseResult::Invalid;
    const char* cursor = line_ + 7;
    uint32_t id = 0;
    if (*cursor < '0' || *cursor > '9') return ParseResult::Invalid;
    while (*cursor >= '0' && *cursor <= '9') {
      const uint32_t digit = *cursor++ - '0';
      if (id > (0x7FFFFFFFU - digit) / 10U) return ParseResult::Invalid;
      id = 10U * id + digit;
    }
    if (!id || *cursor++ != ',' || (*cursor != '0' && *cursor != '1') || cursor[1] != '\0') {
      return ParseResult::Invalid;
    }
    request_ = {id, *cursor == '1'};
    return ParseResult::Ready;
  }
  Request request() const { return request_; }

 private:
  char line_[40]{};
  size_t length_ = 0;
  bool overflow_ = false;
  Request request_{};
};
} // namespace enable_control
