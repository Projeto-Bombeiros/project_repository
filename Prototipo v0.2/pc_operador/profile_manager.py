"""Combinações completas salvas pelo notebook e firmware isolado por perfil."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from actuator_catalog import hardware_pairs, interface_board_issues
from package_variant import VARIANT

PC = Path(__file__).resolve().parent
ROOT = PC.parent
USER = PC / 'parameters_setups' / 'user'
DEFAULTS = PC / 'parameters_setups' / 'defaults'
SECTIONS = ('connection', 'vision', 'control', 'hardware')
DRIVE_KINDS = {'dc_3_6v': 1, 'bts7960_12v': 2, 'bldc_ktc86': 3}
CANNON_KINDS = {'mg996r': 1, 'ht23_ec1000': 2}
RUNTIME_SETUPS = ROOT / 'output' / 'runtime_setups'
FIRMWARE_BUILDS = ROOT / 'output' / 'firmware_builds'
SECRETS_HEADER = ROOT / 'esp32' / 'include' / 'secrets.h'
NETWORK_CREDENTIALS = USER / 'network_credentials.json'


def local_link_credentials(create: bool = False) -> tuple[str, str, str, str] | None:
    """Credenciais do AP local em JSON e no cabeçalho compilado para o ESP32."""
    existing = SECRETS_HEADER.read_text(encoding='utf-8') if SECRETS_HEADER.is_file() else ''
    macros = {}
    for key in ('BLAZE_AP_SSID', 'BLAZE_AP_PASSWORD', 'BLAZE_BT_NAME', 'BLAZE_BT_PIN'):
        match = re.search(r'^#define\s+' + key + r'\s+("(?:[^"\\]|\\.)*")\s*$',
                          existing, re.MULTILINE)
        if match:
            macros[key] = json.loads(match.group(1))
    if NETWORK_CREDENTIALS.is_file():
        saved = _read(NETWORK_CREDENTIALS)
        if all(key in saved for key in ('ap_ssid', 'ap_password', 'bt_name', 'bt_pin')):
            json_values = tuple(saved[key] for key in ('ap_ssid', 'ap_password', 'bt_name', 'bt_pin'))
            if macros and tuple(macros.get(key) for key in
                    ('BLAZE_AP_SSID', 'BLAZE_AP_PASSWORD', 'BLAZE_BT_NAME', 'BLAZE_BT_PIN')) != json_values:
                raise ValueError('As credenciais JSON e o firmware divergem; restaure a mesma instalação antes de compilar.')
            if not macros:
                _write_link_header(*json_values)
                macros = dict(zip(('BLAZE_AP_SSID', 'BLAZE_AP_PASSWORD', 'BLAZE_BT_NAME', 'BLAZE_BT_PIN'), json_values))
    if len(macros) == 4:
        ssid, password, bt_name, bt_pin = (macros[k] for k in
              ('BLAZE_AP_SSID', 'BLAZE_AP_PASSWORD', 'BLAZE_BT_NAME', 'BLAZE_BT_PIN'))
        if (re.fullmatch(r'BLAZE-[0-9A-F]{6}', ssid) and 8 <= len(password) <= 63
                and re.fullmatch(r'[0-9]{6}', bt_pin)):
            if not NETWORK_CREDENTIALS.is_file():
                _save_link_json(ssid, password, bt_name, bt_pin)
            return ssid, password, bt_name, bt_pin
        raise ValueError('Credenciais locais inválidas em esp32/include/secrets.h.')
    if macros:
        raise ValueError('Credenciais locais incompletas em esp32/include/secrets.h.')
    if not create:
        return None
    suffix = secrets.token_hex(3).upper()
    ssid, password, bt_name = f'BLAZE-{suffix}', secrets.token_urlsafe(18), f'BLAZE-{suffix}'
    bt_pin = f'{secrets.randbelow(1_000_000):06d}'
    _write_link_header(ssid, password, bt_name, bt_pin)
    _save_link_json(ssid, password, bt_name, bt_pin)
    return ssid, password, bt_name, bt_pin


def _write_link_header(ssid: str, password: str, bt_name: str, bt_pin: str) -> None:
    additions = ''.join(f'#define {key} {json.dumps(value)}\n' for key, value in (
        ('BLAZE_AP_SSID', ssid), ('BLAZE_AP_PASSWORD', password),
        ('BLAZE_BT_NAME', bt_name), ('BLAZE_BT_PIN', bt_pin)))
    SECRETS_HEADER.parent.mkdir(parents=True, exist_ok=True)
    temp = SECRETS_HEADER.with_suffix('.h.tmp')
    temp.write_text('#pragma once\n#define BLAZE_WIFI_SSID ""\n#define BLAZE_WIFI_PASSWORD ""\n' + additions, encoding='utf-8')
    os.replace(temp, SECRETS_HEADER)
    if os.name != 'nt':
        SECRETS_HEADER.chmod(0o600)


def _save_link_json(ssid: str, password: str, bt_name: str, bt_pin: str) -> None:
    NETWORK_CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    temp = NETWORK_CREDENTIALS.with_suffix('.json.tmp')
    temp.write_text(json.dumps({'ap_ssid': ssid, 'ap_password': password,
            'bt_name': bt_name, 'bt_pin': bt_pin}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, NETWORK_CREDENTIALS)
    if os.name != 'nt':
        NETWORK_CREDENTIALS.chmod(0o600)


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'JSON inválido: {path}')
    return data


def _safe(name: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9_.-]+', '_', name).strip('._')[:48]
    if not clean:
        raise ValueError('Nome da combinação inválido.')
    # O nome visível pode ser longo e conter '*'; o arquivo fica curto e único.
    return clean + '_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]


def _build_dir_name(name: str) -> str:
    # Nome de combinação automática pode ter ~60 caracteres. O diretório do
    # projeto PlatformIO fica curto também em caminhos Windows aninhados.
    return 'fw_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]


def _profile(data: dict) -> str:
    mode = str(data.get('vision', {}).get('combat_mode', '')).casefold()
    if mode in ('simulation', 'simulacao', 'simulação'):
        return 'simulacao'
    if mode in ('real', 'combate_real'):
        return 'combate_real'
    raise ValueError('A visão precisa declarar simulation ou real no setup salvo.')


def names(profile: str | None = None) -> list[str]:
    combinations = (_read(USER / 'combinations.json')
                    if (USER / 'combinations.json').is_file() else {})
    if profile is None:
        return sorted(combinations)
    found = []
    for name in combinations:
        try:
            if _profile(assemble(name)) == profile:
                found.append(name)
        except (KeyError, ValueError, FileNotFoundError):
            continue
    return sorted(found)


def assemble(name: str) -> dict:
    combos = (_read(USER / 'combinations.json')
              if (USER / 'combinations.json').is_file() else {})
    if name not in combos:
        raise KeyError(f'Combinação completa não encontrada: {name}')
    combination = combos[name]
    selected = combination.get('sections', {})
    data = copy.deepcopy(_read(PC / 'config.example.json'))
    for section in SECTIONS:
        choice = selected.get(section, '')
        if choice:
            records = _read(USER / f'{section}.json')
            if choice not in records:
                raise ValueError(f'{name}: setup {choice!r} não existe em {section}.')
            part = copy.deepcopy(records[choice])
        else:
            part = copy.deepcopy(_read(DEFAULTS / f'{section}.json'))
        for key, value in part.items():
            if key in ('_meta', 'saved_at'):
                continue
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
    # A seção de visão é a única dona da entrada de vídeo, inclusive no Default.
    data.setdefault('camera', {})['source'] = data['vision'].get('camera_source', 0)
    profile = _profile(data)
    physical = bool(data.get('hardware', {}).get('physical_outputs', False))
    physical_requested = physical
    jet_requested = bool(data.get('hardware', {}).get('jet_output_enabled', False))
    if profile == 'simulacao':
        # O mesmo cadastro físico pode preparar os dois perfis. No perfil de
        # simulação a autorização de atuação é sempre desabilitada na cópia
        # preparada; o setup salvo continua disponível para o combate real.
        data['hardware']['physical_outputs'] = False
        data['hardware']['jet_output_enabled'] = False
        physical = False
    if profile == 'combate_real' and not physical:
        raise ValueError(f'{name}: combate real exige hardware.physical_outputs=true.')
    if not 0 <= float(data.get('control', {}).get('steering_sensitivity_percent', 50)) <= 100:
        raise ValueError(f'{name}: sensibilidade de curva deve ficar entre 0 e 100%.')
    hardware = data.get('hardware', {})
    drive = hardware.get('drive_kind', 'bts7960_12v')
    cannon = hardware.get('cannon_kind', 'mg996r')
    if drive not in DRIVE_KINDS or cannon not in CANNON_KINDS:
        raise ValueError(f'{name}: conjunto de motores desconhecido.')
    if VARIANT == 'prototipo' and (drive == 'bldc_ktc86' or cannon == 'ht23_ec1000'):
        raise ValueError('Este é o pacote do protótipo; setups Kalatec pertencem ao pacote final.')
    if VARIANT == 'final' and (drive != 'bldc_ktc86' or cannon != 'ht23_ec1000'):
        raise ValueError('Este é o pacote final; requer os dois BLDC e três stepservos Kalatec.')
    if cannon != 'mg996r':
        raise ValueError('O protótipo requer canais de servos RC PWM no canhão.')
    for axis in ('pan', 'tilt', 'camera'):
        kind = str(hardware.get(f'{axis}_servo_kind',
                   hardware.get('camera_servo_kind', 'sg90') if axis == 'camera'
                   else hardware.get('cannon_motor_id', 'mg90s'))).lower()
        if kind not in ('mg90s', 'sg90', 'mg996r'):
            raise ValueError(f'{axis}: selecione MG90S, SG90 ou MG996R.')
        hardware[f'{axis}_servo_kind'] = kind
        hardware[f'{axis}_servo_model'] = {'mg90s': 'MG90S', 'sg90': 'SG90',
                                           'mg996r': 'MG996R'}[kind]
    for side in ('internal', 'external'):
        sensor = str(hardware.get(f'dht_{side}_type', 'DHT22')).upper()
        if sensor not in ('DHT11', 'DHT22'):
            raise ValueError(f'DHT {side}: selecione o formato de dados DHT11 ou DHT22.')
        hardware[f'dht_{side}_type'] = sensor
    focus_model = str(hardware.get('focus_actuator_model') or 'SG90').strip()
    if focus_model not in ('SG90', 'TowerPro SG90'):
        raise ValueError('O foco deste protótipo requer o microservo SG90.')
    dispersed = float(hardware.get('focus_dispersed_deg', 175))
    focused = float(hardware.get('focus_focused_deg', 5))
    if not (0 <= dispersed <= 180 and 0 <= focused <= 180 and dispersed != focused):
        raise ValueError('Informe extremos diferentes entre 0° e 180° para o servo de foco.')
    hardware['focus_actuator_model'] = 'SG90'
    hardware['focus_driver_model'] = 'PWM direto do ESP32 (sinal, não alimentação)'
    hardware['camera_driver_model'] = 'PWM RC 50 Hz (sinal; alimentação externa)'
    errors, pending, actuator_pairs = hardware_pairs(hardware, physical=physical)
    errors.extend(interface_board_issues(hardware))
    if errors:
        raise ValueError(f'{name}: ' + ' | '.join(errors))
    if physical and (len(actuator_pairs) != 2 or any(
            actuator_pairs[group][3].get('backend') in ('planned_bldc', 'planned_stepservo')
            for group in ('Esteiras', 'Canhão'))):
        raise ValueError(f'{name}: seleção sem backend físico validado.')
    hardware['drive_kind'] = drive
    hardware['cannon_kind'] = cannon
    hardware['drive_motor_id'] = actuator_pairs['Esteiras'][0]
    hardware['drive_driver_id'] = actuator_pairs['Esteiras'][1]
    hardware['cannon_motor_id'] = actuator_pairs['Canhão'][0]
    hardware['cannon_driver_id'] = actuator_pairs['Canhão'][1]
    hardware['drive_motor_model'] = actuator_pairs['Esteiras'][2]['name']
    hardware['drive_driver_model'] = actuator_pairs['Esteiras'][3]['name']
    hardware['cannon_motor_model'] = actuator_pairs['Canhão'][2]['name']
    hardware['cannon_driver_model'] = actuator_pairs['Canhão'][3]['name']
    data['_actuator_notes'] = pending
    data['_official'] = {'name': name, 'sections': selected, 'profile': profile,
                         'physical_outputs_requested': physical_requested,
                         'jet_output_requested': jet_requested,
                         'outputs_deferred': profile == 'simulacao' and
                                             (physical_requested or jet_requested),
                         'saved_at': combination.get('saved_at'),
                         'actuator_backend': f'{drive}/{cannon}',
                         'prepared_at': datetime.now(timezone.utc).isoformat()}
    return data


def _portable(data: dict, require_assets: bool = True) -> None:
    vision = data['vision']
    for key in ('fire_model', 'person_model', 'firefighter_model'):
        raw = str(vision.get(key) or '')
        if raw:
            local = PC / 'models' / re.split(r'[/\\]', raw)[-1]
            if local.is_file():
                vision[key] = f'models/{local.name}'
    source = str(vision.get('camera_source') or '')
    if vision.get('source_type') == 'video' and source:
        local = PC / 'videos_input' / re.split(r'[/\\]', source)[-1]
        if local.is_file():
            vision['camera_source'] = f'videos_input/{local.name}'
        elif require_assets and not Path(source).is_file():
            raise FileNotFoundError(f'Vídeo da combinação indisponível: {source}')
        data.setdefault('camera', {})['source'] = vision['camera_source']
    vision['trajectory_export_dir'] = '../output/visao'


def prepare(name: str, expected_profile: str | None = None, *,
            require_assets: bool = True) -> tuple[Path, dict]:
    """Prepara o perfil sem sondar componentes; arquivos só são exigidos na execução."""
    local_link_credentials(create=True)
    data = assemble(name)
    source = data.get('vision', {}).get('camera_source', data.get('camera', {}).get('source', 0))
    source_type = str(data.get('vision', {}).get('source_type', 'local')).lower()
    if source_type not in ('video', 'camera', 'local') or (
            isinstance(source, str) and (source == 'auto-ip' or source.lower().startswith(
                ('rtsp://', 'rtsps://', 'http://', 'https://')))):
        raise ValueError('Escolha câmera USB ou vídeo salvo no setup de visão.')
    # A velocidade da UART pertence à versão do protocolo, inclusive para
    # setups antigos guardados com a taxa inicial de 115200.
    data.setdefault('esp', {})['baudrate'] = 460800
    transport = data.get('esp', {}).get('transport', 'wifi_local')
    if transport not in ('usb', 'wifi_local'):
        raise ValueError('Escolha USB ou Wi-Fi local do ESP32 no setup de conexão.')
    if transport == 'wifi_local':
        data['esp']['host'] = '192.168.4.1'
    profile = data['_official']['profile']
    if expected_profile and expected_profile != profile:
        raise ValueError(f'{name} é {profile}; este programa aceita {expected_profile}.')
    _portable(data, require_assets=require_assets)
    if require_assets:
        for key in ('fire_model', 'person_model'):
            if not (PC / data['vision'].get(key, '')).is_file():
                raise FileNotFoundError(f'Modelo obrigatório indisponível: {key}')
    data['_official']['firmware_signature'] = _firmware_signature(data)[:16]
    RUNTIME_SETUPS.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_SETUPS / f'{_safe(name)}.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)
    return path, data


def prepare_all() -> dict[str, list[str]]:
    report = {'simulacao': [], 'combate_real': [], 'erros': []}
    for name in names():
        try:
            _, data = prepare(name)
            report[data['_official']['profile']].append(name)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            report['erros'].append(f'{name}: {exc}')
    return report


def _firmware_signature(data: dict) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps({'name': data['_official']['name'],
                              'profile': data['_official']['profile'],
                              'configuration': {key: value for key, value in data.items()
                                                if key != '_official'}},
                             sort_keys=True, ensure_ascii=False).encode())
    for path in sorted((ROOT / 'esp32' / 'src').glob('*')) + sorted((ROOT / 'esp32' / 'include').glob('*')):
        if path.is_file() and path.name != 'setup_generated.h':
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    digest.update((ROOT / 'esp32' / 'platformio.ini').read_bytes())
    return digest.hexdigest()


def firmware_project(name: str) -> tuple[Path, dict]:
    _, data = prepare(name)
    profile = data['_official']['profile']
    signature = _firmware_signature(data)
    project = FIRMWARE_BUILDS / profile / _build_dir_name(name)
    project.mkdir(parents=True, exist_ok=True)
    for folder in ('src', 'include'):
        dst = project / folder
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(exist_ok=True)
        for source in (ROOT / 'esp32' / folder).iterdir():
            if source.is_file() and source.name != 'setup_generated.h':
                text = source.read_text(encoding='utf-8')
                if source.name == 'pins.h':
                    # O valor único vem do cabeçalho gerado após o include.
                    text = re.sub(r'^\s*#define\s+BLAZE_ENABLE_PHYSICAL_OUTPUTS\s+\d+\s*\r?\n',
                                  '', text, flags=re.MULTILINE)
                (dst / source.name).write_text(text, encoding='utf-8')
    shutil.copy2(ROOT / 'esp32' / 'platformio.ini', project / 'platformio.ini')
    enabled = profile == 'combate_real'
    jet = enabled and bool(data['hardware'].get('jet_output_enabled', False))
    # O nome informado pelo ESP32 deve coincidir com a combinação em execução.
    name_literal = json.dumps(name, ensure_ascii=True)
    drive_backend = hardware_pairs(data['hardware'])[2]['Esteiras'][3].get('backend')
    drive_driver_kind = {'bts_pwm': 1, 'drv8833_dual': 2,
                         'l298n_dual': 3}.get(drive_backend, 0)
    (project / 'include' / 'setup_generated.h').write_text(
        '#pragma once\n' + f'#define BLAZE_SETUP_NAME {name_literal}\n' +
        f'#define BLAZE_SETUP_SIGNATURE "{signature[:16]}"\n' +
        f'#define BLAZE_ENABLE_PHYSICAL_OUTPUTS {int(enabled)}\n' +
        f'#define BLAZE_ENABLE_JET_OUTPUT {int(jet)}\n' +
        f'#define BLAZE_DRIVE_KIND {DRIVE_KINDS[data["hardware"]["drive_kind"]]}\n' +
        f'#define BLAZE_DRIVE_DRIVER_KIND {drive_driver_kind}\n' +
        f'#define BLAZE_CANNON_KIND {CANNON_KINDS[data["hardware"]["cannon_kind"]]}\n' +
        f'#define BLAZE_FOCUS_DISPERSED_DEG {int(data["hardware"].get("focus_dispersed_deg", 175))}\n' +
        f'#define BLAZE_FOCUS_FOCUSED_DEG {int(data["hardware"].get("focus_focused_deg", 5))}\n' +
        ''.join(f'#define BLAZE_SERVO_{axis.upper()}_SG90 {int(data["hardware"][f"{axis}_servo_kind"] == "sg90")}\n'
                for axis in ('pan', 'tilt', 'camera')) +
        ''.join(f'#define BLAZE_SERVO_{axis.upper()}_MODEL {json.dumps(data["hardware"][f"{axis}_servo_model"])}\n'
                for axis in ('pan', 'tilt', 'camera')) +
        ''.join(f'#define BLAZE_DHT_{side.upper()}_TYPE {11 if data["hardware"][f"dht_{side}_type"] == "DHT11" else 22}\n'
                for side in ('internal', 'external')),
        encoding='utf-8')
    (project / 'profile.json').write_text(json.dumps({
        'name': name, 'profile': profile, 'signature': signature,
        'physical_outputs': enabled, 'jet_output': jet,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return project, data


def platformio() -> list[str]:
    local = Path(sys.executable).parent / ('pio.exe' if os.name == 'nt' else 'pio')
    if local.is_file():
        return [str(local)]
    command = shutil.which('pio')
    if command:
        return [command]
    try:
        import platformio  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('PlatformIO ausente. Execute o preparador do ambiente do pacote.') from exc
    return [sys.executable, '-m', 'platformio']


def run_pio(name: str, upload: bool = False, port: str = '', output=None) -> Path:
    project, data = firmware_project(name)
    if upload:
        port = port.strip() or str(data['hardware'].get('upload_port') or '')
        if port.lower() in ('', 'auto', 'manual', 'none'):
            raise ValueError('Selecione a COM real do ESP32 antes de gravar por USB.')
        from serial.tools import list_ports
        if port not in {item.device for item in list_ports.comports()}:
            raise ValueError(f'{port} indisponível; confirme a porta e feche o monitor serial.')
    command = platformio() + ['run', '-e', 'esp32dev']
    if upload:
        command += ['-t', 'upload', '--upload-port', port]
    process = subprocess.Popen(command, cwd=project, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace',
                               bufsize=1, creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                                         if os.name == 'nt' else 0))
    for line in process.stdout:
        if output:
            output(line.rstrip())
    if process.wait():
        raise RuntimeError('PlatformIO falhou; confira o registro da compilação/gravação.')
    binary = project / '.pio' / 'build' / 'esp32dev' / 'firmware.bin'
    if binary.is_file():
        manifest = _read(project / 'profile.json')
        manifest['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        manifest['built_at'] = datetime.now(timezone.utc).isoformat()
        (project / 'profile.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return binary


def available_firmware(profile: str) -> list[dict]:
    """Builds presentes no PC, com perfil/assinatura e data verificáveis."""
    builds = []
    for manifest_path in (FIRMWARE_BUILDS / profile).glob('*/profile.json'):
        try:
            manifest = _read(manifest_path)
            binary = manifest_path.parent / '.pio/build/esp32dev/firmware.bin'
            if not binary.is_file() or manifest.get('profile') != profile:
                continue
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            if manifest.get('binary_sha256') != digest:
                continue
            builds.append({'name': manifest['name'], 'profile': profile,
                           'signature': manifest['signature'][:16],
                           'built_at': manifest.get('built_at', ''),
                           'binary_sha256': digest, 'project': manifest_path.parent})
        except (OSError, KeyError, ValueError):
            continue
    return sorted(builds, key=lambda item: item['built_at'], reverse=True)


def upload_compiled_firmware(build: dict, port: str, output=None) -> Path:
    """Grava o build selecionado sem reconstruir fontes de outra combinação."""
    project = Path(build['project']).resolve()
    if not project.is_relative_to(FIRMWARE_BUILDS.resolve()):
        raise ValueError('Firmware fora do diretório de builds BLAZE.')
    binary = project / '.pio/build/esp32dev/firmware.bin'
    current = next((item for item in available_firmware(build['profile'])
                    if item['project'].resolve() == project), None)
    if current is None or current['binary_sha256'] != build['binary_sha256']:
        raise ValueError('O binário selecionado foi alterado; compile novamente.')
    if current['name'] not in names(build['profile']):
        raise ValueError('A combinação deste firmware não existe mais.')
    _, data = prepare(current['name'], current['profile'])
    if data['_official']['firmware_signature'] != current['signature']:
        raise ValueError('Este firmware é de outra versão do setup/código. Compile o setup novamente.')
    from serial.tools import list_ports
    if not port or port not in {item.device for item in list_ports.comports()}:
        raise ValueError('Selecione a porta COM presente do ESP32; feche monitores seriais.')
    command = platformio() + ['run', '-e', 'esp32dev', '-t', 'upload', '--upload-port', port]
    process = subprocess.Popen(command, cwd=project, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace',
                               bufsize=1, creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                                         if os.name == 'nt' else 0))
    for line in process.stdout:
        if output: output(line.rstrip())
    if process.wait():
        raise RuntimeError('Falha ao gravar; consulte o registro do PlatformIO.')
    if hashlib.sha256(binary.read_bytes()).hexdigest() != current['binary_sha256']:
        raise RuntimeError('O build mudou durante a gravação; confirme a assinatura com Verificar firmware.')
    return binary
