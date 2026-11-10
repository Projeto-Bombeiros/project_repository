# Atualização do controle do protótipo

Extraia `BLAZE_prototipo/` sobre a pasta instalada, mantendo a mesma estrutura de diretórios. Faça uma cópia da instalação antes. Esta atualização contém apenas código, notebook e documentação: **não sobrescreve os setups, a combinação oficial, os modelos nem os vídeos do operador**.

1. Feche a central e o notebook. Copie os arquivos extraídos sobre os correspondentes na pasta instalada.
2. Abra o notebook e gere/compile o firmware com o setup oficial; grave o novo firmware por USB no ESP32. O arquivo já compilado antes desta revisão continua com o controle antigo.
3. Reinicie o runtime. Com as esteiras erguidas e sem jato, teste curvas pequenas e inversão do joystick; depois, teste pan, tilt e plataforma ao longo do curso.
4. Se um servo continuar tremendo com joystick parado em ângulos específicos, verifique a tensão no borne do servo sob carga, o GND comum, a fonte de alimentação e esforço mecânico. O ESP32 recebe comandos PWM, mas este protótipo não lê posição física dos servos; não há PID externo de posição.

No modo manual, com a mira parada perto da borda, a câmera agora permanece imóvel. O passo de 20° só acontece enquanto o joystick direito é mantido na direção da borda por pelo menos 150 ms; o próximo passo espera o servo completar o anterior. Isso corrige uma fonte encontrada de movimentos repentinos.

O giro do joystick esquerdo usa `0,45 × X × |X|`. O pan, tilt e plataforma seguem alvos com limite de 65°/s e 220°/s². Pequenas mudanças de alvo são ignoradas e o PWM permanece ativo para manter o torque. A fonte de vídeo, calibrações, proteção por detecção de pessoas e paradas permanecem sob os setups ativos.
