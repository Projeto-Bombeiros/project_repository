"""Prepara o kernel local do notebook único e dos dois runtimes."""
import sys
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from preparar_ambiente import ensure_managed_python, ensure_packages


if __name__ == '__main__':
    if '--self-check' in sys.argv[1:]:
        for item in ('pc_operador/teste_configuracao.ipynb',
                     'pc_operador/requirements.txt'):
            if not (ROOT / item).is_file():
                raise FileNotFoundError(item)
        print('Estrutura do notebook e runtime: OK (sem instalação)')
        raise SystemExit(0)
    ensure_managed_python(Path(__file__).resolve(), sys.argv[1:])
    ensure_packages('pc', ROOT / 'pc_operador' / 'requirements.txt',
                    ('numpy', 'cv2', 'PIL', 'ultralytics', 'pygame', 'zeroconf', 'ipykernel', 'ipywidgets'))
    ensure_packages('esp32', None, ('platformio', 'serial'))
    sys.path.insert(0, str(ROOT / 'pc_operador'))
    import profile_manager
    ssid, _, bluetooth_name, _ = profile_manager.local_link_credentials(create=True)
    active = ROOT / 'pc_operador/parameters_setups/official/active.json'
    if active.is_file():
        prior = json.loads(active.read_text(encoding='utf-8'))
        selected = prior.get('_official', {}).get('name')
        if selected and selected in profile_manager.names():
            _, updated = profile_manager.prepare(selected)
            if 'activated_at' in prior.get('_official', {}):
                updated['_official']['activated_at'] = prior['_official']['activated_at']
            temp = active.with_suffix('.json.tmp')
            temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, active)
    print(f'Rede local desta instalação: {ssid}; Bluetooth: {bluetooth_name}.')
    print('Compile e grave o firmware desta instalação antes do primeiro enlace sem USB.')
    print('Ambiente do notebook e runtimes pronto:', sys.executable)
    print('Abra teste_configuracao.ipynb e selecione este Python como kernel.')
