# Primeira execução no VS Code

1. Extraia o ZIP completo em uma pasta local. Evite caminhos excessivamente longos no Windows; por exemplo, `C:\BLAZE`.
2. Dê duplo clique em `scripts/preparar_notebooks_windows.cmd`. O preparador cria `.bootstrap/python312`, instala os pacotes do PC e o PlatformIO e abre o notebook único `pc_operador/teste_configuracao.ipynb`.
3. No VS Code, se surgir **Restricted Mode**, escolha **Trust this folder**. Selecione o kernel em `.bootstrap/python312`.
4. Execute as seções em ordem. Na seção 6, salve a combinação de conexão, visão, controle e hardware; na seção 7, prepare os programas e o firmware; na seção 8, confira o mapa e teste os componentes por USB.
5. Depois, abra `BLAZE_Simulacao.cmd` ou `BLAZE_Combate_Real.cmd` sem usar o notebook. Escolha um único setup completo na janela inicial. Ali também é possível compilar e gravar o firmware correspondente.

O ZIP contém o vídeo e os modelos enviados. A pasta `.bootstrap` é criada localmente para evitar problemas de copiar ambientes Python de outro computador. A primeira preparação precisa de internet para baixar Python, bibliotecas e PlatformIO. A gravação do ESP32 exige USB. Para operar sem roteador, o ESP32 cria sua rede Wi-Fi local. Escolha USB ou Wi-Fi no setup; grave o firmware novo antes de avaliar a latência na primeira janela do runtime.

O perfil de combate real não possui uma combinação pronta neste pacote. Crie e salve uma combinação específica no notebook após definir a pinagem e os componentes físicos.
