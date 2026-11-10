# Setup oficial BLAZE

A última célula de qualquer um dos um notebook cria `active.json` aqui após
selecionar e ativar uma combinação nomeada de conexão, visão, controle e,
opcionalmente, hardware. O runtime do PC usa este arquivo ao iniciar.

Os rascunhos editáveis ficam em `../user/` e `pc_operador/config.json`. Após editar
um rascunho, ative novamente a combinação para atualizar a cópia oficial.
Sem `active.json`, o runtime informa que falta escolher o setup oficial.
A pinagem do ESP32 continua definida em `esp32/include/pins.h` e precisa ser
recompilada e gravada quando alterada.
