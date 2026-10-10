# Conexões definidas para o protótipo BLAZE

**Placa assumida:** ESP32-WROOM-32 em placa de desenvolvimento compatível com `esp32dev`. Os números abaixo são **GPIO**, não a numeração física de posição no conector. Verifique os rótulos impressos na sua placa antes de ligar fios. O mapa está em `esp32/include/pins.h`.

### Seleção do conjunto na seção 6

O mapa abaixo usa **dois módulos BTS7960**, um por esteira, tanto para os motores DC 3–6 V quanto para os Mabuchi 12 V. A diferença é a fonte de potência. Para motores 3–6 V, use alimentação regulada entre **5,5 e 6 V**, somente se a tensão e a corrente de partida dos motores forem compatíveis; o BTS7960 não opera normalmente abaixo de 5,5 V. Para os Mabuchi, use a fonte nominal de 12 V dimensionada para os dois módulos. Os sinais RPWM/LPWM/EN permanecem nos mesmos GPIOs. Nunca ligue o motor diretamente ao ESP32.

Para o BLDC KTC-86BLS125-J, selecione o driver KTC-J-DR-BLDC750 e informe a redução. Seu comando de velocidade requer interface para a entrada de referência do driver (0–5 V ou 0–10 V, conforme configuração); Hall/alarme e sentido precisam de pinagem e conversão elétrica definidas. **O firmware desta versão mantém a tração BLDC desligada.**

Para o canhão HT23-EC1000, selecione KTC-DR23EC-K. É um stepservo de pulso/direção com encoder no driver, não um MG996R de PWM posicional. **Os canais pan/tilt e o jato físico ficam desligados nesse perfil** até existir interface e teste de retorno próprios. O MG90S da câmera continua no GPIO4.

