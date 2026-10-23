# BLAZE — pacote protótipo DC / ponte H

Esta distribuição contém notebook de configuração, dois lançadores de runtime PC, firmware ESP32, modelos e vídeos de exemplo. Rode `scripts/preparar_notebooks_windows.cmd` no Windows antes de abrir `pc_operador/teste_configuracao.ipynb` no VS Code. Os setups ativos e a combinação oficial começam vazios; os valores Default são fornecidos por arquivos separados.

Ao atualizar uma instalação existente, mantenha a pasta `pc_operador/parameters_setups/user` e o arquivo `pc_operador/parameters_setups/official/active.json`: o ZIP não inclui esses JSON do operador e não os substitui. Se extrair em uma pasta nova, copie esses arquivos da instalação antiga antes de abrir o notebook. Depois use **Preparar runtimes** na seção 7 para atualizar as combinações salvas.

## Arquitetura

Dois motores DC com um driver de ponte H selecionado por esteira; três servos RC independentes MG996R ou SG90 (pan, tilt e câmera); um microservo SG90 para focalização/dispersão do jato.

O mapa e os limites estão em [`docs/conexoes_prototipo.md`](docs/conexoes_prototipo.md). Os perfis de motor/servo da outra geração são rejeitados pelo gerador de combinação oficial. Para começar, salve as configurações com nomes automáticos, gere uma combinação oficial e prepare os runtimes. Componentes podem ser cadastrados antes da montagem. No perfil de simulação o firmware mantém as saídas físicas desligadas, ainda que o cadastro preveja componentes reais; para gravar o ESP32, escolha uma COM detectada e use cabo USB. Os lançadores `BLAZE_Simulacao.cmd` e `BLAZE_Combate_Real.cmd` consomem a combinação oficial preparada. O runtime mantém o controle manual por Xbox e ESP32 mesmo sem câmera ou vídeo; o painel mostra a ausência da imagem. A detecção de pessoas e o combate autônomo exigem vídeo e modelos válidos.

## Abrir diretamente no Windows

Execute `BLAZE_Simulacao.cmd` ou `BLAZE_Combate_Real.cmd` por duplo clique. Na primeira execução, o lançador prepara o Python local se faltarem dependências. Escolha uma combinação do perfil correspondente. Se os setups ficaram na instalação anterior, use **Importar setups anteriores** na primeira janela e escolha a pasta BLAZE antiga; confira depois os caminhos de modelos/vídeos e compile/grave o firmware desta instalação.

Por USB, encerre qualquer teste do notebook, monitor serial ou outra janela BLAZE que esteja usando a mesma COM. Para Wi-Fi, a caixa **Conexão local do ESP32 por Wi-Fi** mostra SSID e senha. Grave por USB o firmware preparado nesta instalação. Escolha explicitamente **USB** ou **Wi-Fi local** no setup de conexão. Na janela inicial, o botão **Conectar** abre o meio escolhido para diagnóstico; na central, segure Start por 2 s para iniciar a comunicação.

A primeira janela mantém **Abrir central**, **Calibrar câmera e canhão**, **Compilar firmware** e **Gravar firmware** fixos na faixa inferior; a lista central pode ser rolada em telas menores. A COM é escolhida em uma lista que mostra a descrição do adaptador USB. Em **Comunicação ESP32**, observe o último intervalo entre pacotes, a ida e volta do comando e o contador de desconexões. A fonte USB de índice 0 usa DirectShow primeiro no Windows, como no teste do notebook.

## Estado de integração

O firmware envia retorno curto aproximadamente a cada 50 ms e telemetria completa a cada 1000 ms. Cada linha JSON sai em uma só escrita TCP, evitando centenas de transmissões pequenas por resposta Wi-Fi. O PC envia comandos a cada 50 ms e neutraliza a atuação após 250 ms sem telemetria. Uma pausa prolongada provoca reconexão; no ESP32, a perda de comandos desarma as saídas em até 750 ms. A taxa de leitura dos sensores DHT não é de 50 ms. **Prepare, compile e grave novamente o firmware** após esta atualização; compare a assinatura exibida no primeiro painel. A versão anterior usa outra taxa serial e não atenderá a esta configuração USB.

