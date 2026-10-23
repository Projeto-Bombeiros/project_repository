/*
 * Runtime contínuo embarcado (PlatformIO/Arduino-ESP32).
 * Integra os subsistemas em um firmware. A central calcula estados/permissões,
 * os módulos de atuação decidem seus GPIO, e o arrefecimento opera localmente.
 */
#include <Arduino.h>
#include <cstdio>
#include <cstring>
#include <cmath>

#include "central.h"
#include "net_link.h"
#include "motion.h"
#include "cannon_jet.h"
#include "sensing_safety.h"
#include "pins.h"

NetLink communication;
Central central;
Motion traction;
CannonJet cannon;
SensingSafety safety;
unsigned long last_telemetry_ms = 0;
unsigned long last_fast_telemetry_ms = 0;
namespace {
char diagnostic_line[1152] = {};
size_t diagnostic_used = 0;
bool diagnostic_active = false;
unsigned long diagnostic_until = 0;
char diagnostic_channel[24] = {};
float diagnostic_value = 0;

void diagnosticStop() {
  traction.diagnostic(0, 0);
  safety.diagnostic(false, false);
  diagnostic_active = false;
  Serial.println("DIAG DONE");
}

void readUsbDiagnostic() {
  int budget = 80;
  while (Serial.available() && budget-- > 0) {
    const char ch = char(Serial.read());
    if (ch != '\n') {
      if (ch != '\r' && diagnostic_used < sizeof(diagnostic_line) - 1)
        diagnostic_line[diagnostic_used++] = ch;
      continue;
    }
    diagnostic_line[diagnostic_used] = '\0';
    diagnostic_used = 0;
    if (diagnostic_line[0] == '{') {
      communication.acceptSerialLine(diagnostic_line);
      continue;
    }
    if (strcmp(diagnostic_line, "STATUS") == 0) {
      // STATUS não altera saídas: permite conferir ambos DHT mesmo sem Wi-Fi.
      const SafetyReport s = safety.update(Command{}, false);
      Serial.printf("SENSOR,%d,%.2f,%.2f,%d,%.2f,%.2f,DHT%d,%d,DHT%d,%d,%.2f,%.2f,%.2f,%.2f\n",
                    s.internal_valid, s.temp_internal, s.humidity_internal,
                    s.external_valid, s.temp_external, s.humidity_external,
                    BLAZE_DHT_INTERNAL_TYPE, s.internal_error,
                    BLAZE_DHT_EXTERNAL_TYPE, s.external_error,
                    s.temp_internal_raw, s.humidity_internal_raw,
                    s.temp_external_raw, s.humidity_external_raw);
      continue;
    }
    if (strcmp(diagnostic_line, "VERSION") == 0) {
      Serial.printf("VERSION,%s,%s,%d,%d\n", BLAZE_SETUP_NAME,
                    BLAZE_SETUP_SIGNATURE, BLAZE_DRIVE_KIND, BLAZE_CANNON_KIND);
      continue;
    }
    char name[24] = {}, trailing = 0;
    float value = 0;
    unsigned long duration = 0;
    if (sscanf(diagnostic_line, "TEST %23s %f %lu %c", name, &value, &duration, &trailing) != 3 ||
        !std::isfinite(value) || duration < 100 || duration > 1200 || communication.linked() ||
        diagnostic_active) {
      Serial.println("DIAG REFUSED: sintaxe, enlace ativo ou teste em curso");
      continue;
    }
    const bool motor = strcmp(name, "MOTOR_L") == 0 || strcmp(name, "MOTOR_R") == 0;
    const bool servo = strcmp(name, "SERVO_PAN") == 0 || strcmp(name, "SERVO_TILT") == 0;
    const bool camera_servo = strcmp(name, "SERVO_CAMERA") == 0;
    const bool focus_servo = strcmp(name, "SERVO_FOCUS") == 0;
    const bool relay = strcmp(name, "COOL_INT") == 0 || strcmp(name, "COOL_EXT") == 0;
    if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS) {
      Serial.println("DIAG REFUSED: saídas físicas desabilitadas neste firmware");
      continue;
    }
    if ((motor && BLAZE_DRIVE_KIND == 3) || (servo && BLAZE_CANNON_KIND == 2) ||
        (camera_servo && pins::servo_camera_pan < 0)) {
      Serial.println("DIAG REFUSED: driver escolhido ainda sem interface de acionamento validada");
      continue;
    }
    if ((!motor && !servo && !camera_servo && !focus_servo && !relay) ||
        (motor && (value < -.25f || value > .25f)) ||
        (servo && (value < 0.f || value > 180.f)) ||
        (camera_servo && (value < 0.f || value > 180.f)) ||
        (focus_servo && (value < 0.f || value > 180.f)) ||
        (relay && value != 0.f && value != 1.f)) {
      Serial.println("DIAG REFUSED: canal ou valor inválido");
      continue;
    }
    strncpy(diagnostic_channel, name, sizeof(diagnostic_channel) - 1);
    diagnostic_value = value;
    diagnostic_until = millis() + duration;
    diagnostic_active = true;
    Serial.printf("DIAG START,%s,%.3f,%lu\n", name, value, duration);
  }
}

void diagnosticTick() {
  if (!diagnostic_active) return;
  if (communication.linked() || long(millis() - diagnostic_until) >= 0) {
    diagnosticStop();
    return;
  }
  traction.diagnostic(strcmp(diagnostic_channel, "MOTOR_L") == 0 ? diagnostic_value : 0,
                      strcmp(diagnostic_channel, "MOTOR_R") == 0 ? diagnostic_value : 0);
  if (strcmp(diagnostic_channel, "SERVO_PAN") == 0)
    cannon.panDiagnostic(diagnostic_value);
  if (strcmp(diagnostic_channel, "SERVO_TILT") == 0)
    cannon.tiltDiagnostic(diagnostic_value);
  if (strcmp(diagnostic_channel, "SERVO_CAMERA") == 0)
    cannon.cameraDiagnostic(diagnostic_value);
  if (strcmp(diagnostic_channel, "SERVO_FOCUS") == 0)
    cannon.focusDiagnostic(diagnostic_value);
  safety.diagnostic(strcmp(diagnostic_channel, "COOL_INT") == 0 && diagnostic_value == 1,
                    strcmp(diagnostic_channel, "COOL_EXT") == 0 && diagnostic_value == 1);
}
}

