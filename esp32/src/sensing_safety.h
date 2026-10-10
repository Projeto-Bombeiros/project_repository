#pragma once

#include <DHT.h>
#include "types.h"

class SensingSafety {
public:
  SensingSafety();
  void begin();
  SafetyReport update(const Command &cmd, bool pc_linked);
  void diagnostic(bool internal_on, bool external_on);
private:
  void sample();
  void relay(int pin, bool on);
  DHT internal_, external_;
  SafetyReport report_;
  unsigned long last_sample_ = 0;
  bool internal_temp_on_ = false, internal_humidity_on_ = false, external_temp_on_ = false;
};
