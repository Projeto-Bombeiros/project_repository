#pragma once

#include <Arduino.h>

struct Command {
  unsigned long seq = 0;
  bool valid = false;
  bool auto_mode = false;
  float drive_x = 0.0f, drive_y = 0.0f;
  float cannon_x = 0.0f, cannon_y = 0.0f;
  float cannon_rate_deg_s = 90.0f;
  float camera_rate_deg_s = 90.0f, auto_rate_deg_s = 90.0f;
  float auto_pan = 90.0f, auto_tilt = 90.0f;
  float camera_pan = 90.0f;
  bool calibrating = false;
  float calibration_pan = 90.0f, calibration_tilt = 90.0f;
  bool vision_valid = false, target_valid = false, person_detected = false;
  bool cool_manual = false, cool_internal = false, cool_external = false;
  bool jet_enable = false, leds_on = false, stop = false, rearm = false;
  bool water_on = false, brake = false, emergency = false;
  float pressure = 0.0f, focus = 0.0f;
};

struct SafetyReport {
  float temp_internal = NAN, humidity_internal = NAN;
  float temp_external = NAN, humidity_external = NAN;
  bool internal_valid = false, external_valid = false;
  bool alert_internal = false, alert_external = false;
  bool cool_internal_commanded = false, cool_external_commanded = false;
  bool cool_internal_configured = false, cool_external_configured = false;
};

struct CentralSnapshot {
  bool connected = false, armed = false, safe = false, auto_mode = false;
  bool allow_motion = false, allow_jet = false;
  bool motion_moving = false;
  bool cool_internal_on = false, cool_external_on = false, jet_on = false;
  bool alert_internal = false, alert_external = false;
  const char *reason = "boot";
};

struct MotionReport {
  float left_commanded = 0.0f, right_commanded = 0.0f;
  bool configured = false, moving = false;
};

struct CannonReport {
  float pan_commanded = 90.0f, tilt_commanded = 90.0f;
  float camera_pan_commanded = 90.0f;
  bool camera_servo_configured = false;
  bool servos_configured = false, jet_configured = false;
  bool jet_commanded = false, jet_virtual = false;
};

inline float clampf(float x, float a, float b) {
  return x < a ? a : (x > b ? b : x);
}
