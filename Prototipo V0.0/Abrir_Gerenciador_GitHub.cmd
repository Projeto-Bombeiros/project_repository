@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 (
  echo Nao foi possivel abrir a pasta deste pacote.
  pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo Instale o Git for Windows e tente novamente.
  pause
  exit /b 1
)
if exist ".bootstrap\python312\Scripts\python.exe" (
  ".bootstrap\python312\Scripts\python.exe" "scripts\gerenciar_github.py"
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 "scripts\gerenciar_github.py"
  ) else (
    where python >nul 2>&1
    if errorlevel 1 (
      echo Python nao localizado. Execute scripts\preparar_notebooks_windows.cmd primeiro.
      pause
      exit /b 1
    )
    python "scripts\gerenciar_github.py"
  )
)
if errorlevel 1 (
  echo O gerenciador encontrou um erro. Veja a mensagem acima.
  pause
  exit /b 1
)
popd
endlocal
