"""Catálogo editável e verificação conservadora de motores, servos e drivers.

Compatibilidade elétrica não implica suporte de firmware ou montagem verificada.
O arquivo do usuário registra somente adições e exclusões; padrões vêm no código.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "parameters_setups/user/components.json"
SOURCES = {
    "kalatec_bldc": "https://www.kalatec.com.br/wp-content/uploads/2020/10/Manual-BLDC-Drive-KTC-J-DRBLDC750.pdf",
    "kalatec_stepservo": "https://www.kalatec.com.br/wp-content/uploads/2019/08/Manual-KTC-DR23EC-K-050422.pdf",
    "drv8833": "https://www.ti.com/lit/ds/symlink/drv8833.pdf",
    "l298n": "https://www.st.com/resource/en/datasheet/l298.pdf",
    "mg996r": "https://towerpro.com.tw/product/mg996R/",
}

# Uma placa de interface é distinta dos drivers de potência Kalatec. O cadastro
# registra a topologia para preparação do chicote e para a futura geração do
# firmware, sem converter uma montagem não ensaiada em saída física habilitada.
INTERFACE_BOARDS = {
    "none": dict(name="Sem placa de interface", state="não aplicável",
                 description="Adequada apenas aos backends já existentes de ponte H/PWM RC."),
    "blaze_ktc_if_01": dict(
        name="BLAZE-KTC-IF-01 (projeto de placa)", state="projeto elétrico; sem validação física",
        description="PCA9306 (I²C 3,3/5 V), MCP4728 (2 DAC 0–5 V), "
                    "TCA9539 (controle e alarmes) e 2× TPL7407LA (saídas de coletor aberto). "
                    "Não é uma placa comercial pronta nem substitui os quatro drivers Kalatec.",
        documentation="docs/conexoes_kalatec.md"),
}

def interface_board_issues(hardware: dict) -> list[str]:
    """Impedimentos de topologia; a homologação física é verificada à parte."""
    kalatec_drive = hardware.get("drive_kind") == "bldc_ktc86"
    kalatec_cannon = hardware.get("cannon_kind") == "ht23_ec1000"
    board = hardware.get("interface_board_id", "none")
    if board not in INTERFACE_BOARDS:
        return ["Placa de interface desconhecida."]
    if kalatec_drive != kalatec_cannon:
        return ["O mapa BLAZE-KTC-IF-01 reserva GPIO18/19 para I²C e "
                "não admite mistura de canhão MG996R com conjunto Kalatec."]
    if kalatec_drive and board != "blaze_ktc_if_01":
        return ["O conjunto Kalatec requer a placa de interface BLAZE-KTC-IF-01."]
    if not kalatec_drive and board != "none":
        return ["A placa BLAZE-KTC-IF-01 pertence ao conjunto Kalatec completo."]
    return []
BUILTINS = {
    "dc_3_6v": dict(role="motor", name="Motor DC 3–6 V", technology="brushed_dc",
                    drive_kind="dc_3_6v", voltage_v=6, min_v=3, max_v=6,
                    nominal_a=None, peak_a=None, control="PWM bidirecional",
                    notes="Selecione BTS7960, DRV8833 ou L298N com alimentação externa compatível; confira queda de tensão, corrente de partida e dissipação."),
    "mabuchi_12v": dict(role="motor", name="Mabuchi DC 12 V", technology="brushed_dc",
                        drive_kind="bts7960_12v", voltage_v=12, min_v=12, max_v=12,
                        nominal_a=None, peak_a=None, control="PWM bidirecional",
                        notes="A corrente depende do modelo exato; confirme na ficha técnica."),
    "ktc_86bls125_j": dict(role="motor", name="Kalatec KTC-86BLS125-J", technology="bldc_hall",
                           drive_kind="bldc_ktc86", voltage_v=48, min_v=24, max_v=48,
                           nominal_a=18, peak_a=54, watts=660, torque_nm=2.1, rpm=3000,
                           control="driver BLDC trifásico, Hall, referência 0–5 V",
                           source=SOURCES["kalatec_bldc"],
                           notes="Manual lista 24–48 V, 18 A e 54 A de pico para esta variante. Confirme a etiqueta do motor; a interface ESP32 ainda não está implementada."),
    "mg996r": dict(role="servo", name="TowerPro MG996R", technology="rc_pwm",
                    cannon_kind="mg996r", voltage_v=6, min_v=4.8, max_v=6.6,
                    peak_a=1.4, control="PWM 50 Hz, alimentação independente",
                    source=SOURCES["mg996r"], notes="Servo RC PWM selecionável independentemente para pan, tilt e câmera; confirme o curso real da variante."),
    "ht23_ec1000": dict(role="servo", name="Kalatec HT23-EC1000-K", technology="stepservo",
                        cannon_kind="ht23_ec1000", voltage_v=None, min_v=None, max_v=None,
                        nominal_a=3, torque_nm=2, control="pulso/direção + encoder DB9",
                        source=SOURCES["kalatec_stepservo"],
                        notes="Kalatec indica KTC-DR23EC-K, 24–80 VDC no driver; exige duas unidades."),
    "bts7960": dict(role="driver", name="BTS7960", technology="brushed_dc",
                     interface="dual_pwm_hbridge", min_v=5.5, max_v=27,
                     continuous_a=None, peak_a=None, channels=1, backend="bts_pwm",
                     pins="RPWM, LPWM, R_EN e L_EN; um módulo por esteira.",
                     notes="Corrente contínua depende da placa e dissipação; conferir módulo adquirido."),
    "drv8833": dict(role="driver", name="DRV8833", technology="brushed_dc",
                    interface="dual_pwm_hbridge", min_v=2.7, max_v=10.8,
                    continuous_a=1.2, peak_a=2, channels=2, backend="drv8833_dual",
                    pins="AIN1/AIN2 e BIN1/BIN2; nSLEEP em nível ativo; nFAULT opcional.",
                    source=SOURCES["drv8833"],
                    notes="Limite conservador por canal de módulo comum: 1,2 A contínuo, 2 A pico. Conferir placa."),
    "l298n": dict(role="driver", name="L298N · ponte H dupla", technology="brushed_dc",
                   interface="dual_pwm_hbridge", min_v=4.5, max_v=35,
                   continuous_a=2, peak_a=2, channels=2, backend="l298n_dual",
                   pins="IN1/IN2 GPIO25/26, ENA PWM GPIO27; IN3/IN4 GPIO32/33, ENB PWM GPIO23. Remova os jumpers ENA/ENB.",
                   source=SOURCES["l298n"],
                   notes="Lógica VSS 5 V externa; sinais 3,3 V aceitos pelo CI. Queda de tensão elevada: motor 3–6 V pode não receber 6 V na saída; confira temperatura/corrente do módulo e alimentação."),
    "ktc_j_dr_bldc750": dict(role="driver", name="KTC-J-DR-BLDC750",
                             technology="bldc_hall", interface="analog_bldc_hall",
                             min_v=24, max_v=48, continuous_a=None, peak_a=None,
                             channels=1, backend="planned_bldc",
                             pins="Motor: U/V/W + Hu/Hv/Hw/REF. Controle: SV 0–5 V, COM, F/R, EN, BRK; SPEED e ALM opcionais. Sinais digitais 5 V; requer conversão externa para ESP32.",
                             source=SOURCES["kalatec_bldc"],
                             notes="Um driver por esteira. EN alto para parar, BRK alto para frear. Reservas GPIO25/32 SV, 26/33 F/R, 27/23 EN; não ligue diretamente aos sinais 5 V. Firmware físico pendente."),
    "ktc_dr23ec_k": dict(role="driver", name="KTC-DR23EC-K",
                         technology="stepservo", interface="step_dir_encoder",
                         min_v=24, max_v=80, continuous_a=None, peak_a=None,
                         channels=1, backend="planned_stepservo",
                         pins="PUL+/PUL-, DIR+/DIR-, EN+/EN- e ALM+/ALM-. Alto 4,5–28 V; encoder DB9 liga motor ao driver. Um driver por eixo.",
                         source=SOURCES["kalatec_stepservo"],
                         notes="Dois drivers, pan e tilt. ESP32 3,3 V não satisfaz PUL/DIR; exige interface 5 V, GPIO adicionais sem conflito e firmware físico."),
    "mg996r_pwm": dict(role="driver", name="PWM RC 50 Hz", technology="rc_pwm",
                        interface="pwm_rc", min_v=None, max_v=None,
                        continuous_a=None, peak_a=None, channels=3, backend="rc_pwm",
                        pins="GPIO18, GPIO19 e GPIO4 geram sinal 50 Hz; fonte externa 4,8–6,6 V e GND comum.",
                        notes="Gerador de sinal, não driver de potência nem alimentação do servo."),
}

def _number(value):
    if value in ("", None):
        return None
    result = float(value)
    if not 0 <= result <= 10000:
        raise ValueError("Os valores elétricos devem estar entre 0 e 10000.")
    return result

def _record(raw):
    if not isinstance(raw, dict):
        raise ValueError("Registro de componente inválido.")
    record = dict(raw)
    if record.get("role") not in ("motor", "servo", "driver"):
        raise ValueError("Selecione motor, servo ou driver.")
    if record.get("technology") not in ("brushed_dc", "bldc_hall", "rc_pwm", "stepservo"):
        raise ValueError("Selecione uma tecnologia de acionamento.")
    if not str(record.get("name", "")).strip():
        raise ValueError("Informe o modelo.")
    for key in ("voltage_v", "min_v", "max_v", "nominal_a", "peak_a",
                "continuous_a", "watts", "torque_nm", "rpm"):
        record[key] = _number(record.get(key))
    if record.get("min_v") is not None and record.get("max_v") is not None:
        if record["min_v"] > record["max_v"]:
            raise ValueError("Tensão mínima maior que a máxima.")
    if record["role"] == "driver":
        expected = {"brushed_dc": "dual_pwm_hbridge", "bldc_hall": "analog_bldc_hall",
                    "stepservo": "step_dir_encoder", "rc_pwm": "pwm_rc"}[record["technology"]]
        if record.get("interface") != expected:
            raise ValueError("Interface de entrada incompatível com a tecnologia declarada.")
        channels = int(record.get("channels", 1))
        if channels < 1 or channels > 16:
            raise ValueError("O driver precisa declarar de 1 a 16 canais.")
        record["channels"] = channels
    return record

def catalog(path: Path = CATALOG_PATH, include_hidden: bool = False) -> dict:
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(saved, dict):
        raise ValueError("components.json inválido.")
    hidden = set(saved.get("hidden", []))
    rows = {key: _record(value) for key, value in BUILTINS.items()
            if include_hidden or key not in hidden}
    for key, value in saved.get("custom", {}).items():
        if key not in hidden:
            rows[key] = _record(value)
    return rows

def _save(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def add_custom(key: str, record: dict, path: Path = CATALOG_PATH):
    import re
    if not re.fullmatch(r"[a-z0-9_]{3,48}", key) or key in BUILTINS:
        raise ValueError("ID único: 3–48 caracteres minúsculos, números ou _.")
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    saved.setdefault("custom", {})[key] = _record(record)
    saved["hidden"] = [item for item in saved.get("hidden", []) if item != key]
    _save(saved, path)

def delete(key: str, path: Path = CATALOG_PATH):
    if key not in catalog(path):
        raise KeyError(key)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    saved.setdefault("custom", {}).pop(key, None)
    if key in BUILTINS:
        saved["hidden"] = sorted(set(saved.get("hidden", [])) | {key})
    _save(saved, path)

def validate_pair(motor: dict, driver: dict, physical=False) -> tuple[list[str], list[str]]:
    """Retorna (bloqueios, pendências); nunca deduz um driver pelo motor."""
    errors, pending = [], []
    if motor.get("technology") != driver.get("technology"):
        errors.append("Tecnologias incompatíveis: o driver não comuta este motor/servo.")
        return errors, pending
    if motor["role"] == "servo" and motor["technology"] == "brushed_dc":
        errors.append("Servo sem interface de controle identificada.")
    if motor["role"] == "motor" and motor["technology"] in ("rc_pwm", "stepservo"):
        errors.append("Selecione este atuador na lista de servos.")
    voltage = motor.get("voltage_v")
    if motor["technology"] != "rc_pwm":
        if voltage is None or driver.get("min_v") is None or driver.get("max_v") is None:
            pending.append("Tensão de alimentação não documentada para o par.")
        elif not driver["min_v"] <= voltage <= driver["max_v"]:
            errors.append(f"Tensão: {voltage:g} V fora da faixa {driver['min_v']:g}–{driver['max_v']:g} V do driver.")
    for motor_key, driver_key, name in (("nominal_a", "continuous_a", "contínua"),
                                         ("peak_a", "peak_a", "de partida/pico")):
        motor_a, driver_a = motor.get(motor_key), driver.get(driver_key)
        if motor_a is not None and driver_a is not None and motor_a > driver_a:
            errors.append(f"Corrente {name}: motor {motor_a:g} A > driver {driver_a:g} A por canal.")
        elif motor["technology"] == "brushed_dc" and driver.get("backend") in ("drv8833_dual", "l298n_dual") and motor_a is None:
            pending.append(f"Corrente {name} do motor desconhecida; informe o valor da peça real.")
    if motor["technology"] == "bldc_hall" and driver.get("backend") == "planned_bldc":
        pending.append("Referência 0–5 V, direção, Hall e falha exigem circuito externo e firmware ainda não integrado.")
    if motor["technology"] == "stepservo" and driver.get("backend") == "planned_stepservo":
        pending.append("Pulso/direção com adaptação de nível e encoder exigem firmware ainda não integrado.")
    if driver.get("backend") not in ("bts_pwm", "drv8833_dual", "l298n_dual", "rc_pwm", "planned_bldc", "planned_stepservo"):
        pending.append("Driver cadastrado sem backend de firmware implementado.")
    if physical:
        if motor["technology"] == "brushed_dc" and driver.get("backend") in ("drv8833_dual", "l298n_dual") and any(
                motor.get(k) is None for k in ("nominal_a", "peak_a")):
            pending.append("Corrente do motor não cadastrada: antes da montagem, confirme corrente nominal e de partida dentro da capacidade por canal.")
        if driver.get("backend") in ("planned_bldc", "planned_stepservo") or driver.get("backend") not in (
                "bts_pwm", "drv8833_dual", "l298n_dual", "rc_pwm"):
            errors.append("Este backend ainda não comanda saídas físicas neste firmware.")
        if motor["technology"] == "rc_pwm" and motor.get("name") not in ("TowerPro MG996R", "SG90"):
            errors.append("Servo PWM cadastrado sem calibração de pulsos e limites no firmware.")
        if motor["technology"] == "brushed_dc" and motor.get("drive_kind") not in ("dc_3_6v", "bts7960_12v"):
            errors.append("Motor DC cadastrado sem backend de pinagem homologado.")
    return errors, list(dict.fromkeys(pending))

def hardware_pairs(hardware: dict, physical=False) -> tuple[list[str], list[str], dict]:
    rows = catalog(include_hidden=True)
    legacy_motors = {"dc_3_6v": "dc_3_6v", "bts7960_12v": "mabuchi_12v",
                     "bldc_ktc86": "ktc_86bls125_j"}
    legacy_servos = {"mg996r": "mg996r", "ht23_ec1000": "ht23_ec1000"}
    def by_model(model, role):
        return next((key for key, row in rows.items()
                     if row["role"] == role and row["name"].casefold() == str(model).casefold()), None)
    pairs = [
        ("Esteiras", hardware.get("drive_motor_id") or legacy_motors.get(hardware.get("drive_kind")),
         hardware.get("drive_driver_id") or by_model(hardware.get("drive_driver_model"), "driver")),
        ("Canhão", hardware.get("cannon_motor_id") or legacy_servos.get(hardware.get("cannon_kind")),
         hardware.get("cannon_driver_id") or by_model(hardware.get("cannon_driver_model"), "driver")),
    ]
    # Nome antigo do gerador PWM aparece nos setups anteriores.
    if pairs[1][2] is None and hardware.get("cannon_driver_model") == "MG996R-PWM":
        pairs[1] = (pairs[1][0], pairs[1][1], "mg996r_pwm")
    errors, pending, selected = [], [], {}
    for label, motor_id, driver_id in pairs:
        motor, driver = rows.get(motor_id), rows.get(driver_id)
        if not motor or not driver:
            errors.append(f"{label}: motor/servo ou driver ausente do catálogo; carregue ou restaure o cadastro.")
            continue
        if driver.get("role") != "driver":
            errors.append(f"{label}: a seleção de driver não é um driver.")
            continue
        motor = dict(motor)
        if label == "Esteiras":
            for source, target in (("drive_nominal_a", "nominal_a"),
                                   ("drive_peak_a", "peak_a")):
                if hardware.get(source) not in ("", None):
                    motor[target] = _number(hardware[source])
        bad, warn = validate_pair(motor, driver, physical)
        errors.extend(f"{label}: {message}" for message in bad)
        pending.extend(f"{label}: {message}" for message in warn)
        selected[label] = (motor_id, driver_id, motor, driver)
    return errors, pending, selected

# Pacote do protótipo: o catálogo físico não inclui Kalatec.
for _id in ('ktc_86bls125_j','ht23_ec1000','ktc_j_dr_bldc750','ktc_dr23ec_k'):
    BUILTINS.pop(_id, None)
INTERFACE_BOARDS = {'none': INTERFACE_BOARDS['none']}
BUILTINS['mg996r_pwm']['channels'] = 3
BUILTINS['mg996r_pwm']['pins'] = 'GPIO18 pan, GPIO19 tilt, GPIO4 plataforma; fonte separada dimensionada para três servos.'
BUILTINS['sg90'] = dict(role='servo', name='SG90', technology='rc_pwm',
                        voltage_v=5, min_v=4.8, max_v=6, control='PWM 50 Hz',
                        cannon_kind='mg996r', notes='Servo RC PWM para pan, tilt, câmera ou foco; alimentação externa e GND comum.')