void setup() {
  // 460800 deixa margem para comandos e telemetria simultâneos pela CP210x.
  Serial.begin(460800);
  delay(100);
  traction.begin();
  cannon.begin();
  safety.begin();
  if (BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::led_status >= 0) {
    digitalWrite(pins::led_status, LOW);
    pinMode(pins::led_status, OUTPUT);
  }
  communication.begin();
  Serial.println("BLAZE prototipo: modo manual independe da camera; autonomia exige visao valida.");
  Serial.print("Setup oficial: "); Serial.println(BLAZE_SETUP_NAME);
}

void loop() {
  communication.poll();
  readUsbDiagnostic();
  if (diagnostic_active) {
    diagnosticTick();
    delay(10);
    return;
  }
  const bool connected = communication.linked();
  const Command &cmd = communication.command();
  if (BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::led_status >= 0)
    digitalWrite(pins::led_status, connected && cmd.valid && !cmd.stop && cmd.leds_on ? HIGH : LOW);
  const SafetyReport s = safety.update(cmd, connected);
  const CentralSnapshot permissions = central.update(cmd, connected, s);
  const MotionReport m = traction.update(cmd, permissions);
  const CannonReport c = cannon.update(cmd, permissions);
  const CentralSnapshot current = central.observe(permissions, s, m, c);
  if (millis() - last_fast_telemetry_ms >= 50) {
    communication.sendFastTelemetry(current, m, c);
    last_fast_telemetry_ms = millis();
  }
  if (millis() - last_telemetry_ms >= 1000) {
    communication.sendTelemetry(current, s, m, c);
    last_telemetry_ms = millis();
  }
  delay(1);
}


// ===== SUBSISTEMA CENTRAL =====
#include "central.h"

#include <cmath>

CentralSnapshot Central::update(const Command &cmd, bool connected,
                                const SafetyReport &safety) {
  CentralSnapshot state;
  state.connected = connected;
  if (connected && cmd.valid) auto_mode_ = cmd.auto_mode;
  state.auto_mode = auto_mode_;

  // A central apenas atualiza estados e distribui permissões. Não toca em GPIO.
  if (connected && cmd.valid && cmd.calibrating) {
    armed_ = false;
    rearm_released_ = false;
    state.reason = "calibration_servos_only";
  } else if (!connected || !cmd.valid) {
    armed_ = false;
    rearm_released_ = false;
    state.reason = "link_lost";
  } else if (cmd.stop || cmd.emergency) {
    armed_ = false;
    rearm_released_ = !cmd.rearm;
    state.reason = "operator_stop";
  } else if (auto_mode_ && !cmd.vision_valid) {
    armed_ = false;
    rearm_released_ = !cmd.rearm;
    state.reason = "vision_unavailable";
  } else if (cmd.person_detected) {
    armed_ = false;
    rearm_released_ = !cmd.rearm;
    state.reason = "person_detected";
  } else if (!armed_) {
    // Exige soltar e apertar REARMAR após qualquer bloqueio, além de joysticks neutros.
    if (!cmd.rearm) rearm_released_ = true;
    const bool neutral = std::fabs(cmd.drive_x) < .05f && std::fabs(cmd.drive_y) < .05f
                      && !cmd.jet_enable;
    if (cmd.rearm && !last_rearm_ && rearm_released_ && neutral) armed_ = true;
    state.reason = armed_ ? "ready" : "awaiting_rearm";
  } else {
    state.reason = "ready";
  }
  state.armed = armed_;
  last_rearm_ = cmd.rearm;
  // Sem imagem, o operador ainda pode conduzir manualmente. A visao continua
  // obrigatoria para o modo autonomo; parada, rearme e enlace valem em ambos.
  state.safe = connected && cmd.valid && !cmd.calibrating &&
               (!auto_mode_ || cmd.vision_valid) &&
               !cmd.person_detected && !cmd.stop;
  state.allow_motion = state.safe && armed_ && !cmd.brake;
  state.allow_jet = state.safe && armed_ && cmd.water_on &&
                    (!auto_mode_ || cmd.target_valid);
  // >35 °C é alerta conforme C2; não vira bloqueio global sem requisito expresso.
  (void)safety;
  return state;
}

CentralSnapshot Central::observe(const CentralSnapshot &current, const SafetyReport &safety,
                                 const MotionReport &motion, const CannonReport &cannon) {
  // Estados publicados pelos módulos responsáveis; nenhuma escrita de hardware.
  CentralSnapshot state = current;
  state.motion_moving = motion.moving;
  state.cool_internal_on = safety.cool_internal_commanded;
  state.cool_external_on = safety.cool_external_commanded;
  state.jet_on = cannon.jet_commanded;
  state.alert_internal = safety.alert_internal;
  state.alert_external = safety.alert_external;
  return state;
}


// ===== SUBSISTEMA MOTION =====
#include "motion.h"
#include "pwm_compat.h"
#include "pins.h"

#include <cmath>

namespace {
bool motorPinsReady() {
  return (BLAZE_DRIVE_KIND == 1 || BLAZE_DRIVE_KIND == 2) &&
          (BLAZE_DRIVE_DRIVER_KIND >= 1 && BLAZE_DRIVE_DRIVER_KIND <= 3) &&
         pins::left_rpwm >= 0 && pins::left_lpwm >= 0 &&
         pins::right_rpwm >= 0 && pins::right_lpwm >= 0 &&
         (BLAZE_DRIVE_DRIVER_KIND != 3 ||
          (pins::left_ren >= 0 && pins::right_ren >= 0));
}
}

