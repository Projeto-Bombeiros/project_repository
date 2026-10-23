# Contrato de troca PC ↔ ESP32

O protocolo usa USB serial a **460800 baud** ou TCP na rede Wi-Fi local do ESP32, porta **8765**. Selecione explicitamente `esp.transport: usb` ou `wifi_local`; não há seleção automática de transporte ou comunicação Bluetooth. Um comando JSON por linha é enviado a cada 50 ms; o ESP32 devolve um pacote curto a cada 50 ms e outro completo a cada 1000 ms. O PC preserva os últimos campos completos ao mesclar pacotes curtos. A tela apresenta o intervalo real entre pacotes e o tempo de ida e volta estimado pela sequência (`seq`). Esses períodos são programados, não um compromisso mensurado de latência máxima: a câmera, inferência, Windows, DHT e o movimento dos servos também contribuem.

O PC só abre a comunicação ao segurar Start por 2 s na central. A seta para baixo por 1 s solicita parada ou rearme sem fechar o meio escolhido. Se o PC não receber telemetria por 250 ms, envia comandos neutros; se o ESP32 não receber comandos válidos por 750 ms, desarma os atuadores. Após uma desconexão, solicite nova conexão pelo Start. O firmware e o runtime novos devem ser usados juntos; grave o ESP32 por USB antes de testar.

## PC → ESP32 (`control`)

```json
{"type":"control","seq":0,"mode":"manual","drive_x":0.0,"drive_y":0.0,"cannon_x":0.0,"cannon_y":0.0,"cannon_rate_deg_s":90.0,"auto_pan":90.0,"auto_tilt":90.0,"camera_pan":90.0,"calibrating":false,"calibration_pan":90.0,"calibration_tilt":90.0,"camera_min":0,"camera_max":180,"pan_min":0,"pan_max":180,"tilt_min":0,"tilt_max":180,"vision_valid":false,"target_valid":false,"person_detected":false,"cool_manual":false,"cool_internal":false,"cool_external":false,"jet_enable":false,"water_on":false,"pressure":0,"focus":0,"brake":false,"emergency":false,"leds_on":false,"stop":true,"rearm":false}
```

`drive_x/y` e `cannon_x/y` ficam em [-1,1]. `camera_pan` é o ângulo comandado da plataforma entre 0° e 180°. `auto_pan/tilt` são graus calculados pela visão com os 12 pontos registrados no runtime. `calibrating=true` autoriza somente os três servos; `calibration_pan/tilt` posicionam o canhão com tração, jato e relés bloqueados. `person_detected` é verdadeiro se uma pessoa foi detectada no quadro atual ou na memória curta de detecções. `vision_valid` exige quadro recente **e** detector de pessoas carregado. `jet_enable` comanda o jato virtual na simulação; no combate real depende da liberação física e dos intertravamentos. `rearm` é um pulso produzido na conexão inicial ou após segurar seta para baixo por 1 s, aceito somente com joysticks neutros, sem pessoa detectada e com vídeo e conexão válidos. Não há vídeo bruto nessa mensagem.

## ESP32 → PC (`telemetry`)

```json
{"type":"telemetry","connected":true,"armed":false,"mode":"manual","safety":"safe","motion":"stopped","reason":"awaiting_rearm","temp_internal":null,"humidity_internal":null,"temp_external":null,"humidity_external":null,"sensor_internal_valid":false,"sensor_external_valid":false,"cool_internal_commanded":false,"cool_external_commanded":false,"jet_commanded":false,"jet_virtual":false,"drive_left_commanded":0.0,"drive_right_commanded":0.0,"servo_pan_commanded":90.0,"servo_tilt_commanded":90.0,"camera_pan_commanded":90.0,"camera_servo_configured":true,"cool_internal_configured":false,"cool_external_configured":false,"jet_configured":false}
```

`motion` descreve saídas de tração comandadas, pois não há encoder no diagrama. Válvulas não possuem retorno físico; `*_commanded` descreve o sinal lógico, não confirma movimento/abertura. Os campos `servo_pan_feedback_raw`, `servo_tilt_feedback_raw` e `camera_pan_feedback_raw` permanecem em −1 por compatibilidade; este protótipo não possui medição externa da posição dos servos. Temperaturas e umidades ficam nulas enquanto não houver leitura válida. `reason` explica o bloqueio. Alertas térmicos (>35 °C) aparecem em `alert_internal`/`alert_external`; não causam bloqueio global sem um requisito adicional.

## Prioridades

1. Perda de comando/conexão, parada do operador, pessoa detectada ou visão inválida → tração e jato desabilitados; o canhão conserva posição.
2. Recuperação de conexão não rearma automaticamente. Novo comando com joysticks neutros e `rearm=true` é necessário.
3. O arrefecimento local funciona sem PC. No modo manual, pedidos do operador podem ligá-lo; nunca podem desligar uma necessidade automática por temperatura/umidade.
4. No cenário da chama impressa, apenas a representação do jato e do apagamento é simulada. A saída física do jato depende de configuração explícita adicional e vem desabilitada por padrão.

## Medição e limites

Cada retorno rápido inclui `fast=true`, `protocol_version=4`, `seq`, a assinatura do firmware, três leituras ADC e ângulos e saídas comandadas; a telemetria completa usa `fast=false` e acrescenta sensores, configurações e motivos de bloqueio. A linha `Versão do firmware` depende do primeiro pacote completo. `seq` permite correlacionar o comando com a resposta, mas não mede a chegada física do servo ao setpoint. `camera_min/max`, `pan_min/max` e `tilt_min/max` limitam individualmente os comandos, com 0–180° como padrão. O operador deve confirmar fisicamente os limites seguros dos motores montados.

## Calibração móvel

`calibrating=true` apenas com o firmware de combate real da combinação selecionada e telemetria recente habilita a movimentação dos servos sem rearme da tração. `calibration_pan` e `calibration_tilt` comandam o canhão enquanto `camera_pan` posiciona o servo da plataforma. A telemetria `camera_pan_commanded` confirma o valor enviado ao comando; não é leitura física de posição. Os 12 pares de pan/tilt são salvos em `pc_operador/parameters_setups/user/camera_cannon_calibrations.json` por combinação completa, sem entrar na assinatura do firmware.

Sensores opcionais de posição nos GPIO34/35/36 são calibrados em extremos A/B na janela do runtime. Os 12 pontos e os três eixos medidos são necessários para exibir a mira azul; sem feedback válido, ela fica oculta. Cada canal RC usa 500–2500 µs a 50 Hz (0–180° lógicos). A telemetria completa informa o pulso comandado em pan, tilt e plataforma; o curso físico depende da peça. Um pulso PWM e o setpoint não confirmam que o servo está conectado.

## Ajuste de resposta do protótipo montado

`drive_x` continua em [−1,1], mas sua contribuição de giro à mistura diferencial é `0,45 × drive_x × |drive_x|`. Pan, tilt e câmera recebem os mesmos alvos do protocolo anterior: o firmware aplica tolerância de 0,35°, velocidade máxima teórica de 65°/s e aceleração de até 220°/s² antes de atualizar o PWM. Mudanças inferiores a 0,55° não reescrevem o duty; mudanças maiores são enviadas em intervalos de pelo menos 20 ms. Perda de conexão, parada, pessoa detectada e perda do alvo interrompem trajetórias pendentes conforme as permissões. `*_commanded` passa a representar o último ângulo escrito no PWM, não o alvo recebido nem uma posição física medida.
