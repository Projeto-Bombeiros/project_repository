@echo off
setlocal
echo Preparando o Python e abrindo o notebook BLAZE no VS Code...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_teste_windows.ps1" notebooks
if errorlevel 1 (
  echo A preparacao falhou. Copie a mensagem exibida acima para diagnostico.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0abrir_notebook_windows.ps1"
if errorlevel 1 echo Ambiente preparado, mas o VS Code nao abriu. Abra pc_operador\teste_configuracao.ipynb manualmente.
echo NO VS CODE: se aparecer Restricted Mode, clique em Trust this folder antes de selecionar o kernel.
echo A extensao Python pode estar instalada mas desativada ate confiar nesta pasta.
pause