void Motion::begin() {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS || !motorPinsReady()) return;
  if (BLAZE_DRIVE_DRIVER_KIND == 3) {
    // L298N: IN1..IN4 determinam direção; ENA/ENB recebem PWM de velocidade.
    for (int pin : {pins::left_rpwm, pins::left_lpwm,
                    pins::right_rpwm, pins::right_lpwm}) {
      digitalWrite(pin, LOW); pinMode(pin, OUTPUT);
    }
    blazePwmAttach(pins::left_ren, 0, 16000, 8);
    blazePwmAttach(pins::right_ren, 1, 16000, 8);
  } else {
    blazePwmAttach(pins::left_rpwm, 0, 16000, 8);
    blazePwmAttach(pins::left_lpwm, 1, 16000, 8);
    blazePwmAttach(pins::right_rpwm, 2, 16000, 8);
    blazePwmAttach(pins::right_lpwm, 3, 16000, 8);
  }
  motor(pins::left_rpwm, pins::left_lpwm, 0, 1, 0);
  motor(pins::right_rpwm, pins::right_lpwm, 2, 3, 0);
  // Só o BTS7960 usa R_EN/L_EN. O DRV8833 recebe IN1/IN2 nos canais PWM.
  if (BLAZE_DRIVE_DRIVER_KIND == 1) {
    for (int en : {pins::left_ren, pins::left_len, pins::right_ren, pins::right_len}) {
      if (en >= 0) { pinMode(en, OUTPUT); digitalWrite(en, HIGH); }
    }
  }
}

void Motion::motor(int rpwm, int lpwm, unsigned channel_a, unsigned channel_b, float speed) {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS || !motorPinsReady()) return;
  if (BLAZE_DRIVE_DRIVER_KIND == 3) {
    const bool left = channel_a == 0;
    const int enable = left ? pins::left_ren : pins::right_ren;
    // Desabilite a ponte antes de inverter sentido; zero desliga as duas saídas.
    blazePwmWrite(enable, left ? 0 : 1, 0);
    digitalWrite(rpwm, speed > 0 ? HIGH : LOW);
    digitalWrite(lpwm, speed < 0 ? HIGH : LOW);
    blazePwmWrite(enable, left ? 0 : 1,
                  unsigned(255.f * clampf(std::fabs(speed), 0.f, 1.f)));
    return;
  }
  // BTS7960 e DRV8833: uma entrada de direção recebe PWM, a outra fica baixa.
  blazePwmWrite(rpwm, channel_a, speed > 0 ? unsigned(255.f * speed) : 0);
  blazePwmWrite(lpwm, channel_b, speed < 0 ? unsigned(-255.f * speed) : 0);
}

MotionReport Motion::update(const Command &cmd, const CentralSnapshot &state) {
  MotionReport report;
  report.configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS && motorPinsReady();
  const unsigned long now = millis();
  const float dt = previous_ms_ ? clampf((now - previous_ms_) / 1000.f, 0.f, .1f) : .02f;
  previous_ms_ = now;
  float target_left = 0, target_right = 0;
  if (report.configured && state.allow_motion) {
    // Joystick 1: frente/trás + giro, sem cálculo na central.
    const TrackTargets targets = mixDrive(cmd.drive_x, cmd.drive_y);
    target_left = targets.left;
    target_right = targets.right;
    if (std::fabs(target_left) < .08f) target_left = 0;
    if (std::fabs(target_right) < .08f) target_right = 0;
    const float step = 3.f * dt;  // rampa inicial de ensaio, ajustar após testes.
    left_ += clampf(target_left - left_, -step, step);
    right_ += clampf(target_right - right_, -step, step);
  } else {
    // Parada/bloqueio dispensam rampa: zerar saídas imediatamente.
    left_ = right_ = 0;
  }
  motor(pins::left_rpwm, pins::left_lpwm, 0, 1, pins::invert_left ? -left_ : left_);
  motor(pins::right_rpwm, pins::right_lpwm, 2, 3, pins::invert_right ? -right_ : right_);
  report.left_commanded = left_;
  report.right_commanded = right_;
  report.moving = std::fabs(left_) > .03f || std::fabs(right_) > .03f;
  return report;
}

void Motion::diagnostic(float left, float right) {
  // Limite de 25% para verificação individual sem carga.
  left_ = clampf(left, -.25f, .25f);
  right_ = clampf(right, -.25f, .25f);
  motor(pins::left_rpwm, pins::left_lpwm, 0, 1, pins::invert_left ? -left_ : left_);
  motor(pins::right_rpwm, pins::right_lpwm, 2, 3, pins::invert_right ? -right_ : right_);
}


// ===== SUBSISTEMA CANNON_JET =====
#include "cannon_jet.h"
#include "pins.h"
#include "pwm_compat.h"

namespace {
constexpr float SERVO_RATE_DEG_S = 65.f;
constexpr float SERVO_ACCEL_DEG_S2 = 220.f;
constexpr float SERVO_TARGET_DEADBAND_DEG = .35f;

void followServoTarget(float &position, float &velocity, float target, float dt) {
  const float error = target - position;
  if (std::fabs(error) <= SERVO_TARGET_DEADBAND_DEG && std::fabs(velocity) < 5.f) {
    velocity = 0.f;
    return;
  }
  const float braking_speed = std::sqrt(2.f * SERVO_ACCEL_DEG_S2 * std::fabs(error));
  const float desired = (error < 0.f ? -1.f : 1.f) *
                        std::fmin(SERVO_RATE_DEG_S, braking_speed);
  const float dv = SERVO_ACCEL_DEG_S2 * dt;
  velocity += clampf(desired - velocity, -dv, dv);
  const float step = velocity * dt;
  if ((error >= 0.f && step >= error) || (error <= 0.f && step <= error)) {
    position = target;
    velocity = 0.f;
  } else {
    position = clampf(position + step, 0.f, 180.f);
  }
}

void relay(int pin, bool on) {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS || pin < 0) return;
  digitalWrite(pin, (on != pins::relay_active_low) ? HIGH : LOW);
}
}

