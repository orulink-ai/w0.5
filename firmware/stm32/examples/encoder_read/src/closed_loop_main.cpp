#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_app.h"
namespace {
HardwareSerial console(PA3_ALT1,PA2_ALT1);
closed_application::Application application(console);
closed_hardware::BoardWatchdog watchdog;
#ifdef DUAL_MOTOR_CONTROL
closed_application::Application secondary(console,closed_hardware::secondaryPins());
closed_protocol::Receiver receiver;
void receive() {
  for(unsigned count=0;count<128&&console.available();++count) {
    const auto result=receiver.feed(static_cast<char>(console.read()));
    if(result==closed_protocol::Parse::Ready) {
      const auto& request=receiver.request();
      if(request.motor_id==1)application.handle(request);
      else secondary.handle(request);
      return;
    }
    if(result==closed_protocol::Parse::Invalid){console.println("#FOC_NACK,0,MALFORMED");return;}
  }
}
#endif
}
void setup(){
  // Disable both bridges before either motor's blocking initialization starts.
  for(const auto pin:{PB5,PB12,PA8,PA9,PA10,PA6,PA7,PB0}){digitalWrite(pin,LOW);pinMode(pin,OUTPUT);}
  console.begin(115200); // One shared UART; never reinitialize it per motor.
  const bool board_ready=watchdog.begin();
  application.begin(board_ready);
#ifdef DUAL_MOTOR_CONTROL
  watchdog.poll();secondary.begin(board_ready);
#endif
  if(!watchdog.arm()) {
    application.boardFault();
#ifdef DUAL_MOTOR_CONTROL
    secondary.boardFault();
#endif
  }
}
void loop(){
  watchdog.poll();
  application.tick();
#ifdef DUAL_MOTOR_CONTROL
  secondary.tick();receive();
#endif
  watchdog.poll();
}
#endif
