# Encontra a CLI do VS Code somente quando o Code.exe correspondente existe.
# Ignora atalhos code.cmd quebrados, como um arquivo copiado sem Code.exe.
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$notebook = Join-Path $raiz 'pc_operador\teste_configuracao.ipynb'
if (Test-Path Env:OPENSSL_ia32cap) { Remove-Item Env:OPENSSL_ia32cap }

$candidatos = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'),
    (Join-Path $env:ProgramFiles 'Microsoft VS Code\bin\code.cmd')
)
if (${env:ProgramFiles(x86)}) {
    $candidatos += Join-Path ${env:ProgramFiles(x86)} 'Microsoft VS Code\bin\code.cmd'
}
$candidatos += @(Get-Command code.cmd -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source } | ForEach-Object { $_.Source })

$code = $null
foreach ($candidato in ($candidatos | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidato -PathType Leaf)) { continue }
    $executavel = Join-Path (Split-Path -Parent $candidato) '..\Code.exe'
    if (Test-Path -LiteralPath $executavel -PathType Leaf) {
        $code = $candidato
        break
    }
    Write-Host "Ignorando comando VS Code sem Code.exe: $candidato"
}

if (-not $code) {
    Write-Host 'Python e pacotes prontos. A instalacao do VS Code nao foi localizada.'
    Write-Host "Abra esta pasta no VS Code: $raiz"
    Write-Host "Depois abra este notebook: $notebook"
    exit 0
}

Write-Host "VS Code encontrado: $code"
foreach ($extensao in @('ms-python.python', 'ms-toolsai.jupyter')) {
    Write-Host "Preparando extensao $extensao..."
    & $code --install-extension $extensao
    if ($LASTEXITCODE -ne 0) {
        Write-Host "A extensao $extensao nao foi instalada automaticamente; instale-a pelo VS Code."
    }
}
Write-Host 'Abrindo a pasta do projeto e o notebook do PC...'
& $code --new-window $raiz $notebook
if ($LASTEXITCODE -ne 0) {
    throw "O VS Code nao abriu automaticamente. Abra $notebook dentro da pasta $raiz."
}
Write-Host 'PASSO OBRIGATORIO NO VS CODE: se aparecer Restricted Mode, clique em Trust this folder.'
Write-Host 'Enquanto a pasta nao for confiavel, Python pode estar instalado mas desativado; o kernel nao aparece.'
Write-Host 'Se o VS Code pedir um kernel, escolha o Python em .bootstrap\python312.'