void CannonJet::begin() {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS) return;
  if (BLAZE_CANNON_KIND == 1 && pins::servo_pan >= 0) blazePwmAttach(pins::servo_pan, 4, 50, 16);
  if (BLAZE_CANNON_KIND == 1 && pins::servo_tilt >= 0) blazePwmAttach(pins::servo_tilt, 5, 50, 16);
  if (pins::servo_camera_pan >= 0) blazePwmAttach(pins::servo_camera_pan, 6, 50, 16);
  if (pins::servo_focus >= 0) blazePwmAttach(pins::servo_focus, 7, 50, 16);
  focus_angle_ = BLAZE_FOCUS_DISPERSED_DEG;
  servo(pins::servo_pan, 4, 90);
  servo(pins::servo_tilt, 5, 90);
  servo(pins::servo_camera_pan, 6, 90);
  servo(pins::servo_focus, 7, focus_angle_);
  if (pins::relay_jet >= 0 && BLAZE_ENABLE_JET_OUTPUT) {
    // Defina primeiro o nível desligado; só depois habilite a saída.
    digitalWrite(pins::relay_jet, pins::relay_active_low ? HIGH : LOW);
    pinMode(pins::relay_jet, OUTPUT);
    relay(pins::relay_jet, false);
  }
}

void CannonJet::servo(int pin, unsigned channel, float angle) {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS || pin < 0) return;
  if (BLAZE_CANNON_KIND != 1 && (channel == 4 || channel == 5)) return;
  const unsigned index = channel - 4;
  if (index >= 4) return;
  const unsigned long now = millis();
  // O LEDC mantém o último pulso. Evita escrever setpoints quase idênticos
  // milhares de vezes por segundo, sem retirar o torque de sustentação.
  if (std::isfinite(last_servo_angle_[index]) &&
      (now - last_servo_write_ms_[index] < 20 ||
       std::fabs(angle - last_servo_angle_[index]) < .55f)) return;
  // LEDC 50 Hz/16 bits; faixa estendida para SG90 e MG996R.
  // Um comando logico de 180 graus nao garante curso fisico de 180 graus.
  const float pulse_min_us = 500.f;
  const float pulse_max_us = 2500.f;
  const float pulse = pulse_min_us + clampf(angle, 0, 180) *
                      (pulse_max_us - pulse_min_us) / 180.f;
  const unsigned duty = unsigned(pulse * 65535.f / 20000.f);
  blazePwmWrite(pin, channel, duty);
  last_servo_angle_[index] = clampf(angle, 0.f, 180.f);
  last_servo_write_ms_[index] = now;
}

CannonReport CannonJet::update(const Command &cmd, const CentralSnapshot &state) {
  CannonReport report;
  const unsigned long now = millis();
  const float dt = previous_ms_ ? clampf((now - previous_ms_) / 1000.f, 0.f, .1f) : .02f;
  previous_ms_ = now;
  if (cmd.valid && state.connected && !cmd.stop && !cmd.emergency &&
      BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::servo_camera_pan >= 0) {
    // Setpoint de posição. O feedback interno do servo não é medido pelo ESP.
    const float demand = clampf(cmd.camera_pan, cmd.camera_min, cmd.camera_max);
    if (std::fabs(demand - camera_target_) >= SERVO_TARGET_DEADBAND_DEG)
      camera_target_ = demand;
  }
  if (!cmd.valid || !state.connected || cmd.stop || cmd.emergency) {
    // Interrompe trajetórias pendentes, mesmo se um snapshot de permissões
    // estiver temporariamente atrasado em relação ao comando de parada.
    pan_target_ = pan_; tilt_target_ = tilt_; camera_target_ = camera_pan_;
    pan_velocity_ = tilt_velocity_ = camera_velocity_ = 0.f;
  } else if (BLAZE_CANNON_KIND == 1 && cmd.calibrating &&
      BLAZE_ENABLE_PHYSICAL_OUTPUTS) {
    pan_target_ = clampf(cmd.calibration_pan, cmd.pan_min, cmd.pan_max);
    tilt_target_ = clampf(cmd.calibration_tilt, cmd.tilt_min, cmd.tilt_max);
  } else if (BLAZE_CANNON_KIND == 1 && state.allow_motion) {
    if (state.auto_mode && cmd.target_valid) {
      const float pan = clampf(cmd.auto_pan,cmd.pan_min,cmd.pan_max);
      const float tilt = clampf(cmd.auto_tilt,cmd.tilt_min,cmd.tilt_max);
      if (std::fabs(pan - pan_target_) >= SERVO_TARGET_DEADBAND_DEG) pan_target_ = pan;
      if (std::fabs(tilt - tilt_target_) >= SERVO_TARGET_DEADBAND_DEG) tilt_target_ = tilt;
    } else if (!state.auto_mode && cmd.manual_target_valid) {
      const float pan = clampf(cmd.manual_pan, cmd.pan_min, cmd.pan_max);
      const float tilt = clampf(cmd.manual_tilt, cmd.tilt_min, cmd.tilt_max);
      if (std::fabs(pan - pan_target_) >= SERVO_TARGET_DEADBAND_DEG) pan_target_ = pan;
      if (std::fabs(tilt - tilt_target_) >= SERVO_TARGET_DEADBAND_DEG) tilt_target_ = tilt;
    } else if (!state.auto_mode) {
      // O stick determina taxa angular comandada, não posição instantânea.
      pan_target_ = clampf(pan_target_ + cmd.cannon_x * cmd.cannon_rate_deg_s * dt,
                           cmd.pan_min, cmd.pan_max);
      tilt_target_ = clampf(tilt_target_ - cmd.cannon_y * cmd.cannon_rate_deg_s * dt,
                            cmd.tilt_min, cmd.tilt_max);
    } else {
      // O alvo desapareceu no modo automático: não siga rumo ao último fogo.
      pan_target_ = pan_; tilt_target_ = tilt_;
      pan_velocity_ = tilt_velocity_ = 0.f;
    }
  } else {
    // Pessoa detectada ou outro intertravamento: canhão permanece na
    // posição já comandada, sem completar uma trajetória antiga.
    pan_target_ = pan_; tilt_target_ = tilt_;
    pan_velocity_ = tilt_velocity_ = 0.f;
  }
  followServoTarget(pan_, pan_velocity_, pan_target_, dt);
  followServoTarget(tilt_, tilt_velocity_, tilt_target_, dt);
  followServoTarget(camera_pan_, camera_velocity_, camera_target_, dt);
  servo(pins::servo_pan, 4, pan_);
  servo(pins::servo_tilt, 5, tilt_);
  servo(pins::servo_camera_pan, 6, camera_pan_);
  if (cmd.valid && state.connected && state.allow_motion &&
      BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::servo_focus >= 0) {
    const float demand = clampf(cmd.focus, 0.f, 1.f);
    focus_angle_ = BLAZE_FOCUS_DISPERSED_DEG +
                   demand * (BLAZE_FOCUS_FOCUSED_DEG - BLAZE_FOCUS_DISPERSED_DEG);
  }
  servo(pins::servo_focus, 7, focus_angle_);
  report.focus_angle_commanded = focus_angle_;
  report.focus_servo_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::servo_focus >= 0;
  report.pan_commanded = std::isfinite(last_servo_angle_[0]) ? last_servo_angle_[0] : pan_;
  report.tilt_commanded = std::isfinite(last_servo_angle_[1]) ? last_servo_angle_[1] : tilt_;
  report.camera_pan_commanded = std::isfinite(last_servo_angle_[2]) ? last_servo_angle_[2] : camera_pan_;
  // Os servos RC comuns não transmitem posição física ao ESP32.
  report.pan_feedback_raw = -1;
  report.tilt_feedback_raw = -1;
  report.camera_feedback_raw = -1;
  report.camera_servo_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS &&
                                   pins::servo_camera_pan >= 0;
  report.servos_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS &&
                             BLAZE_CANNON_KIND == 1 &&
                             pins::servo_pan >= 0 && pins::servo_tilt >= 0;
  report.jet_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS && BLAZE_CANNON_KIND == 1 &&
                          BLAZE_ENABLE_JET_OUTPUT &&
                          pins::relay_jet >= 0;
  // Aguarde o alvo teórico e a plataforma alcançarem seus setpoints limitados
  // antes de permitir o jato autônomo. Posição PWM ainda não é feedback físico.
  const bool theoretical_alignment = !state.auto_mode ||
      (fabsf(report.pan_commanded - clampf(cmd.auto_pan,cmd.pan_min,cmd.pan_max)) <= 2.f &&
       fabsf(report.tilt_commanded - clampf(cmd.auto_tilt,cmd.tilt_min,cmd.tilt_max)) <= 2.f &&
       fabsf(report.camera_pan_commanded - clampf(cmd.camera_pan,cmd.camera_min,cmd.camera_max)) <= 2.f);
  const bool requested = BLAZE_CANNON_KIND == 1 && state.allow_jet &&
                         cmd.jet_enable && theoretical_alignment;
  report.jet_virtual = requested;  // pedido aplicado à simulação da chama impressa
  report.jet_commanded = requested && report.jet_configured;
  if (BLAZE_ENABLE_JET_OUTPUT) relay(pins::relay_jet, report.jet_commanded);
  return report;
}

