#!/usr/bin/env bash
set -euo pipefail
alvo="${1:-notebooks}"
shift || true
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_DIR="$raiz/.bootstrap/pythons"
export UV_CACHE_DIR="$raiz/.bootstrap/cache"
bin="$raiz/.bootstrap/bin"
uv="$bin/uv"
if [[ ! -x "$uv" ]]; then
  mkdir -p "$bin"
  echo 'Baixando o gerenciador oficial uv para a pasta do projeto...'
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf 'https://astral.sh/uv/install.sh' | UV_INSTALL_DIR="$bin" sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- 'https://astral.sh/uv/install.sh' | UV_INSTALL_DIR="$bin" sh
  else
    echo 'O sistema precisa de curl ou wget para obter o instalador oficial.' >&2
    exit 2
  fi
fi
[[ -x "$uv" ]] || { echo 'uv não foi encontrado após a instalação.' >&2; exit 2; }
py="$raiz/.bootstrap/python312/bin/python"
versao=""
if [[ -x "$py" ]]; then versao="$($py -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))')"; fi
if [[ "$versao" != '3.12' ]]; then
  "$uv" venv --clear --python 3.12 "$raiz/.bootstrap/python312"
fi
export BLAZE_UV="$uv"
case "$alvo" in
  notebooks) "$py" "$raiz/scripts/preparar_notebooks.py" "$@" ;;
  *) echo 'Escolha notebooks; as configurações estão no teste_configuracao.ipynb.' >&2; exit 2 ;;
esac