Ao abrir a central, a comunicação está fechada. Start por 2 s inicia ou encerra o meio escolhido, com os joysticks neutros; seta para baixo por 1 s solicita parada ou rearme sem trocar de transporte. Na primeira janela, escolha uma câmera USB de índice 0 a 5 apenas para esta execução. A escolha vale no diagnóstico, na central e na calibração e é mantida ao usar F5.

**Operação sem vídeo:** no perfil de combate real, a câmera indisponível não bloqueia esteiras, servos e demais comandos manuais. Segure Start por 2 s com os joysticks neutros, aguarde conexão e rearme. Se o vídeo desaparecer durante a autonomia, a central volta ao modo manual; o operador precisa escolher novamente o modo autônomo após a imagem retornar. O sistema não consegue detectar pessoas sem vídeo: observe diretamente a área antes de acionar água ou mover o robô. A velocidade das esteiras ainda exige `geometry.output_max_rpm` configurado no setup. A calibração da mira e o combate autônomo continuam exigindo uma câmera funcional. Após atualizar este pacote, prepare a combinação oficial, compile e grave o firmware: o firmware antigo ainda bloqueia o modo manual quando `vision_valid` é falso.

O firmware fornece PWM dos motores DC, pan, tilt e plataforma configuráveis MG996R/SG90 e foco SG90. Os quatro canais RC recebem 50 Hz, 16 bits, com 500–2500 µs para 0–180° lógicos. A calibração mostra os pulsos comandados; o curso físico depende da versão do servo, da montagem e da fonte externa. O foco inicia em 5° focalizado e 175° disperso, editáveis entre 0° e 180°. **Recompile e grave** o firmware para aplicar esta faixa. A alimentação dos servos é externa, com GND comum.

Combinações antigas continuam arquivadas com os valores que tinham. Para adotar a plataforma SG90, os novos extremos e a interpretação dos DHT, salve o setup de hardware e a combinação oficial novamente, prepare o runtime e regrave o firmware correspondente. Os módulos físicos são DHT11; os bytes capturados no GPIO16 exigiram decodificação DHT22. O GPIO17 usará o mesmo formato por padrão até uma medição própria.

`Recebendo/ enviando` exige dados recentes; `Enviando` significa canal habilitado sem retorno; `Não enviando` significa canal não habilitado. PWM e relés não comprovam ligação física. Os ângulos de telemetria são setpoints. A mira verde mostra o alvo; a azul exige sensores reais de posição em pan (GPIO34), tilt (GPIO35) e plataforma (GPIO36), calibração ADC A/B e mapa completo de 12 pontos. Sem eles, ela fica oculta. A TowerPro lista o MG996R convencional com 0–159° e uma variante específica de 180°; aumentar o pulso não modifica limites mecânicos.


Se o Wi-Fi oscilar, observe na primeira janela SSID atual, contagem de pacotes completos, último intervalo, perdas e ida e volta. O Windows pode trocar de rede quando um AP não fornece internet; o programa agora verifica o SSID antes de cada conexão e informa quando a rota não sai pela rede do ESP32. Estar associado à rede local sem internet é normal. Feche monitor serial e outros runtimes que possam disputar a mesma placa.

## Revisão USB, visor e pontes H duplas

Esta revisão opera USB a 460800 baud. Prepare o runtime e compile/grave por cabo o firmware da combinação oficial; a central exige protocolo versão 4 para evitar interpretar firmware antigo como se tivesse feedback. A mira azul indica os três eixos medidos e projetados pelo mapa de 12 pontos, não o ponto real de impacto hidráulico.


No hardware, a seleção BTS7960, DRV8833 ou L298N determina o PWM e as ligações. O feedback externo dos servos é opcional e salvo por combinação completa. A tela repinta estados e leituras ambientais a cada 1 s; cada DHT é amostrado uma vez a cada 3 s. A biblioteca DHT sensor library for ESPx 1.19.0 lê temperatura e umidade juntas; a seção 8 apresenta a leitura e o código de erro sem declarar a medição exata só porque houve resposta. A biblioteca ESPx é distribuída separadamente sob GPL-3.0-only. Servos RC de três fios apenas recebem comandos: linha azul no primeiro painel significa saída habilitada, não movimento comprovado.