void CannonJet::panDiagnostic(float angle) {
  pan_ = pan_target_ = clampf(angle, 0, 180);
  pan_velocity_ = 0;
  // O diagnóstico roda a cada 10 ms: não reprograme o mesmo duty em todo ciclo.
  // O hardware LEDC continua emitindo o pulso de sustentação sozinho.
  servo(pins::servo_pan, 4, pan_);
}

void CannonJet::tiltDiagnostic(float angle) {
  tilt_ = tilt_target_ = clampf(angle, 0, 180);
  tilt_velocity_ = 0;
  servo(pins::servo_tilt, 5, tilt_);
}

void CannonJet::cameraDiagnostic(float angle) {
  camera_pan_ = camera_target_ = clampf(angle, 0, 180);
  camera_velocity_ = 0;
  servo(pins::servo_camera_pan, 6, camera_pan_);
}

void CannonJet::focusDiagnostic(float angle) {
  focus_angle_ = clampf(angle, 0.f, 180.f);
  servo(pins::servo_focus, 7, focus_angle_);
}


// ===== SUBSISTEMA SENSING_SAFETY =====
#include "sensing_safety.h"
#include "pins.h"

#include <cmath>

namespace {
constexpr float TEMP_ON = 30.0f, TEMP_OFF = 28.0f;
constexpr float TEMP_ALERT = 35.0f;
// Valores provisórios para ensaio; C2 ainda não definiu limiar de umidade.
constexpr float HUMIDITY_ON = 80.0f, HUMIDITY_OFF = 75.0f;
constexpr unsigned long SENSOR_PERIOD_MS = 3000;
}

SensingSafety::SensingSafety() = default;

void SensingSafety::relay(int pin, bool on) {
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS || pin < 0) return;
  digitalWrite(pin, (on != pins::relay_active_low) ? HIGH : LOW);
}

void SensingSafety::begin() {
  if (pins::dht_internal >= 0)
    internal_.setup(pins::dht_internal,
                    BLAZE_DHT_INTERNAL_TYPE == 22 ? DHTesp::DHT22 : DHTesp::DHT11);
  if (pins::dht_external >= 0)
    external_.setup(pins::dht_external,
                    BLAZE_DHT_EXTERNAL_TYPE == 22 ? DHTesp::DHT22 : DHTesp::DHT11);
  if (!BLAZE_ENABLE_PHYSICAL_OUTPUTS) return;
  for (int pin : {pins::relay_cool_internal, pins::relay_cool_external}) {
    if (pin < 0) continue;
    digitalWrite(pin, pins::relay_active_low ? HIGH : LOW);
    pinMode(pin, OUTPUT);
    relay(pin, false);
  }
}

