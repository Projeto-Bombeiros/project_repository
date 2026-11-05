#pragma once

#include "types.h"

class CannonJet {
public:
  void begin();
  CannonReport update(const Command &cmd, const CentralSnapshot &state);
  void panDiagnostic(float angle);
  void tiltDiagnostic(float angle);
  void cameraDiagnostic(float angle);
  void focusDiagnostic(float angle);
private:
  void servo(int pin, unsigned channel, float angle);
  float pan_ = 90.0f, tilt_ = 90.0f, camera_pan_ = 90.0f;
  float pan_target_ = 90.0f, tilt_target_ = 90.0f, camera_target_ = 90.0f;
  float pan_velocity_ = 0.0f, tilt_velocity_ = 0.0f, camera_velocity_ = 0.0f;
  float last_servo_angle_[4] = {NAN, NAN, NAN, NAN};
  unsigned long last_servo_write_ms_[4] = {};
  float focus_angle_ = 90.0f;
  unsigned long previous_ms_ = 0;
};
