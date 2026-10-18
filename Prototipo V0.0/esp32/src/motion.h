#pragma once

#include "types.h"

struct TrackTargets { float left, right; };
inline TrackTargets mixDrive(float drive_x, float drive_y) {
  const float forward = -drive_y;
  return {clampf(forward + drive_x, -1, 1), clampf(forward - drive_x, -1, 1)};
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
