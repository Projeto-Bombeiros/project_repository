# Contrato de troca PC ↔ ESP32

O mesmo protocolo funciona pela **USB serial a 115200 baud** e pela **rede local criada pelo ESP32 em 192.168.4.1:8765**: uma linha JSON por mensagem. Selecione `esp.transport` como `usb`, `wifi_local` ou `auto` (USB seguida da rede local). A câmera USB ou o arquivo de vídeo é lido diretamente pelo PC. O firmware deve ser gravado pela USB antes do primeiro teste por Wi-Fi. O PC envia `control` a cada 100 ms e o ESP32 responde `telemetry` a cada 200 ms; depois de 750 ms sem comando válido, a atuação perde autorização e exige rearme após reconectar.

A primeira gravação do firmware requer que o computador reconheça uma porta USB serial, salvo se a placa já tiver firmware gravado por outro método. Se o Windows disser que o dispositivo USB não foi reconhecido, a aplicação não pode criar uma porta COM por software: confira cabo de dados, conexão USB e driver do conversor da placa. O vídeo não atravessa a conexão com o ESP32.

## PC → ESP32 (`control`)

```json
{"type":"control","seq":0,"mode":"manual","drive_x":0.0,"drive_y":0.0,"cannon_x":0.0,"cannon_y":0.0,"cannon_rate_deg_s":90.0,"auto_pan":90.0,"auto_tilt":90.0,"camera_pan":90.0,"calibrating":false,"calibration_pan":90.0,"calibration_tilt":90.0,"vision_valid":false,"target_valid":false,"person_detected":false,"cool_manual":false,"cool_internal":false,"cool_external":false,"jet_enable":false,"water_on":false,"pressure":0,"focus":0,"brake":false,"emergency":false,"leds_on":false,"stop":true,"rearm":false}
```

`drive_x/y` e `cannon_x/y` ficam em [-1,1]. `camera_pan` é o ângulo comandado da plataforma entre 0° e 180°. `auto_pan/tilt` são graus calculados pela visão com os 12 pontos registrados no runtime. `calibrating=true` autoriza somente os três servos; `calibration_pan/tilt` posicionam o canhão com tração, jato e relés bloqueados. `person_detected` é verdadeiro se uma pessoa foi detectada no quadro atual ou na memória curta de detecções. `vision_valid` exige quadro recente **e** detector de pessoas carregado. `jet_enable` comanda o jato virtual na simulação; no combate real depende da liberação física e dos intertravamentos. `rearm` é um pulso produzido após Start por 2 s, aceito somente com joysticks neutros, sem pessoa detectada e com vídeo e conexão válidos. Não há vídeo bruto nessa mensagem.

## ESP32 → PC (`telemetry`)

```json
{"type":"telemetry","connected":true,"armed":false,"mode":"manual","safety":"safe","motion":"stopped","reason":"awaiting_rearm","temp_internal":null,"humidity_internal":null,"temp_external":null,"humidity_external":null,"sensor_internal_valid":false,"sensor_external_valid":false,"cool_internal_commanded":false,"cool_external_commanded":false,"jet_commanded":false,"jet_virtual":false,"drive_left_commanded":0.0,"drive_right_commanded":0.0,"servo_pan_commanded":90.0,"servo_tilt_commanded":90.0,"camera_pan_commanded":90.0,"camera_servo_configured":true,"cool_internal_configured":false,"cool_external_configured":false,"jet_configured":false}
```

`motion` descreve saídas de tração comandadas, pois não há encoder no diagrama. Válvulas e servos não possuem retorno físico no diagrama; `*_commanded` descreve o sinal lógico, não confirma movimento/abertura. Temperaturas e umidades ficam nulas enquanto não houver leitura válida. `reason` explica o bloqueio. Alertas térmicos (>35 °C) aparecem em `alert_internal`/`alert_external`; não causam bloqueio global sem um requisito adicional.

## Prioridades

1. Perda de comando/conexão, parada do operador, pessoa detectada ou visão inválida → tração e jato desabilitados; o canhão conserva posição.
2. Recuperação de conexão não rearma automaticamente. Novo comando com joysticks neutros e `rearm=true` é necessário.
3. O arrefecimento local funciona sem PC. No modo manual, pedidos do operador podem ligá-lo; nunca podem desligar uma necessidade automática por temperatura/umidade.
4. No cenário da chama impressa, apenas a representação do jato e do apagamento é simulada. A saída física do jato depende de configuração explícita adicional e vem desabilitada por padrão.

## Campos da revisão atual

O comando inclui `seq` (número de amostra) e `cannon_rate_deg_s` (taxa angular comandada entre 30 e 120 graus/s), além de `leds_on`. O firmware devolve `seq` na telemetria para estimar o tempo fim a fim de comando até o próximo pacote, incluindo seu período de 200 ms. `leds_configured` permanece falso até definir `pins::led_status` em `include/pins.h`; não se presume um GPIO sem conferir o hardware. O teto de RPM das esteiras exige RPM máxima de saída calibrada e nunca representa velocidade medida sem encoder. O firmware desta revisão deve ser gravado junto com o runtime PC antes do teste de latência e dos novos controles.

## Calibração móvel

`calibrating=true` apenas com o firmware de combate real da combinação selecionada e telemetria recente habilita a movimentação dos servos sem rearme da tração. `calibration_pan` e `calibration_tilt` comandam o canhão enquanto `camera_pan` posiciona o MG90S. A telemetria `camera_pan_commanded` confirma o valor enviado ao PWM; não é leitura física de posição. Os 12 pares de pan/tilt são salvos em `pc_operador/parameters_setups/user/camera_cannon_calibrations.json` por combinação completa, sem entrar na assinatura do firmware.
