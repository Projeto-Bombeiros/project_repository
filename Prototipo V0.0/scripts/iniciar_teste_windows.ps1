param(
    [ValidateSet('notebooks')][string]$Alvo = 'notebooks',
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Argumentos = @()
)
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
# Uma configuracao global de OPENSSL_ia32cap pode anunciar instrucoes que a
# CPU nao oferece e derrubar uv/Python com "HW capability requested".
# Limpe apenas para este processo e seus filhos; nao altere o Windows global.
if (Test-Path Env:OPENSSL_ia32cap) {
    Remove-Item Env:OPENSSL_ia32cap
    Write-Host 'OPENSSL_ia32cap removida apenas desta execucao; deteccao da CPU sera automatica.'
}
$env:UV_NO_MODIFY_PATH = '1'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $raiz '.bootstrap\pythons'
$env:UV_CACHE_DIR = Join-Path $raiz '.bootstrap\cache'
$bin = Join-Path $raiz '.bootstrap\bin'
$uv = Join-Path $bin 'uv.exe'
if (-not (Test-Path $uv)) {
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $env:UV_INSTALL_DIR = $bin
    Write-Host 'Baixando o gerenciador oficial uv para a pasta do projeto...'
    Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression
}
if (-not (Test-Path $uv)) { throw 'Instalação local do uv não produziu uv.exe.' }
& $uv --version
if ($LASTEXITCODE -ne 0) { throw 'uv nao inicia. Envie as linhas acima, inclusive HW capability se aparecer.' }
$py = Join-Path $raiz '.bootstrap\python312\Scripts\python.exe'
$versao = if (Test-Path $py) { & $py -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))' } else { '' }
if ($versao -ne '3.12') {
    & $uv venv --clear --python 3.12 (Join-Path $raiz '.bootstrap\python312')
    if ($LASTEXITCODE -ne 0) { throw 'Falhou ao criar Python 3.12. Envie as linhas acima para identificar o executavel afetado.' }
}
$env:BLAZE_UV = $uv
$teste = Join-Path $raiz 'scripts\preparar_notebooks.py'
& $py $teste @Argumentos
if ($LASTEXITCODE -ne 0) { throw "Preparação dos notebooks terminou com erro ($LASTEXITCODE)." }