void SensingSafety::sample() {
  // Alterna os sensores: cada DHT e lido uma vez a cada 3 segundos.
  // Nao use delay(2000): tracao e canhao precisam continuar no ciclo de 50 ms.
  if (last_sample_ && millis() - last_sample_ < SENSOR_PERIOD_MS / 2) return;
  last_sample_ = millis();
  if (!sample_external_next_ && pins::dht_internal >= 0) {
    const TempAndHumidity reading = internal_.getTempAndHumidity();
    report_.temp_internal_raw = reading.temperature;
    report_.humidity_internal_raw = reading.humidity;
    const int error = int(internal_.getStatus());
    const bool limits = BLAZE_DHT_INTERNAL_TYPE == 11
        ? (reading.temperature >= 0.f && reading.temperature <= 50.f &&
           reading.humidity >= 20.f && reading.humidity <= 90.f)
        : (reading.temperature >= -40.f && reading.temperature <= 125.f &&
           reading.humidity >= 0.f && reading.humidity <= 100.f);
    report_.internal_valid = error == 0 && std::isfinite(reading.temperature) &&
                             std::isfinite(reading.humidity) && limits;
    report_.internal_error = error ? error : (report_.internal_valid ? 0 : 3);
    report_.temp_internal = report_.internal_valid ? reading.temperature : NAN;
    report_.humidity_internal = report_.internal_valid ? reading.humidity : NAN;
  }
  if (sample_external_next_ && pins::dht_external >= 0) {
    const TempAndHumidity reading = external_.getTempAndHumidity();
    report_.temp_external_raw = reading.temperature;
    report_.humidity_external_raw = reading.humidity;
    const int error = int(external_.getStatus());
    const bool limits = BLAZE_DHT_EXTERNAL_TYPE == 11
        ? (reading.temperature >= 0.f && reading.temperature <= 50.f &&
           reading.humidity >= 20.f && reading.humidity <= 90.f)
        : (reading.temperature >= -40.f && reading.temperature <= 125.f &&
           reading.humidity >= 0.f && reading.humidity <= 100.f);
    report_.external_valid = error == 0 && std::isfinite(reading.temperature) &&
                             std::isfinite(reading.humidity) && limits;
    report_.external_error = error ? error : (report_.external_valid ? 0 : 3);
    report_.temp_external = report_.external_valid ? reading.temperature : NAN;
    report_.humidity_external = report_.external_valid ? reading.humidity : NAN;
  }
  sample_external_next_ = !sample_external_next_;
}

SafetyReport SensingSafety::update(const Command &cmd, bool pc_linked) {
  sample();  // continua localmente mesmo sem Wi-Fi/PC.
  if (pc_linked && cmd.valid && cmd.calibrating) {
    report_.cool_internal_commanded = false;
    report_.cool_external_commanded = false;
    relay(pins::relay_cool_internal, false);
    relay(pins::relay_cool_external, false);
    return report_;
  }
  if (report_.internal_valid) {
    if (report_.temp_internal >= TEMP_ON) internal_temp_on_ = true;
    if (report_.temp_internal <= TEMP_OFF) internal_temp_on_ = false;
    if (report_.humidity_internal >= HUMIDITY_ON) internal_humidity_on_ = true;
    if (report_.humidity_internal <= HUMIDITY_OFF) internal_humidity_on_ = false;
  } else {
    // Falha do sensor é reportada; saída automática depende da política física definida.
    internal_temp_on_ = internal_humidity_on_ = false;
  }
  if (report_.external_valid) {
    if (report_.temp_external >= TEMP_ON) external_temp_on_ = true;
    if (report_.temp_external <= TEMP_OFF) external_temp_on_ = false;
  } else external_temp_on_ = false;

  report_.alert_internal = report_.internal_valid && report_.temp_internal > TEMP_ALERT;
  report_.alert_external = report_.external_valid && report_.temp_external > TEMP_ALERT;
  const bool manual = pc_linked && cmd.valid && cmd.cool_manual;
  report_.cool_internal_commanded = internal_temp_on_ || internal_humidity_on_ ||
                                    (manual && cmd.cool_internal);
  report_.cool_external_commanded = external_temp_on_ || (manual && cmd.cool_external);
  report_.cool_internal_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::relay_cool_internal >= 0;
  report_.cool_external_configured = BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::relay_cool_external >= 0;
  relay(pins::relay_cool_internal, report_.cool_internal_commanded);
  relay(pins::relay_cool_external, report_.cool_external_commanded);
  return report_;
}

void SensingSafety::diagnostic(bool internal_on, bool external_on) {
  relay(pins::relay_cool_internal, internal_on);
  relay(pins::relay_cool_external, external_on);
}


// ===== SUBSISTEMA NET_LINK =====
#include "net_link.h"

#include <ESPmDNS.h>
#include <cmath>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#define BLAZE_WIFI_SSID ""
#define BLAZE_WIFI_PASSWORD ""
#define BLAZE_AP_SSID ""
#define BLAZE_AP_PASSWORD ""
#define BLAZE_BT_NAME ""
#define BLAZE_BT_PIN ""
#endif

namespace {
bool number(JsonVariantConst v, float &out, float min, float max) {
  if (!(v.is<float>() || v.is<double>() || v.is<int>())) return false;
  out = v.as<float>();
  return std::isfinite(out) && out >= min && out <= max;
}
bool flag(JsonVariantConst v, bool &out) {
  if (!v.is<bool>()) return false;
  out = v.as<bool>();
  return true;
}
void finiteOrNull(JsonDocument &doc, const char *key, float value) {
  if (std::isfinite(value)) doc[key] = value;
  else doc[key] = nullptr;
}
}

void NetLink::connectWifi() {
  if (BLAZE_WIFI_SSID[0] == '\0') return;
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - last_wifi_attempt_ms_ < 2000 && last_wifi_attempt_ms_ != 0) return;
  last_wifi_attempt_ms_ = millis();
  WiFi.disconnect();
  WiFi.begin(BLAZE_WIFI_SSID, BLAZE_WIFI_PASSWORD);
}

void NetLink::begin() {
  // AP local independe de roteador e mantém o mesmo servidor TCP na porta 8765.
  WiFi.mode(BLAZE_WIFI_SSID[0] ? WIFI_AP_STA : WIFI_AP);
  if (BLAZE_AP_SSID[0] && BLAZE_AP_PASSWORD[0]) {
    WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1),
                      IPAddress(255, 255, 255, 0));
    if (WiFi.softAP(BLAZE_AP_SSID, BLAZE_AP_PASSWORD)) {
      Serial.print("BLAZE AP: "); Serial.println(BLAZE_AP_SSID);
    } else {
      Serial.println("BLAZE AP indisponivel");
    }
  }
  server_.begin();
  server_started_ = true;
  WiFi.setAutoReconnect(true);
  connectWifi();
}

bool NetLink::linked() {
  return active_transport_ != 0 && last_valid_ms_ != 0 &&
         millis() - last_valid_ms_ <= 750 &&
         (active_transport_ == 2 ||
          (active_transport_ == 1 && client_ && client_.connected()));
}

