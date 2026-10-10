# BLAZE — configuração e operação

Este pacote contém um notebook de configuração e dois programas independentes para o PC. Os modelos de visão, o vídeo de teste, os parâmetros padrão e o projeto do firmware ESP32 estão incluídos. As listas de setups salvos começam vazias. A pasta `.bootstrap` será criada pelo preparador na primeira execução; ela não depende de arquivos copiados de uma instalação anterior.

Os binários `.bin` de cada combinação são criados pela opção **Compilar firmware** no computador de destino. Nenhum binário anterior é reutilizado depois que o setup ou o código muda.

## Primeira execução no Windows

1. Extraia **todo** o ZIP em uma pasta local, preservando a estrutura.
2. Execute `scripts/preparar_notebooks_windows.cmd`. Ele instala Python 3.12, dependências e PlatformIO na `.bootstrap` local e abre `pc_operador/teste_configuracao.ipynb` no VS Code. É necessário acesso à internet nessa primeira preparação.
3. Configure e teste as seções do notebook. Salve os grupos que personalizar. Na seção 7, grupos não selecionados usam seus valores padrão sem criar entradas nas listas; o nome completo une as quatro partes com `*` e descreve os grupos personalizados. A data/hora fica no registro da combinação.
4. Na seção 8, clique **Preparar runtimes**. Para usar o ESP32, escolha a combinação completa, compile e grave o firmware pela porta USB indicada. A simulação mantém as saídas físicas desligadas.
5. Para combate real, conecte a câmera e os servos, grave o firmware da combinação e clique **Calibrar câmera e canhão** na janela inicial. Registre os quatro cantos em 0°, 90° e 180° da plataforma e salve os 12 pontos. Essa calibração pertence à combinação e não exige recompilar.
6. Feche o notebook, se desejar. Abra `BLAZE_Simulacao.cmd` ou `BLAZE_Combate_Real.cmd`. Escolha **um único nome de combinação completa** na janela inicial. Ali também há botões para compilar e gravar o firmware selecionado. Conecte o Xbox antes ou depois de abrir a central.

## Perfis

| Programa | Combinações exibidas | Firmware |
| --- | --- | --- |
| `BLAZE_Simulacao.cmd` | Apenas visão `simulation` e saídas físicas desabilitadas | Compilação isolada; motor, servos, relés e jato físico desabilitados |
| `BLAZE_Combate_Real.cmd` | Apenas visão `real` e saídas físicas habilitadas | Compilação isolada com a pinagem do projeto e o nome exato da combinação |

O pacote recebido não contém combinações salvas nem uma configuração oficial ativa. Para abrir os programas independentes, salve e ative uma combinação na seção 7. A combinação inteiramente padrão corresponde à simulação com saídas físicas desligadas.

## Conjuntos de motores

Na seção 6 escolha separadamente a tração e o canhão. A combinação completa leva essa escolha ao programa do PC e à compilação de um firmware com identificadores de driver próprios.

| Tração | Driver previsto | Estado do acionamento |
| --- | --- | --- |
| DC 3–6 V com redução | Dois módulos BTS7960; alimentação regulada de 5,5–6 V na potência | PWM reversível esquerdo/direito, mediante fiação e tensão/corrente verificadas |
| Mabuchi 12 V | Dois módulos BTS7960 | PWM reversível esquerdo/direito |
| KTC-86BLS125-J com redutor | KTC-J-DR-BLDC750 | Perfil e checklist disponíveis; saídas de tração bloqueadas até validar entrada analógica/direção/falha do driver |

O canhão MG996R mantém dois sinais PWM de 50 Hz. A opção HT23-EC1000 com KTC-DR23EC-K é cadastrável, porém pan/tilt e jato físico ficam bloqueados até implementar pulso/direção, alimentação e retorno de falha. O servo MG90S da câmera permanece independente. Os testes da seção 10 distinguem os canais e recusam pulsos incompatíveis com o perfil selecionado. A lista inicial mostra saídas habilitadas, leituras de DHT e vídeo; ela não mede continuidade elétrica de motor/relé/servo. Observe fisicamente os resultados dos pulsos.

