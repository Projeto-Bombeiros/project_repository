#pragma once

#include "types.h"

class Central {
public:
  CentralSnapshot update(const Command &command, bool connected,
                         const SafetyReport &safety);
  CentralSnapshot observe(const CentralSnapshot &current, const SafetyReport &safety,
                          const MotionReport &motion, const CannonReport &cannon);
private:
  bool armed_ = false;
  bool auto_mode_ = false;
  bool rearm_released_ = false;
  bool last_rearm_ = false;
};