bool NetLink::acceptSerialLine(const char *line) {
  if (active_transport_ != 2 && linked()) return false;
  Command parsed;
  if (!parse(line, parsed)) return false;
  if (active_transport_ != 2) command_ = Command{};  // troca exige novo rearme
  active_transport_ = 2;
  command_ = parsed;
  last_valid_ms_ = millis();
  client_.stop();
  return true;
}

bool NetLink::parse(const char *line, Command &output) {
  StaticJsonDocument<2048> doc;
  if (deserializeJson(doc, line)) return false;
  if (doc["type"] != "control") return false;
  const char *mode = doc["mode"] | "";
  if (strcmp(mode, "manual") != 0 && strcmp(mode, "auto") != 0) return false;
  Command tmp;
  if (doc["seq"].is<unsigned long>()) tmp.seq = doc["seq"].as<unsigned long>();
  tmp.auto_mode = strcmp(mode, "auto") == 0;
  if (!number(doc["drive_x"], tmp.drive_x, -1, 1) ||
      !number(doc["drive_y"], tmp.drive_y, -1, 1) ||
      !number(doc["cannon_x"], tmp.cannon_x, -1, 1) ||
      !number(doc["cannon_y"], tmp.cannon_y, -1, 1) ||
      !number(doc["cannon_rate_deg_s"], tmp.cannon_rate_deg_s, 1, 360) ||
      !number(doc["camera_rate_deg_s"], tmp.camera_rate_deg_s, 1, 360) ||
      !number(doc["auto_rate_deg_s"], tmp.auto_rate_deg_s, 1, 360) ||
      !number(doc["auto_pan"], tmp.auto_pan, 0, 180) ||
      !number(doc["auto_tilt"], tmp.auto_tilt, 0, 180) ||
      !number(doc["manual_pan"], tmp.manual_pan, 0, 180) ||
      !number(doc["manual_tilt"], tmp.manual_tilt, 0, 180) ||
      !number(doc["camera_pan"], tmp.camera_pan, 0, 180) ||
      !number(doc["calibration_pan"], tmp.calibration_pan, 0, 180) ||
      !number(doc["calibration_tilt"], tmp.calibration_tilt, 0, 180) ||
      !number(doc["camera_min"], tmp.camera_min, 0, 180) ||
      !number(doc["camera_max"], tmp.camera_max, 0, 180) ||
      !number(doc["pan_min"], tmp.pan_min, 0, 180) ||
      !number(doc["pan_max"], tmp.pan_max, 0, 180) ||
      !number(doc["tilt_min"], tmp.tilt_min, 0, 180) ||
      !number(doc["tilt_max"], tmp.tilt_max, 0, 180) ||
      !number(doc["pressure"], tmp.pressure, 0, 1) ||
      !number(doc["focus"], tmp.focus, 0, 1)) return false;
  if (tmp.camera_min >= tmp.camera_max || tmp.pan_min >= tmp.pan_max ||
      tmp.tilt_min >= tmp.tilt_max ||
      doc.overflowed()) return false;
  if (!flag(doc["vision_valid"], tmp.vision_valid) ||
      !flag(doc["manual_target_valid"], tmp.manual_target_valid) ||
      !flag(doc["target_valid"], tmp.target_valid) ||
      !flag(doc["person_detected"], tmp.person_detected) ||
      !flag(doc["cool_manual"], tmp.cool_manual) ||
      !flag(doc["cool_internal"], tmp.cool_internal) ||
      !flag(doc["cool_external"], tmp.cool_external) ||
      !flag(doc["jet_enable"], tmp.jet_enable) ||
      !flag(doc["leds_on"], tmp.leds_on) ||
      !flag(doc["stop"], tmp.stop) ||
      !flag(doc["rearm"], tmp.rearm)) return false;
  if (!flag(doc["calibrating"], tmp.calibrating) ||
      !flag(doc["water_on"], tmp.water_on) ||
      !flag(doc["brake"], tmp.brake) ||
      !flag(doc["emergency"], tmp.emergency)) return false;
  tmp.valid = true;
  output = tmp;
  return true;
}

void NetLink::poll() {
  if (!linked()) {
    command_ = Command{};
    active_transport_ = 0;
    last_valid_ms_ = 0;
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (mdns_started_) {
      MDNS.end();
      mdns_started_ = false;
    }
    connectWifi();
  } else if (!mdns_started_ &&
             (!last_mdns_attempt_ms_ || millis() - last_mdns_attempt_ms_ > 2000)) {
    last_mdns_attempt_ms_ = millis();
    if (MDNS.begin("blaze-esp32")) {
      MDNS.addService("blaze", "tcp", 8765);
      mdns_started_ = true;
    }
    Serial.print("BLAZE ESP32 IP: "); Serial.println(WiFi.localIP());
  }
  if (!client_ || !client_.connected()) {
    client_.stop();
    client_ = server_.available();
    if (client_) client_.setNoDelay(true);
    used_ = 0;
    if (active_transport_ == 1) {
      last_valid_ms_ = 0;
      command_ = Command{};
      active_transport_ = 0;
    }
  }
  if (!client_ || !client_.connected()) return;
  int budget = 1536; // mantém o loop de segurança responsivo sob entrada excessiva.
  while (client_.available() && budget-- > 0) {
    const char c = char(client_.read());
    if (c == '\n') {
      line_[used_] = '\0';
      Command parsed;
      if (parse(line_, parsed) && (active_transport_ == 1 || !linked())) {
        if (active_transport_ != 1) command_ = Command{};
        active_transport_ = 1;
        command_ = parsed;
        last_valid_ms_ = millis();
      }
      used_ = 0;
    } else if (c != '\r' && used_ < sizeof(line_) - 1) {
      line_[used_++] = c;
    } else if (used_ >= sizeof(line_) - 1) {
      used_ = 0;  // descarta mensagem longa ou truncada.
    }
  }
}

