"""Preparação local para o notebook e os runtimes independentes; não é importado pelo runtime.

Quando o teste é aberto diretamente com um Python incompatível, baixa o instalador
oficial do uv, cria um Python 3.12 gerenciado e reinicia o teste no ambiente local.
Os lançadores do VS Code cobrem inclusive máquinas sem Python prévio.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / '.bootstrap' / 'python312'
PYTHON = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
UV_LOCAL = ROOT / '.bootstrap' / 'bin' / ('uv.exe' if os.name == 'nt' else 'uv')
os.environ.setdefault('UV_NO_MODIFY_PATH', '1')
os.environ.setdefault('UV_PYTHON_INSTALL_DIR', str(ROOT / '.bootstrap' / 'pythons'))
os.environ.setdefault('UV_CACHE_DIR', str(ROOT / '.bootstrap' / 'cache'))


def command(args, **kwargs):
    print('> ' + ' '.join(str(part) for part in args), flush=True)
    return subprocess.run([str(part) for part in args], check=True, **kwargs)


def uv_executable():
    supplied = os.environ.get('BLAZE_UV', '')
    for candidate in (supplied, str(UV_LOCAL), shutil.which('uv')):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    print('Instalando uv pelo instalador oficial no diretório local do projeto...')
    url = ('https://astral.sh/uv/install.ps1' if os.name == 'nt'
           else 'https://astral.sh/uv/install.sh')
    installer = ROOT / '.bootstrap' / ('instalar_uv.ps1' if os.name == 'nt'
                                      else 'instalar_uv.sh')
    installer.parent.mkdir(parents=True, exist_ok=True)
    # urlopen usa validação TLS padrão. Instalação automática requer internet.
    with urllib.request.urlopen(url, timeout=40) as response:
        installer.write_bytes(response.read())
    env = dict(os.environ, UV_INSTALL_DIR=str(UV_LOCAL.parent))
    try:
        if os.name == 'nt':
            command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                     '-File', installer], env=env)
        else:
            command(['sh', installer], env=env)
    finally:
        installer.unlink(missing_ok=True)
    if not UV_LOCAL.is_file():
        raise RuntimeError('Instalador terminou, mas o executável uv não foi encontrado.')
    return str(UV_LOCAL)


def version_of(executable):
    try:
        result = subprocess.run([str(executable), '-c',
                                 'import sys; print(sys.version_info.major, sys.version_info.minor)'],
                                capture_output=True, text=True, timeout=12, check=True)
        return tuple(int(part) for part in result.stdout.strip().split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ensure_managed_python(test_file, argv):
    """Relança o arquivo com Python 3.12, sem trocar o Python global do sistema."""
    if Path(sys.executable).absolute() == PYTHON.absolute():
        if version_of(PYTHON) == (3, 12):
            return
        raise RuntimeError('Reexecute pela tarefa do VS Code para reparar o Python gerenciado.')
    uv = uv_executable()
    if version_of(PYTHON) != (3, 12):
        VENV.parent.mkdir(parents=True, exist_ok=True)
        if VENV.exists() and not (VENV / 'pyvenv.cfg').is_file():
            raise RuntimeError('A pasta .bootstrap/python312 não é um ambiente virtual; revise-a antes.')
        # Recria somente o ambiente gerenciado deste pacote quando necessário.
        command([uv, 'venv', '--clear', '--python', '3.12', VENV])
    env = dict(os.environ, BLAZE_UV=uv)
    raise SystemExit(subprocess.run([str(PYTHON), str(test_file)] + list(argv),
                                    env=env, check=False).returncode)


def ensure_packages(tag, requirements, imports):
    """Instala no ambiente gerenciado apenas quando a especificação mudou."""
    import importlib.util

    marker = VENV / ('.blaze_' + tag + '_ready.json')
    specification = (requirements.read_bytes() if requirements else b'platformio>=6.1,<7\npyserial>=3.5,<4')
    signature = hashlib.sha256(specification + sys.version.encode('utf-8')).hexdigest()
    cached = {}
    if marker.is_file():
        try:
            cached = json.loads(marker.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    if cached.get('signature') == signature and all(importlib.util.find_spec(name) for name in imports):
        print('Dependências já preparadas para', tag)
        return
    uv = uv_executable()
    args = [uv, 'pip', 'install', '--python', sys.executable]
    if requirements:
        args += ['-r', requirements]
    else:
        args += ['platformio>=6.1,<7', 'pyserial>=3.5,<4']
    command(args)
    importlib.invalidate_caches()
    missing = [name for name in imports if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError('A instalação terminou, mas faltam módulos: ' + ', '.join(missing))
    marker.write_text(json.dumps({'signature': signature}, indent=2), encoding='utf-8')


def setup_error(exc):
    print('\nPreparação interrompida:', exc)
    print('Verifique conexão com a internet, espaço em disco e acesso à pasta do projeto.')
    return 2
