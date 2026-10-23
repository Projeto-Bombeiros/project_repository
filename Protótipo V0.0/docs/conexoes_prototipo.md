# Ligações do protótipo ESP32

O quadro interativo da seção 8 do notebook mostra os modelos da combinação oficial. Consulte também o silk screen de cada módulo e confirme o chicote antes de alimentar.

| Componente | Sinal do ESP32 | Terminais do componente | Alimentação |
|---|---|---|---|
| BTS7960 esquerdo | GPIO25 RPWM, GPIO26 LPWM, GPIO27 R_EN e L_EN | RPWM, LPWM, R_EN, L_EN; M+/M− ao motor | B+/B− da fonte do motor; lógica VCC/GND segundo módulo |
| BTS7960 direito | GPIO32 RPWM, GPIO33 LPWM, GPIO23 R_EN e L_EN | Mesmos terminais, segundo módulo | Fonte externa, GND comum ao ESP32 |
| DRV8833 (alternativa: ponte dupla) | GPIO25/26 → AIN1/AIN2; GPIO32/33 → BIN1/BIN2 | AOUT1/AOUT2 → motor esquerdo; BOUT1/BOUT2 → motor direito; nSLEEP em nível alto | VM 2,7–10,8 V; GND comum. GPIO27/23 não usados |
| L298N (alternativa: ponte dupla) | GPIO25/26 → IN1/IN2; GPIO27 PWM → ENA; GPIO32/33 → IN3/IN4; GPIO23 PWM → ENB | OUT1/OUT2 → esquerdo; OUT3/OUT4 → direito; retire jumpers ENA/ENB | VSS lógica 5 V separada, Vs fonte do motor, GND comum. Com Vs 6 V não dependa do regulador 5 V da placa |
| MG996R ou SG90 pan | GPIO18 | Sinal PWM 50 Hz | Fonte externa conforme modelo, GND comum |
| MG996R ou SG90 tilt | GPIO19 | Sinal PWM 50 Hz | Fonte externa conforme modelo, GND comum |
| MG996R ou SG90 plataforma da câmera | GPIO4 | Sinal PWM 50 Hz | Fonte externa conforme modelo, GND comum |
| Sensor de posição pan opcional | GPIO34 ADC1 | Saída analógica 0–3,3 V; resistor 100 kΩ externo para GND | GND comum; não ligar 5 V ao ESP32 |
| Sensor de posição tilt opcional | GPIO35 ADC1 | Saída analógica 0–3,3 V; resistor 100 kΩ externo para GND | GND comum; não ligar 5 V ao ESP32 |
| Sensor de posição plataforma opcional | GPIO36 ADC1 | Saída analógica 0–3,3 V; resistor 100 kΩ externo para GND | GND comum; não ligar 5 V ao ESP32 |
| SG90 foco | GPIO14 | Sinal PWM 50 Hz | Fonte externa 4,8–6 V, GND comum |
| Dois módulos DHT11, formato de dados por entrada | GPIO16 e GPIO17 | DATA separado; GPIO16: decodificação DHT22 confirmada; GPIO17: mesmo formato por padrão, ainda sem medição própria | VCC/GND conforme módulo |
| Relés interno, externo e válvula do jato | GPIO22, GPIO13, GPIO21 | IN de cada canal; contatos COM/NO conforme válvula | Fonte do módulo e da carga conforme especificação |

Em servos, são comuns laranja/amarelo para sinal, vermelho para positivo e marrom/preto para terra; **confirme a variante real**. Sensores e relés não têm cores de fios universais. Os GPIO fornecem sinais de controle, nunca a corrente dos motores ou servos. Não suponha que o estado `canal habilitado` comprove ligação física.

Para o motor DC 3–6 V com BTS7960, a fonte deve atender simultaneamente à tensão permitida do motor e à tensão mínima da placa BTS7960 adquirida. A faixa pode ser muito estreita; confira etiqueta, ficha do módulo, corrente e dissipação. Para Mabuchi 12 V, selecione fonte dimensionada para a peça. Use dois BTS7960, um por esteira.

O foco usa um microservo SG90, com extremos de fábrica do setup em 5° focalizado e 175° disperso, editáveis entre 0° e 180°. O comando RB/R3 altera a fração entre esses extremos; confirme os batentes com o mecanismo desacoplado antes de ativar a saída física. A plataforma tem servo independente do pan/tilt; o runtime comanda `camera_pan` separadamente pela câmera/controle.

O driver selecionado no setup oficial determina onde o firmware aplica PWM. Para BTS7960 são dois módulos; para DRV8833 ou L298N basta um módulo de dois canais. DRV8833 não suporta motor de 12 V. O L298N apresenta grande queda interna de tensão, reduzindo a velocidade de motores 3–6 V. Confira a corrente de partida da peça real e capacidade térmica por canal antes de aplicar potência.

MG996R e SG90 convencionais de três fios não devolvem sua posição ao ESP32. Para exibir a mira azul, adicione três sensores externos de ângulo ou servos com saída de feedback, calibre as leituras A/B e registre os 12 pontos da câmera. Não conecte diretamente ao ADC de 3,3 V um potenciômetro alimentado a 5–6 V.

Se MG996R e SG90 partilharem a mesma alimentação, ajuste a fonte externa para a faixa comum indicada pelos fabricantes (4,8–6,0 V) e dimensione a corrente para todos os servos. O pino do ESP32 fornece apenas sinal.