void NetLink::sendJsonLine(const JsonDocument &doc) {
  // ArduinoJson escreve um byte por vez quando recebe um Stream. Com
  // TCP_NODELAY, isso gera centenas de pacotes Wi-Fi para cada telemetria.
  // Formar uma linha completa e transmiti-la em uma única escrita TCP.
  static char frame[3072];  // evita estourar a pilha da tarefa Arduino
  const size_t length = measureJson(doc);
  if (doc.overflowed() || length + 1 >= sizeof(frame)) return;
  const size_t written = serializeJson(doc, frame, sizeof(frame));
  if (written != length) return;
  frame[written] = '\n';
  if (active_transport_ == 2) {
    Serial.write(reinterpret_cast<const uint8_t *>(frame), written + 1);
  } else if (active_transport_ == 1 && client_ && client_.connected()) {
    client_.write(reinterpret_cast<const uint8_t *>(frame), written + 1);
  }
}

void NetLink::sendTelemetry(const CentralSnapshot &state, const SafetyReport &s,
                            const MotionReport &m, const CannonReport &c) {
  if (!linked()) return;
  StaticJsonDocument<2048> doc;
  doc["type"] = "telemetry";
  doc["protocol_version"] = 4;
  doc["seq"] = command_.seq;
  doc["fast"] = false;
  doc["connected"] = state.connected;
  doc["armed"] = state.armed;
  doc["mode"] = state.auto_mode ? "auto" : "manual";
  doc["safety"] = state.safe ? "safe" : "unsafe";
  doc["motion"] = state.motion_moving ? "moving" : "stopped";
  doc["reason"] = state.reason;
  finiteOrNull(doc, "temp_internal", s.temp_internal);
  finiteOrNull(doc, "humidity_internal", s.humidity_internal);
  finiteOrNull(doc, "temp_external", s.temp_external);
  finiteOrNull(doc, "humidity_external", s.humidity_external);
  doc["sensor_internal_valid"] = s.internal_valid;
  doc["sensor_external_valid"] = s.external_valid;
  doc["sensor_internal_error"] = s.internal_error;
  doc["sensor_external_error"] = s.external_error;
  finiteOrNull(doc, "temp_internal_raw", s.temp_internal_raw);
  finiteOrNull(doc, "humidity_internal_raw", s.humidity_internal_raw);
  finiteOrNull(doc, "temp_external_raw", s.temp_external_raw);
  finiteOrNull(doc, "humidity_external_raw", s.humidity_external_raw);
  doc["sensor_internal_type"] = BLAZE_DHT_INTERNAL_TYPE;
  doc["sensor_external_type"] = BLAZE_DHT_EXTERNAL_TYPE;
  doc["alert_internal"] = state.alert_internal;
  doc["alert_external"] = state.alert_external;
  doc["cool_internal_commanded"] = state.cool_internal_on;
  doc["cool_external_commanded"] = state.cool_external_on;
  doc["cool_internal_configured"] = s.cool_internal_configured;
  doc["cool_external_configured"] = s.cool_external_configured;
  doc["drive_left_commanded"] = m.left_commanded;
  doc["drive_right_commanded"] = m.right_commanded;
  doc["drive_configured"] = m.configured;
  doc["drive_kind"] = BLAZE_DRIVE_KIND;
  doc["cannon_kind"] = BLAZE_CANNON_KIND;
  doc["servo_pan_commanded"] = c.pan_commanded;
  doc["servo_tilt_commanded"] = c.tilt_commanded;
  doc["camera_pan_commanded"] = c.camera_pan_commanded;
  doc["servo_pan_pulse_us"] = 500.f + clampf(c.pan_commanded, 0, 180) * (2000.f / 180.f);
  doc["servo_tilt_pulse_us"] = 500.f + clampf(c.tilt_commanded, 0, 180) * (2000.f / 180.f);
  doc["camera_pan_pulse_us"] = 500.f + clampf(c.camera_pan_commanded, 0, 180) * (2000.f / 180.f);
  doc["servo_pan_feedback_raw"] = c.pan_feedback_raw;
  doc["servo_tilt_feedback_raw"] = c.tilt_feedback_raw;
  doc["camera_pan_feedback_raw"] = c.camera_feedback_raw;
  doc["camera_servo_configured"] = c.camera_servo_configured;
  doc["calibrating"] = command_.calibrating;
  doc["servos_configured"] = c.servos_configured;
  doc["jet_commanded"] = c.jet_commanded;
  doc["jet_virtual"] = c.jet_virtual;
  doc["water_on"] = command_.water_on;
  doc["pressure_requested"] = command_.pressure;
  doc["focus_requested"] = command_.focus;
  doc["focus_angle_commanded"] = c.focus_angle_commanded;
  doc["pressure_actuator_configured"] = false;
  doc["focus_actuator_configured"] = c.focus_servo_configured;
  doc["brake"] = command_.brake;
  doc["emergency"] = command_.emergency;
  doc["setup_name"] = BLAZE_SETUP_NAME;
  doc["setup_signature"] = BLAZE_SETUP_SIGNATURE;
  doc["leds_configured"] = BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::led_status >= 0;
  doc["leds_commanded"] = BLAZE_ENABLE_PHYSICAL_OUTPUTS && pins::led_status >= 0 &&
                           !command_.stop && command_.leds_on;
  doc["jet_configured"] = c.jet_configured;
  sendJsonLine(doc);
}

void NetLink::sendFastTelemetry(const CentralSnapshot &state,
                                const MotionReport &m, const CannonReport &c) {
  if (!linked()) return;
  StaticJsonDocument<768> doc;
  doc["type"] = "telemetry";
  doc["protocol_version"] = 4;
  doc["fast"] = true;
  doc["seq"] = command_.seq;
  doc["mode"] = state.auto_mode ? "auto" : "manual";
  doc["armed"] = state.armed;
  doc["drive_left_commanded"] = m.left_commanded;
  doc["drive_right_commanded"] = m.right_commanded;
  doc["servo_pan_commanded"] = c.pan_commanded;
  doc["servo_tilt_commanded"] = c.tilt_commanded;
  doc["camera_pan_commanded"] = c.camera_pan_commanded;
  doc["servo_pan_feedback_raw"] = c.pan_feedback_raw;
  doc["servo_tilt_feedback_raw"] = c.tilt_feedback_raw;
  doc["camera_pan_feedback_raw"] = c.camera_feedback_raw;
  doc["jet_commanded"] = c.jet_commanded;
  doc["jet_virtual"] = c.jet_virtual;
  doc["setup_signature"] = BLAZE_SETUP_SIGNATURE;
  sendJsonLine(doc);
}
