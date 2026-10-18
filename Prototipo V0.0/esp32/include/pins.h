#pragma once
/* GPIO são números lógicos do ESP32-WROOM-32, não a posição no conector.
 * Consulte o mapa de conexões específico deste pacote antes da montagem.
 * O microservo SG90 do foco usa sinal RC PWM no GPIO14.
 */
#include "setup_generated.h"  // gerado da combinação oficial pela seção 8
#ifndef BLAZE_DRIVE_DRIVER_KIND
#define BLAZE_DRIVE_DRIVER_KIND 1  // builds antigos: BTS7960
#endif

namespace pins {
constexpr int dht_internal = 16;
constexpr int dht_external = 17;

// BTS7960: RPWM/LPWM/EN. DRV8833: AIN1/AIN2 e BIN1/BIN2 nos pares.
// L298N: IN1/IN2 = 25/26, ENA(PWM)=27; IN3/IN4 = 32/33, ENB(PWM)=23.
// Kalatec BLDC: reserva GPIO25/32=SV (via conversor), 26/33=F/R,
// 27/23=EN, somente depois de projetar adaptação elétrica e firmware.
// Ambos usam alimentação de potência externa, nunca fornecida pelo ESP32.
// Para motores 3–6 V, alimentação regulada >=5,5 V e <=6 V conforme motor.
constexpr int left_rpwm = 25;
constexpr int left_lpwm = 26;
constexpr int left_ren = 27;
constexpr int left_len = 27;
constexpr int right_rpwm = 32;
constexpr int right_lpwm = 33;
constexpr int right_ren = 23;
constexpr int right_len = 23;
constexpr bool invert_left = false;   // ajustar após ensaio de sentido pela USB
constexpr bool invert_right = false;

constexpr int servo_pan = 18;
constexpr int servo_tilt = 19;
// Servo de plataforma configurável MG996R/SG90; alimentação externa.
constexpr int servo_camera_pan = 4;
constexpr int servo_focus = 14;
// Dois relés de arrefecimento e o canal da válvula do jato.
constexpr int relay_cool_external = 13;
constexpr int relay_cool_internal = 22;
constexpr int relay_jet = 21;
constexpr int led_status = -1;  // configure o GPIO real do módulo de LEDs antes de habilitar
constexpr bool relay_active_low = true;  // confirme no módulo de relés adquirido
}
