#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace angle_target {
// This protocol stages a target only. It has no motor enable or GPIO access.
enum class Result { None, Accepted, Malformed, Conflict };

class Receiver {
 public:
  Result feed(char byte) {
    if (byte != '\n') {
      if (length_ < sizeof(line_) - 1 && !overflow_) line_[length_++] = byte;
      else overflow_ = true;
      return Result::None;
    }
    const bool overflow = overflow_;
    overflow_ = false;
    if (length_ && line_[length_ - 1] == '\r') --length_;
    line_[length_] = '\0';
    const size_t length = length_;
    length_ = 0;
    reply_id_ = 0;
    if (overflow || length == 0 || std::strlen(line_) != length ||
        std::strncmp(line_, "TARGET,", 7) != 0) return Result::Malformed;
    const char* cursor = line_ + 7;
    uint32_t id = 0;
    uint32_t degrees = 0;
    if (!number(cursor, id) || id == 0 || id > 0x7FFFFFFFU || *cursor++ != ',' ||
        !number(cursor, degrees) || degrees >= 360 || *cursor != '\0') {
      return Result::Malformed;
    }
    reply_id_ = id;
    if (id == request_id_ && target_ != static_cast<int>(degrees)) return Result::Conflict;
    request_id_ = id;
    target_ = static_cast<int>(degrees);
    return Result::Accepted;
  }

  uint32_t requestId() const { return request_id_; }
  uint32_t replyId() const { return reply_id_; }
  int target() const { return target_; }

 private:
  static bool number(const char*& cursor, uint32_t& value) {
    if (*cursor < '0' || *cursor > '9') return false;
    value = 0;
    while (*cursor >= '0' && *cursor <= '9') {
      const uint32_t digit = static_cast<uint32_t>(*cursor - '0');
      if (value > (UINT32_MAX - digit) / 10U) return false;
      value = value * 10U + digit;
      ++cursor;
    }
    return true;
  }
  char line_[48]{};
  size_t length_ = 0;
  bool overflow_ = false;
  uint32_t reply_id_ = 0;
  uint32_t request_id_ = 0;
  int target_ = -1;
};
} // namespace angle_target
