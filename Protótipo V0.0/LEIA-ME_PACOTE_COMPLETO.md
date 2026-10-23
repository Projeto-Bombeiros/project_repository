# BLAZE — pacote completo com atualização de controle v4

Este ZIP contém o notebook de configuração, os dois lançadores de runtime, o projeto PlatformIO, os modelos e o vídeo de exemplo da distribuição anterior. As revisões de direção progressiva, suavização do comando de pan/tilt/plataforma, controle da borda da câmera e diagnóstico individual de servos já estão incorporadas. Os documentos `docs/LEIA-ME_ATUALIZACAO_CONTROLE.md` e `docs/DIAGNOSTICO_SERVOS.md` acompanham o pacote.

## Para iniciar no Windows

1. Extraia a pasta `BLAZE_prototipo` inteira em um caminho curto. Não abra o notebook dentro do ZIP.
2. Execute `scripts/preparar_notebooks_windows.cmd`. A pasta `.bootstrap` é criada e as dependências são instaladas nessa etapa; ela não vem pré-instalada no ZIP. É necessária conexão à internet na primeira preparação.
3. Abra o notebook. Se tinha setups configurados na instalação anterior, use a função **Importar setups anteriores** no runtime ou migre `pc_operador/parameters_setups/user/` e `pc_operador/parameters_setups/official/active.json` da instalação anterior. Não foram incluídos setups pessoais atuais porque não foram fornecidos com o pacote de origem.
4. Prepare a combinação oficial, compile e grave o firmware revisado pela USB antes de testar saídas físicas. O firmware antigo não recebe automaticamente as mudanças do código.

**Sem vídeo:** o perfil de combate real permite controle manual com Xbox e ESP32 conectados e rearme feito. A imagem permanece como indisponível; visão autônoma, detecção de pessoas e calibração da mira exigem câmera. Após esta revisão é obrigatório compilar e gravar novamente o firmware da combinação oficial para retirar o bloqueio antigo do modo manual. Sem `output_max_rpm` configurado no setup, as esteiras continuam com comando zero.

**Antes de acionar os MG90S montados:** use alimentação externa regulada para os servos, com GND comum com o ESP32; não use cabo USB cortado do notebook para alimentá-los. O firmware desta versão usa pulsos de 500–2500 µs e curso lógico de 0–180°. Verifique a faixa da variante de MG90S e a montagem antes de comandar os extremos. Faça os primeiros testes individuais na seção 8 perto de 90°, com motores e jato desabilitados.
