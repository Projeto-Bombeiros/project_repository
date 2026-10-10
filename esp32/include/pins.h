#pragma once
/*
 * Referência: ESP32-WROOM-32 / DevKit esp32dev. Números GPIO, não posição
 * física do conector. Um BTS7960 por motor DC, de 3–6 V ou 12 V.
 * EN de cada BTS7960 usa um GPIO para R_EN e L_EN juntos. BLDC e stepservo
 * aguardam interface própria e ficam bloqueados.
 * Alimentações externas e terra comum constam em docs/conexoes_esp32.md.
 * Teste individualmente cada canal antes de ligar motores/solenóides.
 */
#include "setup_generated.h"  // gerado da combinação oficial pela seção 8

namespace pins {
constexpr int dht_internal = 16;
constexpr int dht_external = 17;

// BTS7960 esquerdo/direito: RPWM/LPWM e EN. Alimentação de potência externa.
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
// MG90S da plataforma da câmera, PWM 50 Hz. Alimentação externa 5 V e GND comum.
constexpr int servo_camera_pan = 4;

// Relé de arrefecimento e relé do jato aparecem no diagrama. O segundo
// arrefecimento exige canal e atuador físico adicionais ainda não definidos.
constexpr int relay_cool_external = 13;
constexpr int relay_cool_internal = 22;
constexpr int relay_jet = 21;
constexpr int led_status = -1;  // configure o GPIO real do módulo de LEDs antes de habilitar
constexpr bool relay_active_low = true;  // confirme no módulo de relés adquirido
}