Referências dos componentes: [BTS7960 (Infineon)](https://www.infineon.com/dgdl/BTS7960_Datasheet.pdf?folderId=db3a304412b407950112b408e8c9), [KTC-86BLS125-J (Kalatec)](https://www.kalatec.com.br/motor-brushless-bldc-700w/) e [HT23-EC1000 (Kalatec)](https://www.kalatec.com.br/stepservo-de-2nm-ht23-ec1000/). Confirme a variante e o manual do módulo comprado antes da ligação.

| Origem no ESP32 | Destino no componente | Função |
| --- | --- | --- |
| GPIO25 | BTS7960 esquerdo `RPWM` | Esteira esquerda, um sentido |
| GPIO26 | BTS7960 esquerdo `LPWM` | Esteira esquerda, sentido oposto |
| GPIO27 | BTS7960 esquerdo `R_EN` **e** `L_EN` | Habilitação conjunta do driver esquerdo |
| GPIO32 | BTS7960 direito `RPWM` | Esteira direita, um sentido |
| GPIO33 | BTS7960 direito `LPWM` | Esteira direita, sentido oposto |
| GPIO23 | BTS7960 direito `R_EN` **e** `L_EN` | Habilitação conjunta do driver direito |
| GPIO18 | MG996R pan, entrada de sinal | Giro horizontal do canhão |
| GPIO19 | MG996R tilt, entrada de sinal | Giro vertical do canhão |
| GPIO4 | MG90S da plataforma, entrada de sinal | Giro horizontal da câmera entre 0° e 180° |
| GPIO16 | DHT11 interno, `DATA` | Temperatura/umidade internas; componente adicional ao diagrama V00 |
| GPIO17 | DHT11 externo, `DATA` | Temperatura/umidade externas |
| GPIO22 | Relé de arrefecimento interno, `IN` | Saída independente; exige módulo/atuador próprio |
| GPIO13 | Relé de arrefecimento externo, `IN` | Saída independente |
| GPIO21 | Relé do jato, `IN` | Reservado; **desabilitado** para a chama impressa |

Use o borne `GND` do ESP32 como referência comum com as entradas de controle de baixa tensão dos drivers, fontes dos servos e sensores. O DHT11 deve ser alimentado com **3,3 V compatíveis com a entrada do ESP32** e `DATA` deve ter pull-up conforme o módulo utilizado. Os MG996R devem receber alimentação própria adequada; ligue somente o sinal ao GPIO, nunca os alimente pela saída de um GPIO. Os motores recebem alimentação pela fonte e pelos bornes de potência dos BTS7960 (`B+`, `B-`, `M+`, `M-`), não pelo ESP32. Confirme a compatibilidade dos níveis de entrada de cada *módulo* BTS7960 e de relé com lógica de 3,3 V; use adaptação de nível quando o módulo exigir.

Como GPIOs ficam em alta impedância durante a partida, garanta **desabilitação física definida** nos `R_EN/L_EN` dos BTS7960 até o firmware assumir os pinos; os relés ativos em nível baixo precisam permanecer desligados na partida conforme a eletrônica do módulo. Confirme isso sem motores e sem válvulas ligadas à carga antes do ensaio conjunto.

O ESP32 fornece **somente sinais de controle** aos módulos de relé. Não conecte rede de 220 V a GPIO, `3V3`, `5V` ou `GND` da placa. A ligação dos contatos `COM/NO/NC` ao circuito da válvula exige especificação do módulo, da proteção e da instalação elétrica. O diagrama V00 dispõe de duas válvulas, mas o programa reserva três funções distintas (arrefecimento interno, externo e jato); uma terceira atuação física precisa ser definida antes de usar as três.

## Condições do runtime

### Comunicação local por USB ou rede criada pelo ESP32

No primeiro salvamento do hardware, o programa gera SSID e senha únicos em
`pc_operador/parameters_setups/user/network_credentials.json` e
`esp32/include/secrets.h`. O firmware usa o ponto de acesso `BLAZE-XXXXXX`
com endereço fixo `192.168.4.1` e TCP `8765`. A gravação requer USB.
Depois de gravar, selecione rede local ou automático no setup. Em automático,
o PC tenta USB primeiro e depois entra na rede BLAZE. O Windows precisa ter
adaptador Wi-Fi habilitado e conseguir ver a rede criada pelo ESP32. A troca
para BLAZE pode desconectar o Wi-Fi atual do computador; a câmera USB e o
vídeo salvo continuam locais.

Ao trocar de PC, copie o JSON de credenciais e o cabeçalho da instalação
anterior junto ao pacote, ou grave novamente o ESP32 com as novas
credenciais geradas no outro computador. O runtime verifica telemetria
antes de liberar comandos, exige rearme após perda de comunicação e nunca
transporta vídeo pelo ESP32.

O MG90S da plataforma usa fonte externa de 5 V adequada ao servo e terra comum
com o ESP32. Seu feedback de posição é interno; a telemetria informa o ângulo
comandado, sem medir o eixo. Na janela inicial do runtime de combate real,
**Calibrar câmera e canhão** registra os quatro cantos da imagem em 0°, 90° e
180° da plataforma, após gravar o firmware e conectar câmera e três servos.
Durante essa calibração, tração e relés permanecem desligados. No manual,
D-pad ←/→ gira a plataforma; D-pad ↓ por 1 segundo solicita parada de emergência.

- `BLAZE_ENABLE_PHYSICAL_OUTPUTS=1` permite PWM de tração, servos e relés de arrefecimento **quando comandados**. Na inicialização, tração e relés começam em zero/desligados; movimento exige vídeo/detector de pessoas, enlace válido e rearme manual.
- `BLAZE_ENABLE_JET_OUTPUT=0` mantém a válvula física do jato desabilitada. O apagamento da chama impressa permanece virtual.
- O firmware trata sensores desconectados como leitura inválida. Ele **não detecta** automaticamente se há motor, servo ou módulo de relé fisicamente presente. `*_commanded` confirma o sinal lógico; confirmação física precisa de observação ou sensores de retorno.
- Se uma esteira girar ao contrário no pulso positivo, ajuste `invert_left` ou `invert_right` em `pins.h`, compile e repita o ensaio. Os valores mostrados na HMI continuam no referencial lógico de deslocamento do robô.
- O teste USB aceita `STATUS` e pulsos `TEST MOTOR_L`, `MOTOR_R`, `SERVO_PAN`, `SERVO_TILT`, `SERVO_CAMERA`, `COOL_INT`, `COOL_EXT`; duração máxima 1200 ms, motores limitados a ±25%. O programa guiado pede confirmação para cada canal.

## Dimensões e velocidades

Na HMI, informe distância entre esteiras (m), raio efetivo da roda motriz (m) e RPM máxima **na saída após redução**, medida ou calibrada. Sem os três valores, nenhuma velocidade é estimada. `Vx` é a velocidade longitudinal no referencial do chassi, `Vy=0` para direção diferencial sem deslizamento lateral e o giro é dado em rad/s. O cálculo pressupõe relação aproximadamente linear entre PWM e RPM. Patinagem, carga e tensão alteram essa relação; velocidades reais e posição global X/Y exigem encoders e orientação/odometria.

## Base da escolha de GPIO e PWM

Foram evitados pinos de *strapping* 0, 2, 5, 12 e 15, os pinos 6–11 ocupados pela flash e as entradas 34–39, que não servem como saída. A compatibilidade de LEDC 2.x/3.x está em `esp32/src/pwm_compat.h`. Referências: [GPIO do ESP32](https://docs.espressif.com/projects/esp-idf/en/v5.3.4/esp32/api-reference/peripherals/gpio.html), [módulo WROOM-32](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html) e [LEDC Arduino-ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html).
