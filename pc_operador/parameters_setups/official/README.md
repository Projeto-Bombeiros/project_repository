# Setup oficial BLAZE

A seção 7 do notebook cria `active.json` aqui após salvar e ativar uma combinação.
Cada grupo não selecionado usa o arquivo correspondente em `../defaults/`;
os setups que o usuário salvar ficam em `../user/`. O runtime usa o arquivo
oficial ao iniciar.

Os rascunhos editáveis ficam em `../user/` e `pc_operador/config.json`. Após editar
um rascunho, ative novamente a combinação para atualizar a cópia oficial.
Sem `active.json`, o runtime informa que falta escolher o setup oficial.
A pinagem do ESP32 continua definida em `esp32/include/pins.h` e precisa ser
recompilada e gravada quando alterada.
