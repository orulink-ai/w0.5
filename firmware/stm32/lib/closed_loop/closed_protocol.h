#pragma once
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
namespace closed_protocol {
// Wire zero is single-turn even though the domain origin stays multi-turn.
// Serial.print(...,3) must never round a just-below-360 value to 360.000.
inline float zeroDegreesForWire(float raw_radians) {
  constexpr float two_pi=6.28318530718f;
  float value=std::fmod(raw_radians,two_pi)*360/two_pi;
  if(value<0)value+=360;
  return value>=359.9995f?0:value;
}
enum class Action { Calibrate,Zero,Stop,Limits,Position,Velocity,Keepalive };
struct Request {uint32_t id=0;Action action=Action::Stop;float a=0,b=0;};
enum class Parse {None,Ready,Invalid};
inline bool number(const char* value,float& result) {
  if(!value||!*value)return false;
  char* end=nullptr;errno=0;result=std::strtof(value,&end);
  return errno==0&&end&&*end=='\0'&&std::isfinite(result);
}
class Receiver {
 public:
  Parse feed(char ch) {
    if(ch!='\n') {
      if((static_cast<unsigned char>(ch)<32 && ch!='\r') || static_cast<unsigned char>(ch)>126) {overflow_=true;return Parse::None;}
      if(length_<sizeof(line_)-1&&!overflow_)line_[length_++]=ch;
      else overflow_=true;
      return Parse::None;
    }
    line_[length_]='\0';
    const bool valid=!overflow_&&parse();length_=0;overflow_=false;
    return valid?Parse::Ready:Parse::Invalid;
  }
  const Request& request()const{return request_;}
 private:
  bool parse() {
    if(length_&&line_[length_-1]=='\r')line_[--length_]='\0';
    char* fields[8]{};unsigned count=0;
    fields[count++]=line_;
    for(char* p=line_;*p;++p)if(*p==',') {
      *p='\0';if(count==8)return false;fields[count++]=p+1;
    }
    if(count<3||std::strcmp(fields[0],"FOC")!=0)return false;
    uint32_t id=0;
    if(!*fields[1])return false;
    for(const char* p=fields[1];*p;++p){if(*p<'0'||*p>'9')return false;const uint32_t digit=*p-'0';if(id>(2147483647U-digit)/10)return false;id=id*10+digit;}
    if(!id)return false;
    Request r;r.id=id;
    if(count==3) {
      if(!std::strcmp(fields[2],"CALIBRATE"))r.action=Action::Calibrate;
      else if(!std::strcmp(fields[2],"ZERO"))r.action=Action::Zero;
      else if(!std::strcmp(fields[2],"STOP"))r.action=Action::Stop;
      else if(!std::strcmp(fields[2],"KEEPALIVE"))r.action=Action::Keepalive;
      else return false;
    } else if(count==5&&!std::strcmp(fields[2],"LIMITS")) {
      r.action=Action::Limits;if(!number(fields[3],r.a)||!number(fields[4],r.b))return false;
    } else if(count>=5&&!std::strcmp(fields[2],"START")) {
      if(count==6&&!std::strcmp(fields[3],"POSITION"))r.action=Action::Position;
      else if(count==5&&!std::strcmp(fields[3],"VELOCITY"))r.action=Action::Velocity;
      else return false;
      if(!number(fields[4],r.a))return false;
      if(count>=6&&!number(fields[5],r.b))return false;
    } else return false;
    request_=r;return true;
  }
  char line_[128]{};size_t length_=0;bool overflow_=false;Request request_{};
};
inline const char* name(Action action) {
 switch(action){case Action::Calibrate:return "CALIBRATE";case Action::Zero:return "ZERO";case Action::Stop:return "STOP";case Action::Limits:return "LIMITS";case Action::Position:return "POSITION";case Action::Velocity:return "VELOCITY";case Action::Keepalive:return "KEEPALIVE";}
 return "STOP";
}
} // namespace closed_protocol
