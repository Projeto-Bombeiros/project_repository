@echo off
setlocal
cd /d "%~dp0"
set "BLAZE_PYTHON=%~dp0.bootstrap\python312\Scripts\python.exe"
if not exist "%BLAZE_PYTHON%" (
  goto prepare
)
"%BLAZE_PYTHON%" -c "import cv2, PIL, pygame, serial, ultralytics, tkinter" >nul 2>&1
if errorlevel 1 goto prepare
goto start
:prepare
echo Preparando o Python e as dependencias para o runtime...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\iniciar_teste_windows.ps1" notebooks
if errorlevel 1 goto failed
:start
"%BLAZE_PYTHON%" "%~dp0pc_operador\runtime_simulacao.py"
if errorlevel 1 goto failed
exit /b 0
:failed
echo A central nao abriu. Confira a mensagem acima.
pause
exit /b 1