Na janela inicial do runtime, escolha uma calibração nomeada da combinação antes de abrir a central. O editor permite carregar, salvar e excluir calibrações de 12 pontos. Na plataforma em 0°, os alvos superior/inferior à esquerda ficam na linha vertical central; em 180°, isso vale para os alvos à direita. Calibrações anteriores precisam registrar novamente esses quatro alvos, pois os cantos antigos não são fisicamente alcançáveis. Sem mapa físico, pan e tilt seguem um campo de visão aproximado; o jato autônomo continua bloqueado até a calibração completa. A câmera gira em passos ao alcançar a borda, e o canhão é reposicionado quando o enquadramento se desloca. Na central, verde identifica atividade/mudança, amarelo valor estável, vermelho estado desligado/manual e cinza dado inválido ou ausente.

Ao voltar da calibração para a janela inicial, o diagnóstico reabre automaticamente a câmera e a comunicação com o ESP32 pelo meio selecionado. Aguarde a telemetria reaparecer antes de iniciar outra ação.

## Formato confirmado no GPIO16

No diagnóstico isolado, a captura dos bytes e duas bibliotecas independentes concordaram em aproximadamente 25,4–25,6 °C e 77–78% UR, interpretando os dados como DHT22. A referência independente informada foi 21 °C; a diferença aproximada de 4,4 °C continua sem causa confirmada e nenhum offset é aplicado. Perfis antigos salvos com decodificação DHT11 precisam ser ajustados para DHT22 nas duas entradas na seção 5 antes de gerar novamente a combinação oficial e gravar o firmware normal. A entrada externa continua sem verificação física.

## Central e arrefecimento

Start e seta para baixo usam a própria linha de comunicação e a de armado para mostrar o tempo apenas enquanto são pressionados; após soltar, as mesmas linhas mostram o estado. O painel separa acionamentos, sensoriamento/gestão térmica e comunicação. A escala verde inferior acompanha o ângulo comandado da plataforma em divisões de 5° sobre um campo ilustrativo de 120°, sem substituir calibração óptica. A central mostra o comando de arrefecimento retornado pelo ESP32; o botão A/B é uma solicitação manual, não a indicação de que o relé foi acionado. No firmware real, uma leitura DHT válida liga o arrefecimento interno ou externo a partir de 30 °C e o desliga abaixo de 28 °C (histerese); o interno também considera umidade. Na simulação a indicação é virtual e as saídas físicas permanecem desligadas. O estado comandado não confirma abertura física da válvula.

## Controle após a montagem física

A mistura diferencial usa curva progressiva no stick esquerdo: `giro = 0,45 × X × |X|`. Um pequeno deslocamento lateral muda pouco a velocidade das esteiras; a simulação do notebook usa a mesma curva. Pan, tilt e plataforma recebem alvos com tolerância de 0,35°, velocidade limitada a 65°/s e aceleração limitada a 220°/s². O PWM permanece ativo para manter o torque e só recebe atualização quando há deslocamento suficiente, em intervalos de pelo menos 20 ms. O stick direito tem zona neutra de 0,14 para filtrar ruído central.

No modo manual, a plataforma só recebe o passo de 20° na borda quando o stick direito é mantido naquela direção por 150 ms; um novo passo aguarda a conclusão do anterior. Isso corrige giros súbitos que aconteciam com a mira parada na borda. A atualização do firmware acima suaviza os comandos, mas não constitui um PID de posição física: os servos RC desta montagem não devolvem sua posição ao ESP32. A telemetria informa o último ângulo enviado ao PWM. Se um servo ainda oscilar em uma posição com joystick neutro e telemetria estável, confira a tensão da fonte externa sob carga, o GND comum e o esforço mecânico naquela posição. Recompile e grave o firmware da combinação oficial para aplicar a revisão.

## Publicação pelo notebook

A seção 10 publica a partir do próprio pacote ZIP, mesmo sem diretório `.git`: **Conferir envio** mostra os arquivos antigos que serão removidos e os novos caminhos em `Protótipo V0.0/`; **Enviar revisão** cria um commit normal e faz o envio. É preciso ter Git for Windows e autenticação com permissão de escrita. Para comparar, baixar, criar pasta, mover ou excluir arquivos em uma janela própria, dê dois cliques em `Abrir_Gerenciador_GitHub.cmd`. Veja [o guia](docs/gerenciar_github.md). Credenciais, firmware compilado e vídeos pessoais não entram na cópia publicada.
