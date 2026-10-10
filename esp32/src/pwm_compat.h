#pragma once

#include <Arduino.h>
#include <esp_arduino_version.h>

// Arduino-ESP32 2.x e 3.x expõem assinaturas distintas de LEDC.
inline void blazePwmAttach(int pin, unsigned channel, unsigned hz, unsigned bits) {
  if (pin < 0) return;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttachChannel(pin, hz, bits, channel);
#else
  ledcSetup(channel, hz, bits);
  ledcAttachPin(pin, channel);
#endif
}

inline void blazePwmWrite(int pin, unsigned channel, unsigned duty) {
  if (pin < 0) return;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(channel, duty);
#endif
}
