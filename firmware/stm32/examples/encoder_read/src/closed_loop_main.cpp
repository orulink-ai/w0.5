#if defined(CLOSED_LOOP_CONTROL)
#include "closed_loop_app.h"
namespace {
HardwareSerial console(PA3_ALT1,PA2_ALT1);
closed_application::Application application(console);
}
void setup(){application.begin();}
void loop(){application.tick();}
#endif