O PC recebe vídeo de **câmera USB** ou **arquivo de vídeo salvo**. O ESP32 cria a rede Wi-Fi local `BLAZE-XXXXXX` e atende em `192.168.4.1:8765`, sem depender de roteador, hotspot do Windows ou de endereço IP atribuído por DHCP. O modo automático de comunicação tenta primeiro USB e depois a rede local. A primeira gravação do firmware sempre usa cabo USB e uma porta COM; depois o runtime tenta conectar o Windows ao ponto de acesso do ESP32 quando a opção de rede local estiver selecionada.

Na seção 2, teste a webcam ou o arquivo e selecione USB, rede local do ESP32 ou automático. Na seção 4, selecione novamente a fonte que a visão usará e salve o setup com os modelos de chama e pessoas. A seção 5 testa o controle Xbox. Na seção 6, salvar o hardware gera uma senha única para a rede BLAZE, mostra o SSID e a senha no guia e grava os valores em `pc_operador/parameters_setups/user/network_credentials.json` e no cabeçalho local `esp32/include/secrets.h`. Esses dois arquivos devem permanecer juntos com o firmware compilado: ao mudar de PC, preserve-os ou grave novamente um firmware com as novas credenciais. Eles não vêm preenchidos neste ZIP. Não é necessário preencher SSID/senha de uma rede externa.

A seção 7 salva a combinação completa. Depois de mudar o perfil ou as credenciais, prepare, compile e grave novamente pela USB na seção 8. A seção 9 testa comandos neutros e telemetria pelo transporte selecionado; se não conectar, mostra a última tentativa e a causa informada. A central de simulação permite ensaiar Xbox e vídeo sem atuadores físicos; se a placa estiver presente, recebe comandos de parada. No combate real, a atuação depende dos intertravamentos e da assinatura do firmware da combinação. As velocidades mostradas sem encoders não comprovam movimento físico.

`pc_operador/runtime.py` contém os subsistemas compartilhados. `pc_operador/central_operador.py` contém a interface. Os dois arquivos `runtime_*.py` abrem o seletor de perfil; `profile_manager.py` monta as combinações e compila uma cópia isolada do projeto do ESP32 em `output/firmware_builds/`. Os resultados de visão ficam em `output/visao/`.

Se a placa exigir BOOT manual: com o monitor serial fechado, segure **BOOT**, pressione e solte **EN**, clique **Gravar ESP32 por USB**, e solte BOOT quando o registro mostrar **Chip is ESP32**.

## Plataforma da câmera

O MG90S usa o sinal GPIO4 e alimentação própria de 5 V, com GND comum. No modo manual, mantenha D-pad ←/→ para girar a câmera; no automático ela varre 0°–180° sem chama e recentraliza o enquadramento quando a mira chega à faixa de 8 px da lateral. D-pad ↓ por 1 segundo aciona a parada de emergência. O firmware informa o ângulo **comandado**, pois o feedback interno do MG90S não é uma leitura disponível no ESP32.

Durante a varredura e por 0,45 s depois de mudar o ângulo comandado da câmera, o disparo automático físico fica bloqueado até estabilizar o enquadramento. Confira visualmente os limites reais e a sobreposição de cada ponto antes de salvar a calibração: a telemetria não comprova que o eixo atingiu a posição solicitada.

Na simulação geométrica da seção 5, o cone branco de 120° mostra a área visível da câmera e dois objetos sorteados aparecem na janela menor somente enquanto estiverem dentro dele. Com o stick direito, o canhão gira primeiro e a câmera o acompanha perto da borda; com as setas, a câmera gira primeiro e o canhão acompanha ao atingir a margem oposta. A posição aparente dos objetos responde aos giros e ao deslocamento do robô. Essa janela ilustra a geometria; a central de simulação que usa um vídeo gravado conserva os quadros originais, pois o arquivo não contém imagens de outros ângulos.

### Calibração física e versão do firmware

A janela inicial do runtime mostra telemetria, câmera, controle e sensores. A indicação de saída PWM habilitada **não comprova** que o servo está conectado. Para calibrar, use uma combinação de combate real e uma câmera ao vivo. Confirme a montagem e a chegada física de cada eixo: plataforma 0–180°, pan 25–155°, tilt 35–145°. A rotina salva o limite angular comum, reduzido pela porcentagem escolhida, junto aos 12 pontos da combinação. Se a combinação ou o código de firmware mudar, compile novamente, escolha o binário pela data na janela inicial e grave pela COM. Confira em seguida a assinatura recebida do ESP32.
