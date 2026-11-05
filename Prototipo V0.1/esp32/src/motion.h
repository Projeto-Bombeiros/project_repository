#pragma once

#include "types.h"

struct TrackTargets { float left, right; };
inline float steeringInput(float x) {
  // Curva progressiva: pequena deflexão lateral produz curva suave.
  const float limited = clampf(x, -1.f, 1.f);
  return 0.45f * limited * fabsf(limited);
}
inline TrackTargets mixDrive(float drive_x, float drive_y) {
  const float forward = -drive_y;
  const float turn = steeringInput(drive_x);
  return {clampf(forward + turn, -1, 1), clampf(forward - turn, -1, 1)};
}

class Motion {
public:
  void begin();
  MotionReport update(const Command &cmd, const CentralSnapshot &state);
  void diagnostic(float left, float right);  // ensaio USB temporizado, sem rede
private:
  void motor(int rpwm, int lpwm, unsigned channel_a, unsigned channel_b, float speed);
  float left_ = 0.0f, right_ = 0.0f;
  unsigned long previous_ms_ = 0;
};
