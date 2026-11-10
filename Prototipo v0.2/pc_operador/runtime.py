"""BLAZE — runtime contínuo do PC. Subsistemas reunidos em um arquivo."""

from __future__ import annotations


# ===== CONFIG =====
import json
import sys

from dataclasses import dataclass

from pathlib import Path

from typing import Any

ROOT = Path(__file__).resolve().parent

def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Esperava objeto JSON em {path}")
    return data

def calibration_collection(record):
    """Aceita tanto o arquivo anterior (um mapa) como os perfis nomeados."""
    if not isinstance(record, dict):
        return {'active':'', 'profiles':{}}
    if isinstance(record.get('profiles'), dict):
        profiles = {str(k):v for k,v in record['profiles'].items() if isinstance(v,dict)}
        active = str(record.get('active',''))
        return {'active':active if active in profiles else '', 'profiles':profiles}
    if record.get('angles'):
        return {'active':'Calibração anterior',
                'profiles':{'Calibração anterior':record}}
    return {'active':'', 'profiles':{}}

def saved_camera_calibrations(official_name):
    records = read_json(ROOT / 'parameters_setups/user/camera_cannon_calibrations.json')
    return calibration_collection(records.get(official_name,{}))

def local_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path

def redacted_source(source: int | str) -> str:
    """Avoid exposing RTSP credentials in diagnostics and screen text."""
    value = str(source)
    if '://' not in value:
        return value
    scheme, tail = value.split('://', 1)
    authority, separator, remainder = tail.partition('/')
    if '@' not in authority:
        return value
    return scheme + '://***@' + authority.rsplit('@', 1)[1] + (separator + remainder if separator else '')

def legacy_path(value: str | Path) -> Path:
    """Encontra um setup no diretório local ou na árvore do repositório BLAZE."""
    path = local_path(value)
    if path.is_file() or Path(value).is_absolute():
        return path
    filename = Path(value).name
    for ancestor in (ROOT, *ROOT.parents):
        found = ancestor / "visao/fire_monitor_RGB_monocular/parameters_setups/user" / filename
        if found.is_file():
            return found
    return path

@dataclass(frozen=True)
class VisionSettings:
    params: dict[str, Any]
    calibration: dict[str, Any]
    fire_model: Path | None
    person_model: Path | None
    source_name: str
    firefighter_model: Path | None = None

class AppConfig:
    def __init__(self, filename: str | Path | None = None):
        # A operação usa exclusivamente a combinação aprovada ao final dos notebooks.
        self.filename = local_path(filename) if filename else ROOT / "parameters_setups/official/active.json"
        if filename is None and not self.filename.is_file():
            raise FileNotFoundError("Nenhum setup oficial. Selecione e ative a combinação na seção 7 do notebook.")
        self.data: dict[str, Any] = {}
        self.vision: VisionSettings | None = None
        self.runtime_camera_override: int | None = None
        self.reload()

    def reload(self) -> None:
        base = read_json(ROOT / "config.example.json")
        custom = read_json(self.filename)
        self.data = {**base, **custom}
        for section in ("camera", "esp", "vision", "xbox_axes", "xbox_buttons", "geometry"):
            self.data[section] = {**base.get(section, {}), **custom.get(section, {})}
        if self.runtime_camera_override is not None:
            self.data['vision']['camera_source'] = self.runtime_camera_override
            self.data['vision']['source_type'] = 'camera'
            self.data['camera']['source'] = self.runtime_camera_override
        control = self.data.setdefault('control', {})
        bindings = control.setdefault('input_bindings', {})
        if int(control.get('schema_version', 0)) < 4:
            bindings.pop('camera_toggle', None)
            bindings['camera_left'] = {'kind': 'hat', 'index': 0, 'direction': [-1, 0]}
            bindings['camera_right'] = {'kind': 'hat', 'index': 0, 'direction': [1, 0]}
            bindings['stop'] = {'kind': 'hat', 'index': 0, 'direction': [0, -1]}
        self.vision = self._vision_settings()

    def _find_model(self, candidate: str, fallback: str) -> Path | None:
        # O notebook pode salvar caminho absoluto da máquina em que foi calibrado.
        for value in (candidate, fallback):
            if not value:
                continue
            path = local_path(value)
            probes = [path, ROOT / "models" / Path(value).name]
            probes.extend(ancestor / "visao/fire_monitor_RGB_monocular/models" / Path(value).name
                          for ancestor in (ROOT, *ROOT.parents))
            for probe in probes:
                if probe.is_file():
                    return probe.resolve()
        return None

    def _vision_settings(self) -> VisionSettings:
        section = self.data["vision"]
        source = legacy_path(section.get("legacy_setup_file", ""))
        saved = read_json(source) if source.is_file() else {}
        chosen = section.get("legacy_setup_name", "")
        if not chosen and saved:
            chosen = max(saved, key=lambda name: str(saved[name].get("saved_at", "")))
        entry = saved.get(chosen, {}) if chosen else {}
        params = dict(entry.get("config", entry)) if isinstance(entry, dict) else {}
        calibration = entry.get("servo_calibration", {}) if isinstance(entry, dict) else {}
        calib_path = legacy_path(section.get("legacy_calibration_file", ""))
        if calib_path.is_file():
            calibration = read_json(calib_path)
        params.update(section.get("params_override", {}))
        calibration.update(section.get("calibration_override", {}))
        # A calibração física pertence à combinação completa e é realizada após
        # gravar o firmware. Ela não altera a assinatura do firmware.
        official_name = self.data.get('_official', {}).get('name', '')
        collection = saved_camera_calibrations(official_name)
        if collection['active']:
            calibration = collection['profiles'][collection['active']]
        return VisionSettings(
            params=params,
            calibration=calibration or {},
            fire_model=self._find_model(str(section.get("fire_model", "")), str(params.get("fire_model_path", ""))),
            person_model=self._find_model(str(section.get("person_model", "")), str(params.get("person_model_path", ""))),
            source_name=str(section.get("setup_label") or chosen or "parâmetros padrão"),
            firefighter_model=self._find_model(str(section.get("firefighter_model", "")), ""),
        )

    def camera_source(self) -> int | str:
        raw = self.data["camera"].get("source", 0)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return str(raw)


# ===== PROTOCOL =====
import json

from typing import Any

MAX_LINE = 4096  # Permite telemetria completa de setups com nomes longos.
REQUIRED_PROTOCOL_VERSION = 5  # Políticas de pessoa e sensibilidade de curva por setup.

def protocol_compatible(telemetry):
    try:
        return int(telemetry.get('protocol_version', 0)) >= REQUIRED_PROTOCOL_VERSION
    except (TypeError, ValueError, AttributeError):
        return False

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

def coupled_manual_pose(pan: float, tilt: float, camera_pan: float,
                        stick_x: float, stick_y: float, camera_direction: int,
                        dt: float, camera_speed: float = 45.,
                        edge_offset_px: float = 8., view_width_px: float = 350.,
                        recenter_step_deg: float = 20.) -> tuple[float, ...]:
    """Cinemática ilustrativa da câmera (1 eixo) e do canhão no modo manual.

    Os ângulos são relativos ao chassi: a câmera usa 0..180 com 90 à frente,
    enquanto o pan do canhão usa -180..180 com zero à frente. O eixo vertical
    pertence só ao canhão. Os servos reais não usam esta função de simulação.
    """
    dt = clamp(dt, 0, .12)
    half_fov = 60.  # abertura horizontal total de 120 graus na ilustração
    margin = max(2., half_fov * max(0., edge_offset_px) /
                 max(1., view_width_px / 2.))
    guard = max(5., half_fov - margin)
    stick_x = 0. if abs(stick_x) < .08 else clamp(stick_x, -1, 1)
    stick_y = 0. if abs(stick_y) < .08 else clamp(stick_y, -1, 1)
    direction = int(clamp(camera_direction, -1, 1))
    pan = clamp(pan + stick_x * 90. * dt, -180, 180)
    tilt = clamp(tilt - stick_y * 45. * dt, 0, 90)
    camera_pan = clamp(camera_pan + direction * camera_speed * dt, 0, 180)
    camera_axis = camera_pan - 90.
    relative = pan - camera_axis
    if direction:
        # A plataforma desloca o enquadramento; o canhão só acompanha quando
        # o retículo chegaria à margem oposta do campo de visão.
        pan = clamp(camera_axis + clamp(relative, -guard, guard), -180, 180)
    elif stick_x and abs(relative) > guard:
        # O canhão se move primeiro. Perto da borda, a câmera gira para
        # recentralizar em um passo discreto, limitado pelo fim do curso.
        camera_pan = clamp(camera_pan + (1 if relative > 0 else -1) *
                           clamp(recenter_step_deg, 1, 60), 0, 180)
        camera_axis = camera_pan - 90.
        pan = clamp(camera_axis + clamp(pan - camera_axis, -guard, guard), -180, 180)
    else:
        pan = clamp(camera_axis + clamp(relative, -guard, guard), -180, 180)
    aim_x = clamp((pan - (camera_pan - 90.)) / half_fov, -.96, .96)
    aim_y = clamp((45. - tilt) / 45. * .90, -.90, .90)
    return pan, tilt, camera_pan, aim_x, aim_y

def encode_message(message: dict[str, Any]) -> bytes:
    data = (json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_LINE:
        raise ValueError("Mensagem maior que o limite do protótipo")
    return data

def decode_telemetry(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_LINE:
        raise ValueError("Telemetria maior que o limite")
    message = json.loads(line)
    if not isinstance(message, dict) or message.get("type") != "telemetry":
        raise ValueError("Mensagem de telemetria inválida")
    return message

def control_message(input_state: dict[str, Any], vision_state: dict[str, Any]) -> dict[str, Any]:
    get = input_state.get
    return {
        "type": "control",
        "seq": int(get("seq", 0)),
        "mode": "auto" if get("requested_mode") == "auto" else "manual",
        "drive_x": clamp(get("drive_x", 0), -1, 1),
        "drive_y": clamp(get("drive_y", 0), -1, 1),
        "steering_sensitivity_percent": clamp(get("steering_sensitivity_percent", 50), 0, 100),
        "cannon_x": clamp(get("cannon_x", 0), -1, 1),
        "cannon_y": clamp(get("cannon_y", 0), -1, 1),
        "cannon_rate_deg_s": clamp(get("cannon_rate_deg_s", 90), 1, 360),
        "camera_rate_deg_s": clamp(get("camera_rate_deg_s", 90), 1, 360),
        "auto_rate_deg_s": clamp(get("auto_rate_deg_s", 90), 1, 360),
        "auto_pan": clamp(vision_state.get("pan", 90), 0, 180),
        "auto_tilt": clamp(vision_state.get("tilt", 90), 0, 180),
        "manual_target_valid": bool(get("manual_target_valid", False)),
        "manual_pan": clamp(get("manual_pan", 90), 0, 180),
        "manual_tilt": clamp(get("manual_tilt", 90), 0, 180),
        "camera_pan": clamp(get("camera_pan_deg", 90), 0, 180),
        "calibrating": bool(get("calibrating", False)),
        "calibration_pan": clamp(get("calibration_pan", 90), 0, 180),
        "calibration_tilt": clamp(get("calibration_tilt", 90), 0, 180),
        "camera_min": clamp(get("camera_min", 0), 0, 180),
        "camera_max": clamp(get("camera_max", 180), 0, 180),
        "pan_min": clamp(get("pan_min", 0), 0, 180),
        "pan_max": clamp(get("pan_max", 180), 0, 180),
        "tilt_min": clamp(get("tilt_min", 0), 0, 180),
        "tilt_max": clamp(get("tilt_max", 180), 0, 180),
        "vision_valid": bool(vision_state.get("valid", False)),
        "target_valid": bool(vision_state.get("target_valid", False)),
        "person_detected": bool(vision_state.get("person_detected", False)),
        "person_policy": int(clamp(get("person_policy", 0), 0, 2)),
        "cool_manual": bool(get("cool_manual", False)),
        "cool_internal": bool(get("cool_internal", False)),
        "cool_external": bool(get("cool_external", False)),
        "jet_enable": bool(vision_state.get("jet_permitted", False) if get("requested_mode") == "auto"
                           else get("jet_enable", False)),
        "water_on": bool(get("water_on", False)),
        "pressure": clamp(get("pressure", 0), 0, 1),
        "focus": clamp(get("focus", 0), 0, 1),
        "brake": bool(get("brake", False)),
        "emergency": bool(get("emergency", False)),
        "leds_on": bool(get("leds_on", False)),
        "stop": bool(get("stop", False)),
        "rearm": bool(get("rearm", False)),
    }


# ===== DISCOVERY =====
import threading

def find_service(service_type: str, name_part: str, seconds: float = 2.0):
    """Retorna (IPv4, porta) de serviço cujo nome contenha `name_part`."""
    if not name_part:
        return None
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return None
    result = []
    found = threading.Event()

    class Listener(ServiceListener):
        def add_service(self, zc, kind, name):
            if name_part.casefold() not in name.casefold():
                return
            info = zc.get_service_info(kind, name, timeout=500)
            if info:
                addresses = [x for x in info.parsed_addresses() if ":" not in x]
                if addresses:
                    result.append((addresses[0], info.port))
                    found.set()

        def update_service(self, zc, kind, name):
            self.add_service(zc, kind, name)

        def remove_service(self, zc, kind, name):
            pass

    try:
        zc = Zeroconf()
    except OSError:
        return None
    try:
        browser = ServiceBrowser(zc, service_type, Listener())
        found.wait(seconds)
        browser.cancel()
    finally:
        zc.close()
    return result[0] if result else None

def discover_services(service_type: str, seconds: float = 1.5) -> list[tuple[str, str, int]]:
    """Lista anúncios mDNS disponíveis (nome, IPv4, porta), sem varrer a rede."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []
    found: dict[str, tuple[str, str, int]] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, kind, name):
            info = zc.get_service_info(kind, name, timeout=400)
            if info:
                addresses = [address for address in info.parsed_addresses() if ':' not in address]
                if addresses:
                    found[name] = (name.removesuffix('.' + service_type), addresses[0], info.port)

        def update_service(self, zc, kind, name):
            self.add_service(zc, kind, name)

        def remove_service(self, zc, kind, name):
            found.pop(name, None)

    try:
        zc = Zeroconf()
    except OSError:
        return []
    try:
        browser = ServiceBrowser(zc, service_type, Listener())
        import time
        time.sleep(seconds)
        browser.cancel()
    finally:
        zc.close()
    return sorted(found.values())


# ===== KINEMATICS =====
import math

def estimate(left_command: float, right_command: float, geometry: dict) -> dict | None:
    """Converte comando PWM normalizado em estimativa usando RPM calibrada.

    A velocidade lateral do chassi diferencial no referencial do próprio robô é
    zero. Coordenadas globais X/Y exigem orientação medida ou odometria.
    """
    try:
        radius = float(geometry["sprocket_radius_m"])
        width = float(geometry["track_width_m"])
        max_rpm = float(geometry["output_max_rpm"])
        left, right = float(left_command), float(right_command)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (radius, width, max_rpm, left, right)):
        return None
    if radius <= 0 or width <= 0 or max_rpm <= 0:
        return None
    left_rpm, right_rpm = left * max_rpm, right * max_rpm
    left_mps = left_rpm * (2 * math.pi * radius) / 60
    right_mps = right_rpm * (2 * math.pi * radius) / 60
    return {"left_rpm_est": left_rpm, "right_rpm_est": right_rpm,
            "left_mps_est": left_mps, "right_mps_est": right_mps,
            "vx_body_mps_est": (left_mps + right_mps) / 2,
            "vy_body_mps_est": 0., "yaw_rad_s_est": (right_mps - left_mps) / width}


# ===== CONTROLS =====
import threading

import time

class OperatorInputs:
    def __init__(self, axes: dict, buttons: dict, joystick_debug: bool = False,
                 preferred_index: int = 0, speed_limit_rpm: float = 80.,
                 calibrated_max_rpm: float = 80., bindings: dict | None = None):
        self.axes, self.buttons = axes, buttons
        self.joystick_debug = joystick_debug
        self.preferred_index = preferred_index
        self._lock = threading.Lock()
        self.requested_mode = "manual"
        self.ack_mode: str | None = None
        self.jet_virtual_ack = False
        self.last_ack = 0.0
        self.cool_internal = False
        self.cool_external = False
        self.jet_enable = False
        self.water_on = False
        self.pressure = 0.0
        self.focus = 0.0
        self.brake = False
        self.emergency = False
        self.lt = 0.0
        self._want_link = False
        self._held_since = {'link_hold': None, 'stop': None}
        self._held_fired = {'link_hold': False, 'stop': False}
        indices={'lt':('axis',4),'drive_x':('axis',0),'drive_y':('axis',1),
                 'lb':('button',4),'rt':('axis',5),'rb':('button',5),
                 'r3':('button',9),'cannon_x':('axis',2),'cannon_y':('axis',3),
                 'mode':('button',2),'cool_internal':('button',0),
                 'cool_external':('button',1),'leds':('button',3),
                 'camera_left':('hat',0),'camera_right':('hat',0),'overlay':('hat',0),
                 'link_hold':('button',7),'stop':('hat',0),'water':('button',6)}
        self.bindings={name:{'kind':kind,'index':index} for name,(kind,index) in indices.items()}
        self.bindings.update(bindings or {})
        self.bindings.pop('camera_toggle', None)
        for key,direction in [('camera_left',[-1,0]),('camera_right',[1,0]),
                              ('overlay',[0,1]),('stop',[0,-1])]:
            self.bindings[key].setdefault('direction',direction)
        self.leds_on = False
        self.overlay_visible = True
        self.camera_pan_deg = 90.0
        self.camera_scan_direction = 1
        self.camera_last_update = time.monotonic()
        self.camera_last_motion = self.camera_last_update
        self.camera_settle_until = self.camera_last_update + .45
        self.camera_edge_last = 0.0
        self.camera_edge_press_since = None
        self.camera_edge_latched = False
        self.servo_pan_commanded = None
        self.servo_tilt_commanded = None
        self.manual_target_pan = self.manual_target_tilt = None
        self.auto_follow_pan = self.auto_follow_tilt = None
        self.camera_left = self.camera_right = False
        self.speed_limit_rpm = float(speed_limit_rpm)
        self.calibrated_max_rpm = float(calibrated_max_rpm)
        self.speed_limit_percent = 100.
        self.steering_sensitivity_percent = 50.
        self.person_policy = 0  # 0 rearme manual, 1 auto após 1 s, 2 sem bloqueio por pessoa
        self.person_active = False
        self.person_latched = False
        self.person_clear_since = None
        self.person_auto_rearmed = False
        self.stop = True  # rearme explícito após a inicialização
        self.link_enabled = False
        self.rearm_until = 0.0
        self.drive_x = self.drive_y = self.cannon_x = self.cannon_y = 0.0
        self.pressed: set[str] = set()
        self.joy = None
        self.previous_buttons: dict[str, bool] = {}
        self._pending_actions: list[str] = []
        try:
            import pygame
            pygame.init()
            pygame.joystick.init()
            self.pygame = pygame
            self._open_joystick()
        except (ImportError, Exception):
            self.pygame = None

    def _open_joystick(self):
        if self.pygame and self.pygame.joystick.get_count() > self.preferred_index >= 0:
            self.joy = self.pygame.joystick.Joystick(self.preferred_index)
            self.joy.init()

    def key(self, keysym: str, pressed: bool):
        with self._lock:
            if pressed:
                self.pressed.add(keysym.lower())
            else:
                self.pressed.discard(keysym.lower())

    def action(self, name: str):
        with self._lock:
            if name == "mode":
                self.requested_mode = "auto" if self.requested_mode == "manual" else "manual"
                self.jet_enable = False
            elif name == "cool_internal":
                self.cool_internal = not self.cool_internal
            elif name == "cool_external":
                self.cool_external = not self.cool_external
            elif name == "jet":
                self.jet_enable = not self.jet_enable
            elif name == "water":
                self.water_on = not self.water_on
                if not self.water_on:self.jet_enable=False
            elif name == "leds":
                self.leds_on = not self.leds_on
            elif name == "overlay":
                self.overlay_visible = not self.overlay_visible
            elif name == "stop":
                self.stop = True
                self.emergency = True
                self.water_on = False
                self.jet_enable = False
                self.rearm_until = 0.0
            elif name == "rearm":
                if self.link_enabled and abs(self.drive_x) <= .05 and abs(self.drive_y) <= .05:
                    self.emergency = False
                    self.stop = False
                    self.rearm_until = time.monotonic() + .6

    def select_stop_hold(self, duration: float) -> None:
        """Seleciona a política na soltura; a seta pressionada bloqueia movimento."""
        if duration < .25:
            return
        with self._lock:
            if duration >= 3.:
                self.person_policy = 2
                self.person_latched = False
                self.person_auto_rearmed = True
                self.person_clear_since = None
                if (self.link_enabled and self._want_link and not self.stop and
                        not self.emergency and abs(self.drive_x) <= .05 and
                        abs(self.drive_y) <= .05):
                    self.rearm_until = time.monotonic() + .6
            elif duration >= 1.:
                self.person_policy = 1
                self.person_auto_rearmed = False
                self.person_clear_since = time.monotonic() if not self.person_active else None
            else:
                self.person_policy = 0
                if self.emergency or self.stop or self.person_latched:
                    if self.link_enabled and abs(self.drive_x) <= .05 and abs(self.drive_y) <= .05:
                        self.emergency = self.stop = False
                        self.person_latched = False
                        self.rearm_until = time.monotonic() + .6
                else:
                    self.emergency = self.stop = True
                    self.water_on = self.jet_enable = False
                    self.rearm_until = 0.

    def update_person_safety(self, detected: bool, vision_recent: bool) -> None:
        """Aplica a política selecionada sem rearme automático da parada do operador."""
        now = time.monotonic()
        with self._lock:
            if detected:
                self.person_active = True
                if self.person_policy != 2:
                    self.person_latched = True
                self.person_clear_since = None
                self.person_auto_rearmed = False
            elif self.person_active:
                self.person_active = False
                self.person_clear_since = now if vision_recent else None
            if not vision_recent:
                self.person_clear_since = None
            elif (self.person_clear_since is None and not detected and
                  self.person_policy in (1, 2)):
                self.person_clear_since = now
            if (self.person_policy in (1, 2) and not self.person_auto_rearmed and
                    self.person_clear_since is not None and now-self.person_clear_since >= 1. and
                    self.link_enabled and self._want_link and not self.stop and not self.emergency and
                    abs(self.drive_x) <= .05 and abs(self.drive_y) <= .05):
                self.rearm_until = now + .25
                self.person_auto_rearmed = True
                self.person_latched = False

    def acknowledge_mode(self, mode: str, jet_virtual: bool):
        with self._lock:
            self.ack_mode = mode if mode in ("manual", "auto") else None
            self.jet_virtual_ack = bool(jet_virtual)
            self.last_ack = time.monotonic()

    def set_link(self, connected: bool):
        with self._lock:
            was_connected=self.link_enabled
            if not connected:
                self.stop = True
                self.jet_enable = False
                self.rearm_until = 0.0
                self.ack_mode = None
                self.jet_virtual_ack = False
                if was_connected:
                    self._want_link = False  # requer segurar Start novamente após perda do enlace
            self.link_enabled = connected
            if connected and not was_connected and self._want_link and not self.emergency:
                self.stop=False
                self.rearm_until=time.monotonic()+.6

    @staticmethod
    def _axis(value: float) -> float:
        return 0.0 if abs(value) < .08 else max(-1., min(1., float(value)))

    def poll(self):
        """Deve ser executado pela thread da HMI; não bloqueia captura nem rede."""
        if self.pygame:
            self.pygame.event.pump()
            if self.joy is None and self.pygame.joystick.get_count():
                self._open_joystick()
        with self._lock:
            keys = self.pressed
            keyboard = (int("d" in keys) - int("a" in keys),
                        int("s" in keys) - int("w" in keys),
                        int("right" in keys) - int("left" in keys),
                        int("down" in keys) - int("up" in keys))
            x, y, cx, cy = map(float, keyboard)
            if self.joy is not None and self.joy.get_init():
                axes=[self.joy.get_axis(i) for i in range(self.joy.get_numaxes())]
                buttons={i for i in range(self.joy.get_numbuttons()) if self.joy.get_button(i)}
                hats=[self.joy.get_hat(i) for i in range(self.joy.get_numhats())]
                def analog(name):
                    bind=self.bindings[name];index=int(bind.get('index',-1))
                    return axes[index] if bind.get('kind')=='axis' and 0<=index<len(axes) else 0.
                def trigger(name):
                    bind=self.bindings[name];raw=analog(name)
                    rest=float(bind.get('rest',-1.));active=float(bind.get('active',1.))
                    return max(0.,min(1.,(raw-rest)/(active-rest))) if abs(active-rest)>.1 else 0.
                def pressed(name):
                    bind=self.bindings[name];index=int(bind.get('index',-1))
                    if bind.get('kind')=='button':return index in buttons
                    if bind.get('kind')=='hat' and 0<=index<len(hats):
                        return tuple(bind.get('direction',(0,0)))==tuple(hats[index])
                    return False
                values={name:analog(name) for name in ('drive_x','drive_y','cannon_x','cannon_y')}
                if self.joystick_debug:
                    print("Xbox eixos", values)
                x, y = values.get("drive_x", 0), values.get("drive_y", 0)
                cx, cy = values.get("cannon_x", 0), values.get("cannon_y", 0)
                self.lt=trigger('lt')
                self.pressure=trigger('rt') if self.water_on else 0.
                self.brake=pressed('lb')
                self.camera_left, self.camera_right = pressed('camera_left'), pressed('camera_right')
                self.focus=max(0.,min(1.,self.focus+(int(pressed('rb'))-int(pressed('r3')))*.015))
                now=time.monotonic()
                for name,duration in [('link_hold',2.)]:
                    if pressed(name):
                        if self._held_since[name] is None:self._held_since[name]=now
                        if now-self._held_since[name]>=duration and not self._held_fired[name]:
                            self._held_fired[name]=True
                            if not self._want_link:
                                if abs(x)<.08 and abs(y)<.08 and self.lt<.08 and self.pressure<.08:
                                    self._want_link=True
                                    # A conexão já pode estar ativa quando Start
                                    # é segurado. Rearmar também neste caso.
                                    if self.link_enabled:
                                        self.stop=False
                                        self.rearm_until=now+.6
                            else:self._want_link=False;self.stop=True;self.water_on=False
                    else:self._held_since[name]=None;self._held_fired[name]=False
                if pressed('stop'):
                    if self._held_since['stop'] is None:self._held_since['stop']=now
                elif self._held_since['stop'] is not None:
                    duration=now-self._held_since['stop']
                    self._held_since['stop']=None
                    self._pending_actions.append(('stop_hold',duration))
                for name in ('mode','cool_internal','cool_external','leds','overlay','water'):
                    current=pressed(name)
                    if current and not self.previous_buttons.get(name, False):
                        # action() toma o mesmo lock, então faça a mudança após poll().
                        self._pending_actions.append(name)
                    self.previous_buttons[name] = current
            else:
                # Perda do Xbox durante a operação exige novo Start de 2 s.
                x = y = cx = cy = 0.
                self.lt = self.pressure = 0.
                self.brake = False
                self.camera_left = self.camera_right = False
                self._want_link = False
                self.stop = True
                self.water_on = False
                self.jet_enable = False
                self._held_since = {'link_hold': None, 'stop': None}
                self._held_fired = {'link_hold': False, 'stop': False}
                self.previous_buttons.clear()
            self.drive_x, self.drive_y = self._axis(x), self._axis(y)
            # O stick direito tem zona neutra maior: ruído perto do centro
            # não integra pequenos comandos contínuos no alvo do canhão.
            self.cannon_x = 0. if abs(cx) < .14 else self._axis(cx)
            self.cannon_y = 0. if abs(cy) < .14 else self._axis(cy)
            pending = self._pending_actions[:]
            self._pending_actions.clear()
        for name in pending:
            if isinstance(name,tuple) and name[0]=='stop_hold':
                self.select_stop_hold(name[1])
            else:self.action(name)

    def snapshot(self) -> dict:
        with self._lock:
            x, y = self.drive_x, self.drive_y
            scale = clamp(self.speed_limit_percent / 100., 0., 1.)
            throttle=self.lt if self._want_link and not self.brake else 0.
            x, y = x * scale * throttle, y * scale * throttle
            return {
                "mode": self.ack_mode or self.requested_mode,
                "requested_mode": self.requested_mode,
                "drive_x": x if self.link_enabled and self._held_since['stop'] is None else 0.,
                "drive_y": y if self.link_enabled and self._held_since['stop'] is None else 0.,
                "steering_sensitivity_percent": self.steering_sensitivity_percent,
                "throttle": self.lt if self._want_link and not self.brake else 0.,
                "cannon_x": self.cannon_x if self.link_enabled else 0.,
                "cannon_y": self.cannon_y if self.link_enabled else 0.,
                "manual_target_valid": (self.manual_target_pan is not None and
                                        self.manual_target_tilt is not None and self.link_enabled),
                "manual_pan": self.manual_target_pan if self.manual_target_pan is not None else 90.,
                "manual_tilt": self.manual_target_tilt if self.manual_target_tilt is not None else 90.,
                "auto_follow_pan": self.auto_follow_pan,
                "auto_follow_tilt": self.auto_follow_tilt,
                "cannon_rate_deg_s": 65.,
                "cool_manual": self.cool_internal or self.cool_external,
                "cool_internal": self.cool_internal,
                "cool_external": self.cool_external,
                "jet_enable": bool(self.water_on and self.pressure > .05),
                "water_on": self.water_on,
                "pressure": self.pressure,
                "focus": self.focus,
                "brake": self.brake,
                "emergency": self.emergency,
                "person_policy": self.person_policy,
                "person_latched": self.person_latched,
                "leds_on": self.leds_on,
                "overlay_visible": self.overlay_visible,
                "camera_pan_deg": self.camera_pan_deg,
                "camera_settled": time.monotonic() >= getattr(self, "camera_settle_until", self.camera_last_motion + .45),
                "camera_left": self.camera_left,
                "camera_right": self.camera_right,
                "want_link": self._want_link,
                "start_hold_seconds": (max(0.,time.monotonic()-self._held_since['link_hold'])
                                       if self._held_since['link_hold'] is not None else 0.),
                "stop_hold_seconds": (max(0.,time.monotonic()-self._held_since['stop'])
                                      if self._held_since['stop'] is not None else 0.),
                "jet_virtual_ack": self.jet_virtual_ack and time.monotonic() - self.last_ack < .75,
                "stop": (self.stop or not self._want_link or
                         (self._held_since['stop'] is not None and
                          time.monotonic()-self._held_since['stop'] >= .25)),
                "rearm": time.monotonic() <= self.rearm_until,
            }

    def update_camera(self, vision_record: dict, mode: str, vision_recent: bool,
                      person_blocked: bool, settings: dict | None = None,
                      frame_shape=(540,960,3), calibration=None, params=None):
        """Move os eixos independentes e recentraliza o vídeo perto da borda."""
        settings = settings or {}
        calibration = calibration or {}
        params = params or {}
        with self._lock:
            now = time.monotonic()
            dt = min(.15, max(0., now - self.camera_last_update))
            self.camera_last_update = now
            if self.stop or not self._want_link or self.emergency:
                self.manual_target_pan = self.manual_target_tilt = None
                self.auto_follow_pan = self.auto_follow_tilt = None
                self.camera_edge_press_since = None
                return
            margin=float(settings.get('camera_edge_offset_px',8))
            def bounds():
                return camera_view_limits(frame_shape,calibration,params,
                                          self.camera_pan_deg,margin)
            # O pan do canhão usa seu próprio curso mecânico. As bordas do
            # vídeo servem apenas de gatilho para o giro da plataforma.
            fixed_tilt_limits=camera_view_limits(frame_shape,calibration,params,
                                                 90.,margin)[1]
            physical_pan=(float(settings.get('pan_min',0.)),
                          float(settings.get('pan_max',180.)))
            physical_tilt=(max(float(settings.get('tilt_min',0.)),fixed_tilt_limits[0]),
                           min(float(settings.get('tilt_max',180.)),fixed_tilt_limits[1]))
            if physical_tilt[0]>physical_tilt[1]:
                physical_tilt=(float(settings.get('tilt_min',0.)),
                               float(settings.get('tilt_max',180.)))
            pan_now=(self.servo_pan_commanded if self.servo_pan_commanded is not None
                     else 90.)
            tilt_now=(self.servo_tilt_commanded if self.servo_tilt_commanded is not None
                      else 90.)
            if mode == 'manual':
                self.auto_follow_pan = self.auto_follow_tilt = None
                direction = int(self.camera_right) - int(self.camera_left)
                previous = self.camera_pan_deg
                self.camera_pan_deg = clamp(self.camera_pan_deg + direction *
                    min(float(settings.get('camera_manual_speed_deg_s', 45.)),
                        float(settings.get('calibrated_servo_rate_deg_s',360.))) * dt, 0, 180)
                rate=min(65., max(1., float(settings.get('cannon_rate_deg_s',90.))))
                pan_demand=((self.manual_target_pan if self.manual_target_pan is not None
                             else pan_now)+(self.camera_pan_deg-previous)*int(bool(direction))+
                            self.cannon_x*rate*dt)
                tilt_demand=(self.manual_target_tilt if self.manual_target_tilt is not None
                             else tilt_now)-self.cannon_y*rate*dt
                pan_demand=clamp(pan_demand,*physical_pan)
                tilt_demand=clamp(tilt_demand,*physical_tilt)
                width=max(2,frame_shape[1]);y=frame_shape[0]/2
                left,_=pixel_to_servos((margin,y),frame_shape,calibration,params,
                                       self.camera_pan_deg)
                right,_=pixel_to_servos((width-1-margin,y),frame_shape,
                                        calibration,params,self.camera_pan_deg)
                low,high=sorted((left,right))
                # A calibração pode mapear apenas ~20° da imagem. Não use essa
                # faixa para recortar o movimento físico do canhão.
                edge=(1 if pan_demand>=high else -1 if pan_demand<=low else 0)
                # O pan pode continuar sobre a borda quando o stick é solto.
                # Sem esta condição a câmera recebia saltos de 20° em repouso.
                pushing_edge = (not direction and edge and
                                self.cannon_x * edge > .20)
                if pushing_edge:
                    if self.camera_edge_press_since is None:
                        self.camera_edge_press_since=now
                    if (now-self.camera_edge_press_since>=.15 and
                        now>=self.camera_settle_until and
                        now-self.camera_edge_last>=.45):
                        step=clamp(settings.get('camera_recenter_step_deg',20),1,60)
                        moved=clamp(self.camera_pan_deg+edge*step,0,180)
                        if moved != self.camera_pan_deg:
                            self.camera_pan_deg=moved
                            self.camera_edge_last=now
                else:
                    self.camera_edge_press_since=None
                self.manual_target_pan=pan_demand
                self.manual_target_tilt=tilt_demand
                if abs(self.camera_pan_deg-previous) > 1e-4:
                    self.camera_last_motion = now
                    servo_rate=min(65.,max(1.,float(settings.get("calibrated_servo_rate_deg_s",90))))
                    self.camera_settle_until = now + max(.55, abs(self.camera_pan_deg-previous)/servo_rate+.35)
                return
            self.camera_edge_press_since = None
            self.manual_target_pan = self.manual_target_tilt = None
            if not vision_recent or person_blocked:
                self.auto_follow_pan = self.auto_follow_tilt = None
                return
            aim = vision_record.get('aim_px')
            size = int(vision_record.get('frame_width') or 0)
            if vision_record.get('target_valid') and aim and size > 0:
                offset = max(2, int(settings.get('camera_edge_offset_px', 8)))
                (pan_low,pan_high),_=bounds()
                edge_from_aim=(-1 if aim[0] <= offset else
                               1 if aim[0] >= size - 1 - offset else 0)
                edge_from_pan=(-1 if pan_now <= pan_low+1 else
                               1 if pan_now >= pan_high-1 else 0)
                at_edge=bool(edge_from_aim or edge_from_pan)
                if not at_edge and offset + 12 < aim[0] < size - 13 - offset:
                    self.camera_edge_latched = False
                if at_edge and now - self.camera_edge_last > .3:
                    left,_=pixel_to_servos((0,frame_shape[0]/2),frame_shape,
                                           calibration,params,self.camera_pan_deg)
                    right,_=pixel_to_servos((frame_shape[1]-1,frame_shape[0]/2),
                                            frame_shape,calibration,params,self.camera_pan_deg)
                    direction = (edge_from_aim or edge_from_pan)*(1 if right>=left else -1)
                    step = float(settings.get('camera_recenter_step_deg', 20.))
                    previous = self.camera_pan_deg
                    self.camera_pan_deg = clamp(self.camera_pan_deg + direction * step, 0, 180)
                    if abs(self.camera_pan_deg-previous) > 1e-4:
                        self.camera_last_motion = now
                        servo_rate=min(65.,max(1.,float(settings.get("calibrated_servo_rate_deg_s",90))))
                        self.camera_settle_until = now + max(.55,abs(self.camera_pan_deg-previous)/servo_rate+.35)
                    self.camera_edge_latched = True
                    self.camera_edge_last = now
            else:
                self.camera_edge_latched = False
                previous = self.camera_pan_deg
                self.camera_pan_deg += (self.camera_scan_direction *
                    min(float(settings.get('camera_scan_speed_deg_s', 12.)),
                        float(settings.get('calibrated_servo_rate_deg_s',360.))) * dt)
                if self.camera_pan_deg >= 180:
                    self.camera_pan_deg, self.camera_scan_direction = 180., -1
                elif self.camera_pan_deg <= 0:
                    self.camera_pan_deg, self.camera_scan_direction = 0., 1
                if abs(self.camera_pan_deg-previous) > 1e-4:
                    self.camera_last_motion = now
                    self.camera_settle_until = now + .45
            (pan_low,pan_high),(tilt_low,tilt_high)=bounds()
            target_pan=clamp(pan_now,pan_low,pan_high)
            target_tilt=clamp(tilt_now,*fixed_tilt_limits)
            if abs(target_pan-pan_now)>.5 or abs(target_tilt-tilt_now)>.5:
                self.auto_follow_pan=target_pan
                self.auto_follow_tilt=target_tilt
            else:
                self.auto_follow_pan=self.auto_follow_tilt=None


# ===== CAMERA =====
import threading

import time

from typing import Any

import cv2

class CameraSource:
    def __init__(self, source: int | str, reconnect_seconds: float = 2.0,
                 mdns_name: str = "", stream_path: str = "/live", fallback_source: str = ""):
        if isinstance(source, str) and source.strip().isdigit():
            source = int(source.strip())
        self.source = (str(local_path(source).resolve()) if isinstance(source, str)
                       and not source.startswith(('rtsp://','http://','https://'))
                       and local_path(source).is_file() else source)
        self.reconnect_seconds = reconnect_seconds
        self.mdns_name, self.stream_path, self.fallback_source = mdns_name, stream_path, fallback_source
        self._lock = threading.Lock()
        self._frame: Any = None
        self._timestamp = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_error = ''
        self.backend_name = ''

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="camera")
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            source = self.source
            if source == "auto-ip":
                service = find_service("_rtsp._tcp.local.", self.mdns_name)
                source = (f"rtsp://{service[0]}:{service[1]}{self.stream_path}"
                          if service else self.fallback_source)
            if not self._running:
                break
            if source == "":
                self.last_error = 'Fonte de vídeo não configurada.'
                time.sleep(self.reconnect_seconds)
                continue
            try:
                first_frame = None
                backend_used = 'automático'
                if isinstance(source, int) and sys.platform == 'win32':
                    failures = []
                    cap = None
                    for title, backend in (('DirectShow', cv2.CAP_DSHOW),
                                           ('Media Foundation', cv2.CAP_MSMF),
                                           ('automático', cv2.CAP_ANY)):
                        candidate = None
                        try:
                            candidate = cv2.VideoCapture(source, backend)
                            if candidate.isOpened():
                                for _ in range(5):
                                    ok, sample = candidate.read()
                                    if ok and sample is not None and sample.size:
                                        cap, first_frame = candidate, sample
                                        backend_used = title
                                        break
                            if cap is not None:
                                break
                            failures.append(title + ': sem quadro')
                        except Exception as exc:
                            failures.append(f'{title}: {type(exc).__name__}: {exc}')
                        finally:
                            if candidate is not None and candidate is not cap:
                                candidate.release()
                    if cap is None:
                        self.last_error = ('Câmera USB '+str(source)+' indisponível: '
                                           + '; '.join(failures)
                                           + '. Feche prévias do notebook e outros aplicativos.')
                        time.sleep(self.reconnect_seconds)
                        continue
                else:
                    cap = cv2.VideoCapture(source)
            except Exception as exc:
                self.last_error = f'Falha ao abrir {redacted_source(source)}: {type(exc).__name__}: {exc}'
                time.sleep(self.reconnect_seconds)
                continue
            if not cap.isOpened():
                self.last_error = f'Não foi possível abrir a fonte de vídeo: {redacted_source(source)}'
                cap.release()
                time.sleep(self.reconnect_seconds)
                continue
            self.backend_name = backend_used
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            is_recording = isinstance(source, str) and Path(source).is_file()
            file_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25) if is_recording else 0.0
            if is_recording and not 1 <= file_fps <= 120:
                file_fps = 25.0
            next_frame_at = time.monotonic()
            while self._running:
                if is_recording:
                    wait = next_frame_at - time.monotonic()
                    if wait > 0:time.sleep(min(wait,.1))
                    next_frame_at = max(next_frame_at + 1/file_fps,time.monotonic())
                if first_frame is not None:
                    ok, frame = True, first_frame
                    first_frame = None
                else:
                    ok, frame = cap.read()
                if not ok or frame is None:
                    if is_recording:
                        cap.set(cv2.CAP_PROP_POS_FRAMES,0)
                        next_frame_at=time.monotonic()
                        continue
                    self.last_error = f'A fonte de vídeo parou de fornecer quadros: {redacted_source(source)}'
                    break
                with self._lock:
                    self._frame = frame
                    self._timestamp = time.monotonic()
                    self.last_error = ''
            cap.release()
            with self._lock:
                self._frame = None
                self._timestamp = 0.0
            if self._running:
                time.sleep(self.reconnect_seconds)

    def latest(self, stale_seconds: float = 1.0):
        with self._lock:
            stamp = self._timestamp
            frame = None if self._frame is None else self._frame.copy()
        if frame is None or time.monotonic() - stamp > stale_seconds:
            return None, 0.0
        return frame, stamp

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def switch_source(self, source: int | str) -> None:
        self.stop()
        self.source = int(source.strip()) if isinstance(source,str) and source.strip().isdigit() else source
        with self._lock:
            self._frame, self._timestamp = None, 0.0
        self.start()


# ===== NETWORK =====
import concurrent.futures
import ipaddress
import subprocess
import socket

import threading

import time

from collections.abc import Callable

from typing import Any

USB_IDS = {'10C4', '1A86', '303A', '0403', '067B'}

def current_ipv4_subnets() -> list[str]:
    """Local /24 networks, with the Windows mobile hotspot first if present."""
    addresses = []
    if os.name == 'nt':
        try:
            script = ('Get-NetIPAddress -AddressFamily IPv4 | '
                      'Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress')
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive',
                                     '-Command', script], capture_output=True, text=True,
                                    timeout=8, check=True)
            parsed = json.loads(result.stdout)
            addresses = [parsed] if isinstance(parsed, dict) else parsed
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            addresses = [{'IPAddress': record[4][0], 'PrefixLength': 24}
                         for record in socket.getaddrinfo(socket.gethostname(), None,
                                                           socket.AF_INET)]
        except OSError:
            pass
    subnets = []
    for item in addresses:
        try:
            address = ipaddress.ip_address(item['IPAddress'])
            if not address.is_private or address.is_loopback or address.is_link_local:
                continue
            prefix = max(24, int(item.get('PrefixLength', 24)))
            net = ipaddress.ip_network(f'{address}/{prefix}', strict=False)
            if net.num_addresses <= 256 and str(net) not in subnets:
                subnets.append(str(net))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(subnets, key=lambda net: (not net.startswith('192.168.137.'), net))[:3]

def discover_tcp_hosts(port: int, subnet: str | None = None,
                       timeout: float = .22) -> list[str]:
    """Probe only one currently attached private /24 (or a specified /24)."""
    networks = [subnet] if subnet else current_ipv4_subnets()[:1]
    if not networks:
        return []
    net = ipaddress.ip_network(networks[0], strict=False)
    if not net.is_private or net.is_loopback or net.is_link_local or net.num_addresses > 256:
        raise ValueError('Informe uma rede privada com até 256 endereços.')
    hosts = [str(host) for host in net.hosts()]
    def available(host):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return host
        except (OSError, TimeoutError):
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        return [host for host in pool.map(available, hosts) if host]

def serial_candidates(selected: str = 'auto') -> list[str]:
    if selected and selected.lower() != 'auto':
        return [selected]
    from serial.tools import list_ports
    return [p.device for p in list_ports.comports()
            if (p.vid is not None and f'{p.vid:04X}' in USB_IDS) or
            any(word in (p.description or '').lower() for word in
                ('esp32', 'espressif', 'cp210', 'ch340', 'ch341', 'usb serial', 'ftdi'))]

def connected_wifi_ssids() -> set[str]:
    """Lê apenas a associação atual do Windows; SSID não mede qualidade ou internet."""
    import os
    import re
    import subprocess
    if os.name != 'nt':
        return set()
    try:
        result = subprocess.run(['netsh','wlan','show','interfaces'],
                                capture_output=True,text=True,errors='replace',timeout=4)
    except (OSError,subprocess.TimeoutExpired):
        return set()
    if result.returncode:
        return set()
    return {value.strip() for value in re.findall(
        r'^\s*SSID\s*:\s*(.+?)\s*$',result.stdout,re.MULTILINE)}

def join_local_esp_ap(ssid: str, password: str) -> None:
    """Conecta o Windows ao AP BLAZE somente se o SSID estiver visível.

    Essa troca pode desconectar o Wi-Fi atual; nunca a faz quando o AP está
    ausente. O XML transitório com a chave sai do disco após o netsh importá-lo.
    """
    import os
    import re
    import subprocess
    import tempfile
    from xml.sax.saxutils import escape
    if os.name != 'nt':
        raise RuntimeError('Entrada automática na rede local implementada para Windows.')
    try:
        scan = subprocess.run(['netsh','wlan','show','networks','mode=ssid'],
                              capture_output=True,text=True,errors='replace',timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError('O Windows não concluiu a busca da rede local BLAZE.') from exc
    visible = re.findall(r'^\s*SSID\s+\d+\s*:\s*(.*?)\s*$',scan.stdout,re.MULTILINE)
    if scan.returncode or ssid not in visible:
        raise ConnectionError(f'Rede local {ssid} ainda não está visível no Wi-Fi do PC.')
    xml = ('<?xml version="1.0" encoding="utf-8"?>'
           '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
           f'<name>{escape(ssid)}</name><SSIDConfig><SSID><name>{escape(ssid)}</name>'
           '</SSID></SSIDConfig><connectionType>ESS</connectionType>'
           '<connectionMode>manual</connectionMode><MSM><security><authEncryption>'
           '<authentication>WPA2PSK</authentication><encryption>AES</encryption>'
           '<useOneX>false</useOneX></authEncryption><sharedKey>'
           '<keyType>passPhrase</keyType><protected>false</protected>'
           f'<keyMaterial>{escape(password)}</keyMaterial></sharedKey>'
           '</security></MSM></WLANProfile>')
    try:
        with tempfile.TemporaryDirectory(prefix='blaze-ap-') as directory:
            filename = Path(directory) / 'wlan.xml'
            filename.write_text(xml, encoding='utf-8')
            imported = subprocess.run(['netsh','wlan','add','profile',f'filename={filename}',
                                       'user=current'],capture_output=True,text=True,
                                      errors='replace',timeout=15)
        if imported.returncode:
            raise ConnectionError('O Windows não aceitou o perfil da rede local BLAZE.')
        connected = subprocess.run(['netsh','wlan','connect',f'name={ssid}',f'ssid={ssid}'],
                                   capture_output=True,text=True,errors='replace',timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError('O Windows não concluiu a conexão com a rede local BLAZE.') from exc
    if connected.returncode:
        raise ConnectionError('O Windows não iniciou a conexão com a rede local BLAZE.')

class ESPConnection:
    # Reconexão não relaxa o intertravamento local de comandos ativos.
    TELEMETRY_TIMEOUT_SECONDS = 1.5
    COMMAND_FRESH_SECONDS = .25

    def __init__(self, host: str, port: int, get_command: Callable[[], dict[str, Any]],
                 on_telemetry: Callable[[dict[str, Any]], None], retry_seconds: float = 1.5,
                 transport: str = 'wifi_local', serial_port: str = 'auto', baudrate: int = 460800,
                 expected_signature: str = '',
                 preserve_wifi: bool = False):
        if transport not in ('usb', 'wifi_local'):
            raise ValueError('Escolha explicitamente USB ou Wi-Fi local no setup de comunicação.')
        self.host, self.port = host, port
        self.get_command, self.on_telemetry = get_command, on_telemetry
        self.retry_seconds = retry_seconds
        self.transport, self.serial_port, self.baudrate = transport, serial_port, baudrate
        self.expected_signature = expected_signature
        # A câmera IP pode depender do hotspot atual. A descoberta do AP BLAZE
        # não deve trocar a rede do Windows enquanto esse vídeo está em uso.
        self.preserve_wifi = bool(preserve_wifi)
        self.connected = False
        self.active_transport = ''
        self.last_error = ''
        self.last_packet_at = 0.0
        self.telemetry_count = 0
        self.disconnect_count = 0
        self.longest_gap_seconds = 0.0
        self.last_interval_seconds = 0.0
        self.round_trip_seconds = None
        self.full_telemetry_count = 0
        self.last_full_packet_at = 0.0
        self._sequence = 0
        self._last_ap_attempt = 0.0
        self.attempting = ''
        self._running = False
        self._thread: threading.Thread | None = None
        self._stream = None
        self._cancel = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            if self._running: return
            self._thread.join(timeout=.5)
            if self._thread.is_alive():
                raise RuntimeError('A porta anterior ainda está sendo liberada; aguarde e tente novamente.')
        self._cancel.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name='esp-link')
        self._thread.start()

    def _wifi(self):
        host = self.host
        if host == 'auto':
            service = find_service('_blaze._tcp.local.', 'blaze-esp32', seconds=1.0)
            candidates = [service[0]] if service else ['blaze-esp32.local']
            if getattr(self, '_last_wifi_host', '') not in candidates:
                candidates.insert(0, getattr(self, '_last_wifi_host', ''))
            error = None
            for candidate in filter(None, candidates):
                try:
                    sock = socket.create_connection((candidate, self.port), timeout=.7)
                    self._last_wifi_host = candidate
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.settimeout(.05)
                    return sock
                except (OSError, TimeoutError) as exc:
                    error = exc
            if self.preserve_wifi:
                # mDNS is not dependable on every Windows hotspot. Do not join
                # another network; find the ESP32 on the camera's current LAN.
                for candidate in discover_tcp_hosts(self.port):
                    try:
                        sock = socket.create_connection((candidate, self.port), timeout=.7)
                        self._last_wifi_host = candidate
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        sock.settimeout(.05)
                        return sock
                    except (OSError, TimeoutError):
                        continue
            raise ConnectionError('ESP32 ausente na rede atual. Confira Wi-Fi do firmware '
                                  'e hotspot do PC.') from error
        sock = socket.create_connection((host, self.port), timeout=2.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(.05)
        return sock

    def _wifi_local(self):
        import os
        import profile_manager
        credentials = profile_manager.local_link_credentials(create=False)
        if not credentials:
            raise ConnectionError('Crie e grave o firmware local pelo notebook antes de usar o AP.')
        ssid, password, _, _ = credentials
        if os.name == 'nt' and ssid not in connected_wifi_ssids():
            if self.preserve_wifi:
                raise ConnectionError(
                    'Câmera IP usa a rede atual; não será feita troca automática para o AP do ESP32. '
                    'Conecte o PC ao AP do ESP32 ou use USB.')
            if time.monotonic() - self._last_ap_attempt < 6:
                raise ConnectionError(f'Windows fora do SSID {ssid}; aguardando reconexão.')
            self._last_ap_attempt = time.monotonic()
            join_local_esp_ap(ssid, password)
            deadline=time.monotonic()+10
            while self._running and time.monotonic()<deadline and ssid not in connected_wifi_ssids():
                time.sleep(.35)
            if ssid not in connected_wifi_ssids():
                raise ConnectionError(f'Windows não permaneceu associado ao SSID {ssid}.')
        try:
            sock=socket.create_connection(('192.168.4.1',self.port),timeout=.8)
        except (OSError,TimeoutError) as exc:
            raise ConnectionError(f'SSID {ssid} ativo, mas ESP32 sem resposta TCP em 192.168.4.1:{self.port}.') from exc
        local_ip=sock.getsockname()[0]
        if not local_ip.startswith('192.168.4.'):
            sock.close()
            raise ConnectionError(f'Rota para o ESP32 saiu por {local_ip}; escolha a rede {ssid} no Windows.')
        self.wifi_ssid=ssid
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(.05)
        return sock

    def _usb(self, name: str):
        import serial
        device = serial.Serial(name, self.baudrate, timeout=0, write_timeout=.12)
        # A abertura de COM pode reiniciar a placa. Descarte bytes de boot antigos.
        device.reset_input_buffer()
        return device

    @staticmethod
    def _send(stream, packet: bytes, kind: str):
        if kind in ('wifi', 'wifi_local'):
            stream.sendall(packet)
        else:
            stream.write(packet)

    @staticmethod
    def _recv(stream, kind: str) -> bytes:
        if kind in ('wifi', 'wifi_local'):
            return stream.recv(4096)
        available = stream.in_waiting
        if not available:
            time.sleep(.002)
            return b''
        return stream.read(min(available, 4096))

    def _session(self, stream, kind: str) -> None:
        self._stream = stream
        self.last_interval_seconds = 0.0
        self.round_trip_seconds = None
        pending = bytearray()
        last_send = 0.0
        sent_at = {}
        merged = {}
        deadline = time.monotonic() + (8.0 if kind in ('usb',) else 4.0)
        last_telemetry = 0.0
        try:
            while self._running:
                now = time.monotonic()
                if now - last_send >= .05:
                    # Até a primeira telemetria, envie somente parada neutra.
                    # Uma telemetria antiga não autoriza manter o último
                    # comando ativo enquanto a porta ainda se recupera.
                    fresh = self.connected and last_telemetry and now-last_telemetry <= self.COMMAND_FRESH_SECONDS
                    packet = (self.get_command() if fresh else
                              control_message({'requested_mode': 'manual', 'stop': True}, {}))
                    self._sequence = (self._sequence + 1) % 2_000_000_000
                    packet['seq'] = self._sequence
                    self._send(stream, encode_message(packet), kind)
                    sent_at[self._sequence] = time.monotonic()
                    if len(sent_at) > 50:
                        sent_at.pop(next(iter(sent_at)))
                    last_send = now
                try:
                    data = self._recv(stream, kind)
                except (socket.timeout, TimeoutError):
                    data = None
                if kind in ('wifi','wifi_local') and data == b'':
                    raise ConnectionError('Conexão TCP encerrada')
                if data is None:
                    data = b'' 
                pending.extend(data)
                if len(pending) > MAX_LINE * 2:
                    raise ValueError('Buffer de comunicação excedido')
                while b'\n' in pending:
                    line, _, remaining = pending.partition(b'\n')
                    pending = bytearray(remaining)
                    try:
                        telemetry = decode_telemetry(line)
                    except (ValueError, UnicodeError):
                        continue  # logs de boot e diagnóstico no serial
                    if self.expected_signature and telemetry.get('setup_signature') != self.expected_signature:
                        raise ValueError('Assinatura do firmware difere da combinação selecionada.')
                    received_at = time.monotonic()
                    seq = telemetry.get('seq')
                    if seq in sent_at:
                        self.round_trip_seconds = received_at-sent_at[seq]
                        for old_seq in list(sent_at):
                            if old_seq <= seq: sent_at.pop(old_seq)
                    merged.update(telemetry)
                    if telemetry.get('fast') is False:
                        self.full_telemetry_count += 1
                        self.last_full_packet_at = received_at
                    self.on_telemetry(dict(merged))
                    if last_telemetry:
                        self.last_interval_seconds = received_at-last_telemetry
                        self.longest_gap_seconds = max(self.longest_gap_seconds,
                                                       received_at-last_telemetry)
                    last_telemetry = received_at
                    self.last_packet_at = last_telemetry
                    self.telemetry_count += 1
                    self.last_error = ''
                    self.connected = True
                    self.active_transport = kind
                now = time.monotonic()
                if (not self.connected and now > deadline) or (self.connected and
                        now - last_telemetry > self.TELEMETRY_TIMEOUT_SECONDS):
                    gap = now-last_telemetry if last_telemetry else 0.0
                    raise TimeoutError(f'Telemetria do ESP32 indisponível por {gap:.1f}s; '
                                       'confira exclusividade da COM, cabo e alimentação')
        finally:
            if self.connected and self._running:
                self.disconnect_count += 1
            if self.connected:
                try:
                    self._send(stream, encode_message(control_message(
                        {'requested_mode': 'manual', 'stop': True}, {})), kind)
                except (OSError, ValueError):
                    pass
            self.connected = False
            self.active_transport = ''
            self._stream = None
            stream.close()

    def _run(self) -> None:
        while self._running:
            candidates = []
            if self.transport == 'usb':
                try:
                    candidates.extend(('usb', name) for name in serial_candidates(self.serial_port))
                except (ImportError, OSError):
                    pass
            if self.transport == 'wifi_local':
                candidates.append(('wifi_local', ''))
            for kind, name in candidates:
                if not self._running:
                    break
                self.attempting = (kind.upper() + (' ' + name if name else ''))
                try:
                    stream = self._usb(name) if kind == 'usb' else self._wifi_local()
                    self._session(stream, kind)
                except (OSError, ValueError, TimeoutError, ImportError, ConnectionError) as exc:
                    self.last_error = f'{kind.upper()}: {type(exc).__name__}: {exc}'
            if self._running:
                self._cancel.wait(self.retry_seconds)

    def stop(self) -> None:
        self._running = False
        self._cancel.set()
        stream=self._stream
        if stream is not None:
            try: stream.close()
            except OSError: pass
        if self._thread:
            self._thread.join(timeout=1)


# ===== VISION =====
import math

import threading

import time

from dataclasses import dataclass

from typing import Any

import cv2

import numpy as np

@dataclass
class VisionOutput:
    live: np.ndarray
    combat: np.ndarray
    pan: float = 90.0
    tilt: float = 90.0
    valid: bool = False
    target_valid: bool = False
    person_detected: bool = False
    status: str = "sem imagem"
    frame_stamp: float = 0.0
    jet_permitted: bool = False

    def state(self) -> dict[str, Any]:
        return {"pan": self.pan, "tilt": self.tilt, "valid": self.valid,
                "target_valid": self.target_valid, "person_detected": self.person_detected,
                "jet_permitted": self.jet_permitted}

def black_frame(text: str, w: int = 640, h: int = 480) -> np.ndarray:
    image = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(image, text[:50], (24, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image

def _model(path):
    if path is None:
        return None
    from ultralytics import YOLO  # opcional somente para execução do detector
    return YOLO(str(path))

def _detect(model, frame: np.ndarray, conf: float, size: int, max_det: int, words: tuple[str, ...]):
    if model is None:
        return []
    names = model.names
    if isinstance(names, list):
        names = dict(enumerate(names))
    classes = [int(k) for k, name in names.items() if any(word in str(name).lower() for word in words)]
    if not classes:
        if len(names) == 1:
            classes = [int(next(iter(names)))]
        else:
            return []
    results = model.predict(frame, conf=conf, imgsz=size, classes=classes,
                            max_det=max_det, verbose=False)
    if not results or results[0].boxes is None:
        return []
    h, w = frame.shape[:2]
    output = []
    for box, score in zip(results[0].boxes.xyxy.cpu().numpy(),
                          results[0].boxes.conf.cpu().numpy()):
        x1, y1, x2, y2 = [int(v) for v in box]
        x1, x2 = sorted((max(0, min(w - 1, x1)), max(0, min(w - 1, x2))))
        y1, y2 = sorted((max(0, min(h - 1, y1)), max(0, min(h - 1, y2))))
        if x2 > x1 and y2 > y1:
            output.append({"box": (x1, y1, x2, y2), "conf": float(score)})
    return output

def fire_color_mask(frame: np.ndarray, fires: list[dict]) -> np.ndarray:
    """Refina as caixas YOLO com vermelho/laranja/amarelo da chama impressa."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 90, 70), (25, 255, 255))
    red |= cv2.inRange(hsv, (170, 90, 70), (179, 255, 255))
    selected = np.zeros((h, w), np.uint8)
    for det in fires:
        x1, y1, x2, y2 = det["box"]
        selected[y1:y2, x1:x2] = red[y1:y2, x1:x2]
        if cv2.countNonZero(selected[y1:y2, x1:x2]) < 30:
            selected[y1:y2, x1:x2] = 255  # fallback para a caixa validada pelo YOLO
    return cv2.morphologyEx(selected, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

def route_from_mask(mask: np.ndarray, cfg: dict[str, Any]) -> list[tuple[int, int]]:
    """Varrimento em zigue-zague dentro dos contornos, como na revisão v15 do notebook."""
    step = max(3, int(cfg.get("route_step_px", 18)))
    spacing = max(3, 2 * int(cfg.get("erase_radius_px", 28)))
    area_limit = int(cfg.get("large_region_area_px", 2500))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    route: list[tuple[int, int]] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < 30:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if cv2.contourArea(contour) < area_limit:
            m = cv2.moments(contour)
            route.append((int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])))
            continue
        region = np.zeros_like(mask)
        cv2.drawContours(region, [contour], -1, 255, -1)
        vertical = h > w
        first, last = (x, x + w - 1) if vertical else (y, y + h - 1)
        lanes = list(range(first, last + 1, spacing))
        if not lanes or lanes[-1] != last:
            lanes.append(last)
        reverse = False
        for lane in lanes:
            low, high = max(first, lane - spacing // 2), min(last, lane + spacing // 2)
            segment = region[y:y+h, low:high+1] if vertical else region[low:high+1, x:x+w]
            rows, cols = np.where(segment > 0)
            if not len(rows):
                continue
            xs = low + cols if vertical else x + cols
            ys = y + rows if vertical else low + rows
            axis = ys if vertical else xs
            bins = list(range(int(axis.min()), int(axis.max()) + 1, step))
            if bins[-1] != int(axis.max()):
                bins.append(int(axis.max()))
            points = []
            for coordinate in bins:
                band = np.abs(axis - coordinate) <= max(1, step // 2)
                if np.any(band):
                    points.append((int(round(np.mean(xs[band]))), int(round(np.mean(ys[band])))))
            route.extend(reversed(points) if reverse else points)
            reverse = not reverse
    compact: list[tuple[int, int]] = []
    for point in route:
        if not compact or math.dist(point, compact[-1]) >= max(2., step * .35):
            compact.append(point)
    route = compact
    return route

from datetime import datetime

EXPORT_DIR = ROOT.parent / 'output' / 'visao'
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
VISION_DEFAULTS = {'fire_conf': 0.3, 'person_conf': 0.7, 'firefighter_conf': 0.7, 'imgsz_infer': 640, 'detect_every_n_frames': 15, 'merge_iou': 0.45, 'max_fire_box_area_px': 8000, 'route_speed_px_frame': 30, 'jet_drop_px': 90, 'erase_radius_px': 80, 'restore_seconds': 20.0, 'human_safety_radius_px': 90, 'person_memory_seconds': 2.0}

def detections(model, image, confidence, image_size, words):
    names = model.names
    names = dict(enumerate(names)) if isinstance(names, list) else names
    ids = [int(key) for key, name in names.items() if
           any(word in str(name).lower() for word in words)]
    result = model.predict(image, conf=float(confidence), imgsz=int(image_size),
                           classes=ids, max_det=100, verbose=False)[0]
    output = []
    if result.boxes is not None:
        for box, score in zip(result.boxes.xyxy.cpu().numpy(),
                              result.boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = map(int, box)
            if x2 > x1 and y2 > y1:
                output.append({'box': (x1, y1, x2, y2), 'conf': float(score),
                               'center': ((x1+x2)/2, (y1+y2)/2),
                               'area': (x2-x1)*(y2-y1)})
    return output

def merge_overlapping_boxes(boxes, iou_threshold):
    """Agrupa caixas da mesma classe por sobreposição, com união transitiva."""
    pending=sorted(boxes,key=lambda item:item['conf'],reverse=True)
    merged=[]
    while pending:
        group=[pending.pop(0)]
        changed=True
        while changed:
            changed=False
            remaining=[]
            for candidate in pending:
                if any(box_iou(candidate['box'],other['box']) >= iou_threshold for other in group):
                    group.append(candidate)
                    changed=True
                else:remaining.append(candidate)
            pending=remaining
        x1=min(item['box'][0] for item in group)
        y1=min(item['box'][1] for item in group)
        x2=max(item['box'][2] for item in group)
        y2=max(item['box'][3] for item in group)
        merged.append({'box':(x1,y1,x2,y2),'conf':max(item['conf'] for item in group),
                       'center':((x1+x2)/2,(y1+y2)/2),'area':(x2-x1)*(y2-y1)})
    return merged

def box_iou(a,b):
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area_a=max(0,a[2]-a[0])*max(0,a[3]-a[1])
    area_b=max(0,b[2]-b[0])*max(0,b[3]-b[1])
    return overlap/max(1,area_a+area_b-overlap)

CAMERA_CALIBRATION_CORNERS = ('tl', 'tr', 'bl', 'br')
CAMERA_CALIBRATION_ANGLES = (0, 90, 180)

def calibration_marker(corner, angle):
    """Posição normalizada dos 12 alvos, respeitando o curso de pan do canhão."""
    x = 0.5 if (angle == 0 and corner in ('tl', 'bl')) or (angle == 180 and corner in ('tr', 'br')) else (0.0 if corner in ('tl', 'bl') else 1.0)
    return x, (0.0 if corner in ('tl', 'tr') else 1.0)

def camera_calibration_complete(calibration):
    angles = calibration.get('angles', {}) if isinstance(calibration, dict) else {}
    try:
        return bool(calibration.get('enabled') and int(calibration.get('schema_version', 0)) >= 5 and all(
            len(angles[str(angle)][corner]) == 2 and
            all(math.isfinite(float(value)) for value in angles[str(angle)][corner]) and
            0 <= float(angles[str(angle)][corner][0]) <= 180 and
            0 <= float(angles[str(angle)][corner][1]) <= 180
            for angle in CAMERA_CALIBRATION_ANGLES for corner in CAMERA_CALIBRATION_CORNERS))
    except (KeyError, ValueError, TypeError):
        return False

def measured_servo_angles(telemetry, calibration):
    """Ângulos inferidos exclusivamente dos três sensores físicos de posição.

    Sem três sensores calibrados, amostra recente e níveis elétricos plausíveis,
    não há uma posição física da mira que se possa representar no vídeo.
    """
    feedback = calibration.get('servo_feedback', {}) if isinstance(calibration, dict) else {}
    if not feedback.get('enabled') or not isinstance(telemetry, dict):
        return None
    angles = {}
    for axis, field in (('pan', 'servo_pan_feedback_raw'),
                        ('tilt', 'servo_tilt_feedback_raw'),
                        ('camera', 'camera_pan_feedback_raw')):
        try:
            settings = feedback[axis]
            raw_low, raw_high = (float(settings[key]) for key in ('raw_low', 'raw_high'))
            deg_low, deg_high = (float(settings[key]) for key in ('deg_low', 'deg_high'))
            raw = float(telemetry[field])
            span = raw_high - raw_low
            if not all(math.isfinite(v) for v in
                       (raw_low, raw_high, deg_low, deg_high, raw)):
                return None
            if (abs(span) < 300 or not 0 <= deg_low < deg_high <= 180
                    or min(raw_low, raw_high) < 80 or max(raw_low, raw_high) > 4015
                    or raw < 50 or raw > 4045
                    or not min(raw_low, raw_high)-abs(span)*.08 <= raw <=
                           max(raw_low, raw_high)+abs(span)*.08):
                return None
            angles[axis] = clamp(deg_low+(raw-raw_low)*(deg_high-deg_low)/span, 0, 180)
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            return None
    return angles

def pixel_to_servos(point, shape, calibration, params, camera_pan_deg=90.):
    x, y = point
    height, width = shape[:2]
    if camera_calibration_complete(calibration):
        image_u = clamp(x / max(1, width-1), 0, 1)
        v = clamp(y / max(1, height-1), 0, 1)
        def at(angle):
            # Em 0° a metade esquerda e em 180° a metade direita não
            # possuem correspondência física alcançável no canhão.
            left = calibration_marker('tl', angle)[0]
            right = calibration_marker('tr', angle)[0]
            u = clamp((image_u-left)/(right-left), 0, 1)
            corners = calibration['angles'][str(angle)]
            return [sum(float(corners[corner][axis]) * weight for corner, weight in (
                ('tl',(1-u)*(1-v)), ('tr',u*(1-v)),
                ('bl',(1-u)*v), ('br',u*v))) for axis in (0, 1)]
        angle = clamp(camera_pan_deg, 0, 180)
        low, high = (0, 90) if angle <= 90 else (90, 180)
        a, b = at(low), at(high)
        fraction = (angle-low)/(high-low)
        pan, tilt = [a[i]*(1-fraction)+b[i]*fraction for i in (0, 1)]
    else:
        # Mapa provisório: sem os 12 pontos medidos, o centro horizontal
        # desloca junto com o único eixo da plataforma da câmera.
        pan = np.interp(x, [0, width-1], [params.get('servo_pan_min', 25),
                                          params.get('servo_pan_max', 155)]) + (camera_pan_deg-90.)
        tilt = np.interp(y, [0, height-1], [params.get('servo_tilt_max', 145),
                                            params.get('servo_tilt_min', 35)])
    return float(np.clip(pan, 0, 180)), float(np.clip(tilt, 0, 180))

def servos_to_pixel(pan, tilt, shape, calibration, params, camera_pan_deg=90.):
    """Projeta ângulos dos eixos no vídeo, invertendo o mapa de 12 pontos.

    A origem dos ângulos é responsabilidade de quem chama esta função: a mira
    azul usa exclusivamente feedback físico calibrado. Pontos fora do campo
    da câmera retornam None.
    """
    if not all(math.isfinite(float(v)) for v in (pan, tilt, camera_pan_deg)):
        return None
    h, w = shape[:2]
    if h < 2 or w < 2:
        return None
    if not camera_calibration_complete(calibration):
        pan_min, pan_max = (float(params.get(key, default)) for key, default in
                            (('servo_pan_min', 25), ('servo_pan_max', 155)))
        tilt_min, tilt_max = (float(params.get(key, default)) for key, default in
                              (('servo_tilt_min', 35), ('servo_tilt_max', 145)))
        if abs(pan_max-pan_min) < 1e-6 or abs(tilt_max-tilt_min) < 1e-6:
            return None
        u = (float(pan)-(float(camera_pan_deg)-90.)-pan_min)/(pan_max-pan_min)
        v = (tilt_max-float(tilt))/(tilt_max-tilt_min)
    else:
        # Mesmo interpolador bilinear de pixel_to_servos; inversão numérica
        # permite 0°, 90°, 180° e posições intermediárias da plataforma.
        def at(u, v):
            return np.array(pixel_to_servos((u*(w-1),v*(h-1)),shape,
                                            calibration,params,camera_pan_deg))
        target=np.array((float(pan),float(tilt)))
        u=v=.5
        for _ in range(12):
            estimate=at(u,v)
            if float(np.linalg.norm(target-estimate)) < .01:
                break
            delta=.001
            jac=np.column_stack(((at(u+delta,v)-estimate)/delta,
                                 (at(u,v+delta)-estimate)/delta))
            if abs(float(np.linalg.det(jac))) < 1e-7:
                return None
            step=np.linalg.solve(jac,target-estimate)
            u+=float(step[0]);v+=float(step[1])
            if max(abs(float(step[0])),abs(float(step[1]))) < 1e-5:
                break
    if not (-.02 <= u <= 1.02 and -.02 <= v <= 1.02):
        return None
    return (int(round(np.clip(u,0,1)*(w-1))),
            int(round(np.clip(v,0,1)*(h-1))))

def camera_view_limits(shape, calibration, params, camera_pan_deg=90., margin_px=8.):
    """Limites de pan e tilt que mantêm a mira dentro do quadro atual.

    O mapa físico usa os 12 pontos; sem eles, usa a aproximação explícita
    de 25..155 graus de pan e 35..145 graus de tilt da visão padrão.
    """
    h, w = shape[:2]
    if h < 3 or w < 3:
        return (0., 180.), (0., 180.)
    margin = clamp(margin_px, 1, min(w,h)/4)
    points = [pixel_to_servos((x,y),shape,calibration,params,camera_pan_deg)
              for x in (margin,w-1-margin) for y in (margin,h-1-margin)]
    limits = []
    for axis in (0,1):
        values = [point[axis] for point in points]
        limits.append((max(0., min(values)),min(180.,max(values))))
    return tuple(limits)

class VisionSession:
    def __init__(self, fire_model, person_model, params, calibration, mode, source,
                 firefighter_model=None):
        self.fire_model, self.person_model = fire_model, person_model
        self.firefighter_model = firefighter_model
        self.params, self.calibration, self.mode, self.source = params, calibration, mode, source
        self.journal_path = EXPORT_DIR / f'trajetoria_{datetime.now():%Y%m%d_%H%M%S}.jsonl'
        self.journal = self.journal_path.open('w', encoding='utf-8')
        self._ack_servo = None
        self.reset()

    def observe_servo_setpoint(self, pan, tilt, camera):
        """Eco de setpoints recebidos do ESP; não é posição física medida."""
        if all(isinstance(value, (int,float)) for value in (pan,tilt,camera)):
            self._ack_servo = (float(pan),float(tilt),float(camera),time.monotonic())

    def close(self):
        self.journal.close()

    def reset(self):
        self.fires, self.people, self.firefighters = [], [], []
        self.regions, self.route = [], []
        self.impact, self.last_step = None, None
        self.last_person, self.last_detection = -1e10, -1e10
        self.trail, self.visited_cells = [], set()
        self.target = None
        self._held_cell = None
        self._held_box = None
        self._held_since = 0.
        self.previous_camera_pan = None

    def _painted_frame(self, frame, now):
        canvas=frame.copy()
        if self.mode != 'simulation':return canvas
        lifetime=max(.1,float(self.params['restore_seconds']))
        radius=int(self.params['erase_radius_px'])
        self.trail=[point for point in self.trail if now-point[0]<lifetime]
        for instant,px,py in self.trail:
            alpha=max(0.,min(1.,1.-(now-instant)/lifetime))
            cx,cy=int(round(px)),int(round(py))
            x0,x1=max(0,cx-radius),min(canvas.shape[1],cx+radius+1)
            y0,y1=max(0,cy-radius),min(canvas.shape[0],cy+radius+1)
            if x0>=x1 or y0>=y1:continue
            roi=canvas[y0:y1,x0:x1]
            mask=np.zeros(roi.shape[:2],dtype=np.uint8)
            cv2.circle(mask,(cx-x0,cy-y0),radius,255,-1)
            roi[mask>0]=(roi[mask>0].astype(np.float32)*(1.-alpha)).astype(np.uint8)
        return canvas

    def _fire_mask(self, frame, raw, cell):
        """Refina as caixas YOLO com pixels quentes, mantendo fallback para chama atípica."""
        height,width=frame.shape[:2]
        mask=np.zeros((height,width),dtype=np.uint8)
        for fire in raw:
            x1,y1,x2,y2=fire['box']
            x1,y1=max(0,x1),max(0,y1)
            x2,y2=min(width,x2),min(height,y2)
            if x2<=x1 or y2<=y1:continue
            roi=frame[y1:y2,x1:x2]
            hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
            hue,sat,val=cv2.split(hsv)
            warm=(((hue<=42)|(hue>=170)) & (sat>=65) & (val>=115)).astype(np.uint8)*255
            # O branco muito luminoso só é aceito perto de pixels quentes.
            bright=((val>=205)&(sat<=95)).astype(np.uint8)*255
            nearby=cv2.dilate(warm,np.ones((max(3,cell//4),)*2,np.uint8))
            support=cv2.bitwise_or(warm,cv2.bitwise_and(bright,nearby))
            coverage=cv2.countNonZero(support)
            if coverage>=max(12,int(.008*roi.shape[0]*roi.shape[1])):
                kernel=np.ones((max(3,cell//6),)*2,np.uint8)
                support=cv2.morphologyEx(support,cv2.MORPH_CLOSE,kernel)
                support=cv2.dilate(support,np.ones((max(3,cell//5),)*2,np.uint8))
                mask[y1:y2,x1:x2]=cv2.bitwise_or(mask[y1:y2,x1:x2],support)
            else:
                # Mesmo no fallback, pixels ainda escuros pelo jato ficam de fora.
                visible=(np.max(roi,axis=2)>35).astype(np.uint8)*255
                mask[y1:y2,x1:x2]=cv2.bitwise_or(mask[y1:y2,x1:x2],visible)
        return mask

    def _small_boxes_and_regions(self, frame, raw):
        height,width=frame.shape[:2]
        cell=max(4,int(math.floor(math.sqrt(float(self.params['max_fire_box_area_px'])))))
        mask=self._fire_mask(frame,raw,cell)
        boxes=[]
        coverage=np.zeros((height,width),dtype=np.uint8)
        # Cada caixa fica contida em uma célula fixa: nunca há sobreposição.
        for y0 in range(0,height,cell):
            for x0 in range(0,width,cell):
                cropped=mask[y0:min(height,y0+cell),x0:min(width,x0+cell)]
                if not cv2.countNonZero(cropped):continue
                ys,xs=np.nonzero(cropped)
                x1,x2=x0+int(xs.min()),x0+int(xs.max())+1
                y1,y2=y0+int(ys.min()),y0+int(ys.max())+1
                if (x2-x1)*(y2-y1)>self.params['max_fire_box_area_px']:
                    # O ajuste abaixo também cobre limites de área não quadrados.
                    x2=min(x2,x1+cell)
                    y2=min(y2,y1+max(1,int(self.params['max_fire_box_area_px']//(x2-x1))))
                overlaps=[f['conf'] for f in raw if box_iou((x1,y1,x2,y2),f['box'])>0]
                conf=max(overlaps,default=max((f['conf'] for f in raw),default=0.))
                index=len(boxes)
                boxes.append({'box':(x1,y1,x2,y2),'conf':conf,
                              'center':((x1+x2)/2.,(y1+y2)/2.),
                              'area':(x2-x1)*(y2-y1),
                              'cell':(x0//cell,y0//cell),'region':None})
                coverage[y1:y2,x1:x2]=255
        if not boxes:return [],[]
        count,labels,stats,_=cv2.connectedComponentsWithStats(coverage,connectivity=8)
        regions=[]
        for component in range(1,count):
            if stats[component,cv2.CC_STAT_AREA]<2:continue
            ox,oy,ow,oh=map(int,stats[component,:4])
            part=np.where(labels[oy:oy+oh,ox:ox+ow]==component,255,0).astype(np.uint8)
            contours,_=cv2.findContours(part,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if not contours:continue
            contour=max(contours,key=cv2.contourArea).copy()
            contour[:,0,0]+=ox
            contour[:,0,1]+=oy
            reduced=cv2.approxPolyDP(contour,max(1.,cv2.arcLength(contour,True)*.002),True)
            regions.append({'contour':contour,'export':reduced.reshape(-1,2).tolist(),
                            'component':component,'box_indices':[]})
        component_to_region={region['component']:i for i,region in enumerate(regions)}
        for i,box in enumerate(boxes):
            cx=min(width-1,int(box['center'][0]))
            cy=min(height-1,int(box['center'][1]))
            component=int(labels[cy,cx])
            region_index=component_to_region.get(component)
            if region_index is not None:
                box['region']=region_index
                regions[region_index]['box_indices'].append(i)
        return boxes,regions

    def _detect(self, painted, now, force=False):
        p=self.params
        fps=max(1.,float(p.get('input_fps',25)))
        if not force and now-self.last_detection<max(.02,p['detect_every_n_frames']/fps):
            return
        self.people=merge_overlapping_boxes(
            detections(self.person_model,painted,p['person_conf'],p['imgsz_infer'],
                       ('person','pessoa','human')),p['merge_iou'])
        self.firefighters=(merge_overlapping_boxes(
            detections(self.firefighter_model,painted,p['firefighter_conf'],p['imgsz_infer'],
                       ('firefighter','fireman','bombeiro','helmet','capacete','turnout',
                        'protective','ppe','epi')),p['merge_iou'])
            if self.firefighter_model is not None else [])
        raw=detections(self.fire_model,painted,p['fire_conf'],p['imgsz_infer'],
                       ('fire','flame','fogo','chama'))
        self.fires,self.regions=self._small_boxes_and_regions(painted,raw)
        self.last_detection=time.monotonic()
        if self.people or self.firefighters:self.last_person=self.last_detection
        if not self.fires:self.visited_cells.clear()

    def process(self, frame, engaged=True, camera_pan_deg=90.):
        now=time.monotonic()
        p=self.params
        height,width=frame.shape[:2]
        painted=self._painted_frame(frame,now)
        if self.previous_camera_pan is not None and abs(camera_pan_deg-self.previous_camera_pan) > 1.0:
            # As caixas do enquadramento anterior deixam de ser válidas após o giro.
            self.last_detection = -1e10
            self.visited_cells.clear()
            self.impact = None
            self.trail = []
            self._held_cell = None
            self._held_box = None
        self.previous_camera_pan = camera_pan_deg
        # Em simulação a inferência recebe o vídeo já pintado, sem desenhos de interface.
        self._detect(painted,now)
        blocked=now-self.last_person<=p['person_memory_seconds']
        if self.impact is None:self.impact=(width/2.,height/2.)
        self.route=[tuple(box['center']) for box in self.fires]
        self.target=None
        if engaged and not blocked and self.fires:
            candidates=[box for box in self.fires if box['cell'] not in self.visited_cells]
            if not candidates:
                self.visited_cells.clear()
                candidates=self.fires
            self.target=min(candidates,key=lambda box:math.dist(self.impact,box['center']))
            if self.mode == 'real':
                if self._held_cell is not None:
                    previous=next((box for box in self.fires if box['cell']==self._held_cell),None)
                    if previous is not None and self._held_box is not None:
                        self.target=self._held_box
                    else:
                        self._held_cell=None  # chama desapareceu: não mantém jato em alvo antigo
                if self._held_cell is None:
                    self._held_cell=self.target['cell']
                    self._held_box=dict(self.target)
                    self._held_since=now
        if blocked or not self.fires:
            self.impact=None
            self.last_step=None
            self._held_cell=None
            self._held_box=None
            if blocked:self.trail=[]
        fps=max(1.,float(p.get('input_fps',25)))
        dt=min(.25,max(1./fps,now-(self.last_step if self.last_step is not None else now)))
        self.last_step=now if self.target is not None else None
        arrived=False
        if self.target is not None:
            waypoint=self.target['center']
            distance=math.dist(self.impact,waypoint)
            step=float(p['route_speed_px_frame'])*fps*dt
            if self.mode == 'real':
                # A visão envia uma posição fixa, sem uma trajetória virtual de pixels.
                self.impact=tuple(map(float,waypoint))
            elif distance<=step:
                self.impact=tuple(map(float,waypoint))
                arrived=True
                self.visited_cells.add(self.target['cell'])
                # A próxima imagem exige inferência nova antes de escolher outro centro.
                self.last_detection=-1e10
            elif distance:
                self.impact=(self.impact[0]+(waypoint[0]-self.impact[0])*step/distance,
                             self.impact[1]+(waypoint[1]-self.impact[1])*step/distance)
        active_region=None
        active_region_index=None
        if self.impact is not None and not blocked:
            for index,region in enumerate(self.regions):
                if cv2.pointPolygonTest(region['contour'],self.impact,False)>=0:
                    active_region=region
                    active_region_index=index
                    break
        enabled=active_region is not None and engaged
        if enabled and self.mode=='simulation':
            self.trail.append((now,*self.impact))
            self.trail=self.trail[-max(100,int(p['restore_seconds']*fps*2)):]
            painted=self._painted_frame(frame,now)
        aim=(self.impact[0],max(0.,self.impact[1]-p['jet_drop_px'])) if self.target else None
        pan,tilt=pixel_to_servos(aim,frame.shape,self.calibration,p,camera_pan_deg) if aim else (None,None)
        if self.mode=='real':
            ack=self._ack_servo
            arrived=bool(self.target and ack and pan is not None and tilt is not None and
                         ack[3] >= self._held_since and now-ack[3] < .3 and
                         abs(ack[0]-pan) <= 1.5 and abs(ack[1]-tilt) <= 1.5 and
                         abs(ack[2]-camera_pan_deg) <= 2 and
                         now-self._held_since >= .6)
            enabled=bool(enabled and arrived)
            if arrived and now-self._held_since >= .9:
                self.visited_cells.add(self._held_cell)
                self._held_cell=None
                self._held_box=None
                self.last_detection=-1e10
        record={'t_unix':time.time(),'mode':self.mode,'camera':str(self.source),
                'frame_width':width,'frame_height':height,'strategy':'centroides_em_regioes',
                'route_index':next((i for i,box in enumerate(self.fires)
                                    if self.target and box['cell']==self.target['cell']),None),
                'route_pixels':[list(point) for point in self.route],
                'small_boxes':[list(box['box']) for box in self.fires],
                'regions':[region['export'] for region in self.regions],
                'impact_px':list(self.impact) if self.impact else None,
                'aim_px':list(aim) if aim else None,'pan_deg':pan,'tilt_deg':tilt,
                'camera_pan_deg':camera_pan_deg,
                'target_valid':bool(self.target),'centroid_reached':bool(arrived),
                'person_detected':bool(self.people),'firefighter_detected':bool(self.firefighters),
                'blocked':bool(blocked),'jet_requested':bool(self.target and not blocked),
                'jet_permitted':bool(enabled),'region_index':active_region_index}
        if self.mode=='real' or enabled or blocked:
            self.journal.write(json.dumps(record,ensure_ascii=False)+'\n')
            self.journal.flush()
        canvas=painted
        label_scale=max(.45,min(.9,width/1500.))
        label_stroke=max(1,int(round(label_scale*2)))
        for box in self.fires:
            bx1,by1,bx2,by2=box['box']
            cv2.rectangle(canvas,(bx1,by1),(bx2,by2),(0,150,255),1)
            cv2.circle(canvas,tuple(map(int,box['center'])),3,(0,200,255),-1)
        for region in self.regions:
            cv2.polylines(canvas,[region['contour']],True,(220,40,220),2,cv2.LINE_AA)
            indices=region['box_indices']
            if indices:
                mean_conf=sum(self.fires[index]['conf'] for index in indices)/len(indices)
                label=f'FOGO {mean_conf:.0%}'
                points=region['contour'].reshape(-1,2)
                x=int(points[:,0].min())
                y=max(16,int(points[:,1].min())-4)
                small_scale=max(.35,min(.6,width/2200.))
                cv2.putText(canvas,label,(x,y),cv2.FONT_HERSHEY_SIMPLEX,
                            small_scale,(0,0,0),3)
                cv2.putText(canvas,label,(x,y),cv2.FONT_HERSHEY_SIMPLEX,
                            small_scale,(220,40,220),1)
        for kind,items,color in (('PESSOA',self.people,(0,0,255)),
                                 ('BOMBEIRO/EPI',self.firefighters,(255,200,0))):
            for found in items:
                x1,y1,x2,y2=found['box']
                margin=int(p['human_safety_radius_px'])
                cv2.rectangle(canvas,(max(0,x1-margin),max(0,y1-margin)),
                              (min(width-1,x2+margin),min(height-1,y2+margin)),color,1)
                cv2.rectangle(canvas,(x1,y1),(x2,y2),color,2)
                label=f'{kind} {found["conf"]:.0%}'
                y=max(18,y1-3)
                cv2.putText(canvas,label,(x1,y),cv2.FONT_HERSHEY_SIMPLEX,
                            label_scale,(0,0,0),label_stroke+2)
                cv2.putText(canvas,label,(x1,y),cv2.FONT_HERSHEY_SIMPLEX,
                            label_scale,color,label_stroke)
        if blocked:
            cv2.rectangle(canvas,(0,0),(width,max(55,int(width*.085))),(0,0,170),-1)
            cv2.putText(canvas,'PESSOA/BOMBEIRO: JATO BLOQUEADO',
                        (10,max(40,int(width*.06))),cv2.FONT_HERSHEY_SIMPLEX,
                        max(1.,width/640.),(255,255,255),3)
        # Mira e parábola são ilustrações virtuais exclusivas da simulação.
        if self.mode == 'simulation' and self.target is not None and not blocked and self.impact is not None:
            hit=(int(round(self.impact[0])),int(round(self.impact[1])))
            aim_pt=(int(round(aim[0])),int(round(aim[1])))
            cv2.circle(canvas,aim_pt,9,(0,200,0),-1)
            cv2.circle(canvas,hit,7,(0,255,255),2)
            if enabled:
                drop=float(p['jet_drop_px'])
                start=(width//2,height-1)
                path=[]
                for t in np.linspace(0.,1.,40):
                    x=start[0]+(hit[0]-start[0])*t
                    y=start[1]+(hit[1]-start[1]-drop)*t+drop*t*t
                    path.append((int(round(x)),int(round(y))))
                cv2.polylines(canvas,[np.array(path,dtype=np.int32)],
                              False,(255,110,0),max(5,width//120),cv2.LINE_AA)
                cv2.circle(canvas,aim_pt,9,(0,200,0),-1)
                cv2.circle(canvas,hit,9,(255,255,255),2)
        return canvas,record


class VisionEngine:
    """Mesma inferência da seção 4, com vídeo único e intertravamento de pessoas."""
    def __init__(self, settings: VisionSettings, options: dict[str, Any]):
        self.configure(settings, options)

    def configure(self, settings: VisionSettings, options=None):
        if hasattr(self, 'session') and self.session is not None:
            self.session.close()
        self.settings=settings
        self.options=options if options is not None else self.options
        self.session=None
        self.last_record={}
        self.model_error=''
        self.fire_model=self.person_model=self.firefighter_model=None
        for kind,path in [('fire',settings.fire_model),('person',settings.person_model),
                          ('firefighter',settings.firefighter_model)]:
            try:setattr(self,kind+'_model',_model(path))
            except Exception as exc:self.model_error+=' '+kind+': '+str(exc)
        if self.fire_model is None or self.person_model is None:
            self.model_error+=' Selecione modelos válidos de chama e pessoa na seção 4.'
        mode=self.options.get('combat_mode','simulation')
        params={**VISION_DEFAULTS, **settings.params}
        params['input_fps']=int(self.options.get('input_fps',params.get('input_fps',25)))
        if mode=='real' and 'route_speed_px_frame' not in settings.params:
            params['route_speed_px_frame']=5
        if self.fire_model is not None and self.person_model is not None:
            self.session=VisionSession(self.fire_model,self.person_model,params,
                settings.calibration,mode,self.options.get('camera_source',''),
                firefighter_model=self.firefighter_model)

    def process(self, frame: np.ndarray, stamp: float, mode: str,
                virtual_jet: bool, manual_xy: tuple[float,float],
                camera_pan_deg: float = 90.) -> VisionOutput:
        if self.session is None:
            return VisionOutput(frame.copy(), frame.copy(), status=self.model_error, frame_stamp=stamp)
        canvas,record=self.session.process(frame,mode=='auto',camera_pan_deg)
        self.last_record=record
        if mode!='auto':
            record['jet_permitted']=False
        # A detecção de pessoa/bombeiro sempre bloqueia os dois modos.
        blocked=bool(record['blocked'])
        return VisionOutput(canvas,canvas,pan=record.get('pan_deg') or 90.,
            tilt=record.get('tilt_deg') or 90.,valid=time.monotonic()-stamp<1,
            target_valid=bool(record['target_valid'] and mode=='auto' and not blocked),
            person_detected=blocked,jet_permitted=bool(record['jet_permitted'] and mode=='auto' and not blocked),
            status='PESSOA/BOMBEIRO: JATO BLOQUEADO' if blocked else 'visão válida',frame_stamp=stamp)

    def close(self):
        if self.session is not None:
            self.session.close();self.session=None

class VisionWorker:
    """Executa inferência fora da thread de interface e preserva apenas resultado atual."""
    def __init__(self, camera, settings: VisionSettings, options: dict[str, Any], inputs):
        self.camera, self.inputs = camera, inputs
        self.engine = VisionEngine(settings, options)
        self._lock = threading.Lock()
        image = black_frame("Aguardando camera")
        self.result = VisionOutput(image, image.copy())
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vision")
        self._thread.start()

    def _loop(self):
        previous_stamp = 0.0
        while self._running:
            frame, stamp = self.camera.latest()
            if frame is None:
                blank = black_frame("CAMERA DESCONECTADA")
                with self._lock:
                    self.result = VisionOutput(blank, blank.copy(), status="camera desconectada")
                time.sleep(.08)
                continue
            if stamp == previous_stamp:
                time.sleep(.01)
                continue
            previous_stamp = stamp
            state = self.inputs.snapshot()
            try:
                output = self.engine.process(frame, stamp, state["mode"], state["jet_virtual_ack"],
                                             (state["cannon_x"], state["cannon_y"]),
                                             state.get('camera_pan_deg', 90.))
            except Exception as exc:
                blank = black_frame("ERRO NA VISAO")
                output = VisionOutput(blank, blank.copy(), status=f"Erro na visao: {exc}")
            with self._lock:
                self.result = output

    def snapshot(self) -> VisionOutput:
        with self._lock:
            output = self.result
        if output.frame_stamp and time.monotonic() - output.frame_stamp > 1.0:
            return VisionOutput(output.live, output.combat, status="quadro desatualizado")
        return output

    def reload(self, settings: VisionSettings, options: dict[str, Any] | None = None):
        # Chamado somente depois de parar a thread; evita trocar modelos durante predict().
        self.stop()
        if self._thread and self._thread.is_alive():
            raise RuntimeError("O detector ainda está processando um quadro; tente F5 novamente")
        self.engine.configure(settings, options)
        self.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if not self._thread or not self._thread.is_alive():
            self.engine.close()


# ===== APP =====
import threading

import json

import math

import time

from collections import deque

import tkinter as tk

from tkinter import ttk

import cv2

from PIL import Image, ImageTk

class OperatorApp:
    def __init__(self, config: AppConfig, joystick_debug: bool = False):
        self.config = config
        self.inputs = OperatorInputs(config.data["xbox_axes"], config.data["xbox_buttons"],
                                     joystick_debug, int(config.data.get("xbox_index", 0)),
                                     float(config.data.get("control", {}).get("speed_limit_rpm", 80)),
                                     float(config.data["geometry"].get("output_max_rpm", 0)),
                                     config.data.get("control",{}).get("input_bindings",{}))
        self.inputs.speed_limit_percent = float(config.data.get('control',{}).get('speed_limit_percent',100))
        self.inputs.steering_sensitivity_percent = float(config.data.get('control',{}).get('steering_sensitivity_percent',50))
        cam = config.data["camera"]
        self.camera = CameraSource(config.data["vision"].get("camera_source",config.camera_source()), cam["reconnect_seconds"],
                                   cam.get("mdns_name", ""), cam.get("stream_path", "/live"),
                                   cam.get("fallback_source", ""))
        self.vision = VisionWorker(self.camera, config.vision, config.data["vision"], self.inputs)
        self.telemetry_lock = threading.Lock()
        self.telemetry: dict = {}
        self.telemetry_stamp = 0.
        esp = config.data["esp"]
        self.connection = ESPConnection(str(esp["host"]), int(esp["port"]), self._command,
                                        self._on_telemetry, float(esp["reconnect_seconds"]),
                                        str(esp.get("transport", "wifi_local")),
                                        str(esp.get("serial_port", "auto")),
                                        int(esp.get("baudrate", 460800)),
                                        str(config.data.get('_official',{}).get('firmware_signature','')),
                                        preserve_wifi=isinstance(self.camera.source, str) and
                                        self.camera.source.lower().startswith(('rtsp://', 'rtsps://',
                                                                               'http://', 'https://')))

        self.root = tk.Tk()
        self.root.title("BLAZE — Operador do protótipo")
        self.root.geometry("1450x1030")
        self.root.configure(bg="#111b27")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<KeyPress>", lambda event: self.inputs.key(event.keysym, True))
        self.root.bind("<KeyRelease>", lambda event: self.inputs.key(event.keysym, False))
        self.root.bind("<F5>", self.reload_parameters)
        self._build()
        self._photos: list[ImageTk.PhotoImage | None] = [None]
        self._history = deque(maxlen=200)
        self._closing = False
        self._camera_switch_seen = 0

    def _build(self):
        bg = "#111b27"
        header = tk.Frame(self.root, bg=bg)
        header.pack(fill="x", padx=15, pady=10)
        tk.Label(header, text="BLAZE  ·  PROTÓTIPO", fg="#e5f1ff", bg=bg,
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        official = self.config.data.get("_official", {}).get("name", "sem nome")
        limit = self.config.data.get("control", {}).get("speed_limit_rpm", 80)
        tk.Label(header, text=f"Setup oficial: {official}  ·  teto {limit} RPM",
                 fg="#d3e9f6", bg=bg).pack(side="left", padx=20)
        tk.Label(header, text="F5: recarregar parâmetros do notebook", fg="#a3b8ca", bg=bg,
                 font=("Segoe UI", 10)).pack(side="right")

        videos = tk.Frame(self.root, bg=bg)
        videos.pack(fill="x", padx=12)
        self.images = []
        box = tk.Frame(videos, bg="#203044", bd=2, relief="ridge")
        box.pack(side="left", padx=5, fill="both")
        tk.Label(box, text="Visão ao vivo · alvo e segurança", bg="#203044", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(pady=4)
        label = tk.Label(box, bg="#000000")
        label.pack(padx=6, pady=4)
        self.images.append(label)
        self.readings = tk.StringVar(master=self.root, value="Sem telemetria")
        telemetry_box = tk.Frame(videos, bg="#203044", bd=2, relief="ridge")
        telemetry_box.pack(side="left", padx=5, fill="both", expand=True)
        tk.Label(telemetry_box, text="Estados e parâmetros", bg="#203044", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(pady=4)
        tk.Label(telemetry_box, textvariable=self.readings, bg="#203044", fg="#d3e9f6",
                 anchor="nw", font=("Consolas", 10), justify="left", wraplength=420).pack(fill="both", padx=12, pady=8)

        tk.Label(self.root, text="Xbox: segure Start 2 s para conectar/rearmar; View libera água; "
                 "LT acelera, LB freia, RT ajusta pressão; segure D-pad ← 1 s para emergência.",
                 bg=bg, fg="#d3e9f6", font=("Segoe UI", 10)).pack(anchor="w", padx=17, pady=8)

        geometry = tk.Frame(self.root, bg=bg)
        geometry.pack(fill="x", padx=17, pady=3)
        self.geometry_values = {}
        for key, label in (("track_width_m", "Distância entre esteiras (m)"),
                           ("sprocket_radius_m", "Raio efetivo da roda (m)"),
                           ("output_max_rpm", "RPM máx. calibrada na saída")):
            tk.Label(geometry, text=label, bg=bg, fg="#d3e9f6").pack(side="left", padx=(7, 2))
            variable = tk.StringVar(master=self.root, value=str(self.config.data["geometry"].get(key, 0)))
            self.geometry_values[key] = variable
            tk.Entry(geometry, textvariable=variable, width=9, state="readonly").pack(side="left")
        tk.Label(geometry, text="Edite no notebook e ative novamente o setup oficial.",
                 bg=bg, fg="#d3e9f6").pack(side="left", padx=12)

        self.status = tk.StringVar(master=self.root, value="Aguardando câmera e ESP32")
        tk.Label(self.root, textvariable=self.status, bg=bg, fg="#f5d791", anchor="w",
                 font=("Segoe UI", 11), justify="left").pack(fill="x", padx=17, pady=6)
        tk.Label(self.root, text="Histórico: comandos esteira E/D (−1 a +1); RPM só após calibração. Ângulos dos servos são comandados.",
                 bg=bg, fg="#a3b8ca").pack(anchor="w", padx=17)
        self.chart = tk.Canvas(self.root, height=145, bg="#182737", highlightthickness=0)
        self.chart.pack(fill="x", padx=17, pady=3)
        self.speed_chart = tk.Canvas(self.root, height=112, bg="#182737", highlightthickness=0)
        self.speed_chart.pack(fill="x", padx=17, pady=3)
        tk.Label(self.root, text="Xbox: esquerdo=esteiras · direito=canhão · funções conforme setup oficial  |  Teclado: WASD e setas",
                 bg=bg, fg="#829cb3", font=("Segoe UI", 9)).pack(side="bottom", pady=8)

    def _command(self) -> dict:
        state = self.inputs.snapshot()
        limits=self.config.vision.calibration.get('angle_limits', {})
        for axis in ('camera','pan','tilt'):
            pair=limits.get(axis,[0,180])
            if (isinstance(pair,(list,tuple)) and len(pair)==2 and
                    all(isinstance(value,(int,float)) for value in pair) and
                    0 <= pair[0] < pair[1] <= 180):
                state[axis+'_min'],state[axis+'_max']=pair
        return control_message(state, self.vision.snapshot().state())

    def _on_telemetry(self, message: dict):
        with self.telemetry_lock:
            self.telemetry = message
            self.telemetry_stamp = time.monotonic()
        self.inputs.acknowledge_mode(str(message.get("mode", "")), bool(message.get("jet_virtual", False)))
        session=getattr(self.vision.engine,'session',None)
        if session is not None and not message.get('calibrating'):
            session.observe_servo_setpoint(message.get('servo_pan_commanded'),
                                           message.get('servo_tilt_commanded'),
                                           message.get('camera_pan_commanded'))
        if isinstance(message.get('servo_pan_commanded'),(int,float)):
            with self.inputs._lock:
                self.inputs.servo_pan_commanded=float(message['servo_pan_commanded'])
                if isinstance(message.get('servo_tilt_commanded'),(int,float)):
                    self.inputs.servo_tilt_commanded=float(message['servo_tilt_commanded'])

    def reload_parameters(self, _event=None):
        try:
            self.config.reload()
            self.vision.reload(self.config.vision, self.config.data['vision'])
            new_source=self.config.data['vision'].get('camera_source',self.config.camera_source())
            if self.camera.source != new_source:self.camera.switch_source(new_source)
            self.inputs.axes = self.config.data["xbox_axes"]
            self.inputs.buttons = self.config.data["xbox_buttons"]
            self.inputs.bindings.update(self.config.data.get("control",{}).get("input_bindings",{}))
            self.inputs.speed_limit_rpm = float(self.config.data.get("control", {}).get("speed_limit_rpm", 80))
            self.inputs.steering_sensitivity_percent = float(self.config.data.get('control',{}).get('steering_sensitivity_percent',50))
            self.inputs.calibrated_max_rpm = float(self.config.data["geometry"].get("output_max_rpm", 0))
            self.status.set(f"Parâmetros carregados: {self.config.vision.source_name}")
        except (OSError, ValueError, RuntimeError) as exc:
            self.status.set(f"Não foi possível recarregar: {exc}")

    def save_geometry(self):
        try:
            values = {key: float(var.get().replace(',', '.'))
                      for key, var in self.geometry_values.items()}
            if any(not math.isfinite(value) or not 0 < value < (5000 if key == 'output_max_rpm' else 10)
                   for key, value in values.items()):
                raise ValueError("informe valores positivos, em metros e RPM na saída")
            self.status.set("Ajuste a geometria no notebook e reative a combinação oficial na seção 7.")
        except (OSError, ValueError) as exc:
            self.status.set(f"Geometria inválida: {exc}")

    def plot_commands(self):
        canvas = self.chart
        canvas.delete("all")
        width = max(500, canvas.winfo_width())
        center, scale = 73, 54
        canvas.create_line(30, center, width - 16, center, fill="#66758a")
        canvas.create_text(15, 17, text="+1", fill="white")
        canvas.create_text(15, 125, text="−1", fill="white")
        canvas.create_text(180, 15, text="Esteira E (laranja) / D (verde) — PWM comandado",
                           fill="#d3e9f6")
        for index, color in ((0, "#ffa65b"), (1, "#89d49a")):
            coords = []
            for i, sample in enumerate(self._history):
                coords.extend((30 + i * (width - 50) / max(1, self._history.maxlen - 1),
                               center - max(-1., min(1., float(sample[index]))) * scale))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2)

    def plot_speeds(self):
        canvas = self.speed_chart
        canvas.delete("all")
        width = max(500, canvas.winfo_width())
        geometry = self.config.data["geometry"]
        sample = estimate(0, 0, geometry)
        if sample is None:
            canvas.create_text(width / 2, 55,
                               text="Gráfico de RPM estimada: informe geometria e RPM calibrada.",
                               fill="#d3e9f6")
            return
        max_rpm = float(geometry["output_max_rpm"])
        canvas.create_line(30, 58, width - 16, 58, fill="#66758a")
        canvas.create_text(210, 14, text="RPM estimada E (laranja) / D (verde) — sem encoder",
                           fill="#d3e9f6")
        canvas.create_text(25, 14, text="+{:.0f}".format(max_rpm), fill="white")
        canvas.create_text(25, 106, text="−{:.0f}".format(max_rpm), fill="white")
        for name, color in (("left_rpm_est", "#ffa65b"), ("right_rpm_est", "#89d49a")):
            coords = []
            for i, (left, right) in enumerate(self._history):
                value = estimate(left, right, geometry)[name]
                coords.extend((30 + i * (width - 50) / max(1, self._history.maxlen - 1),
                               58 - value * 40 / max_rpm))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2)

    def _tick(self):
        if self._closing:
            return
        self.inputs.poll()
        self.inputs.set_link(self.connection.connected)
        operator = self.inputs.snapshot()
        result = self.vision.snapshot()
        self.inputs.update_camera(getattr(self.vision.engine,'last_record',{}),
            operator.get('requested_mode','manual'), bool(result.frame_stamp),
            bool(result.person_detected), self.config.data.get('control',{}))
        with self.telemetry_lock:
            telem = (dict(self.telemetry) if self.connection.connected and
                     time.monotonic() - self.telemetry_stamp <= .9 else {})
        frame = result.live
        display = cv2.resize(frame,(960,720))
        image = cv2.cvtColor(display,cv2.COLOR_BGR2RGB)
        self._photos[0] = ImageTk.PhotoImage(Image.fromarray(image), master=self.root)
        self.images[0].configure(image=self._photos[0])
        operator = self.inputs.snapshot()
        link = ("CONECTADO POR " + self.connection.active_transport.upper()
                if self.connection.connected else "DESCONECTADO")
        camera = "CONECTADA" if result.frame_stamp else "DESCONECTADA"
        self.status.set(f"ESP32: {link}   |   Câmera: {camera}   |   Visão: {result.status}   |   "
                        f"Modo solicitado: {operator['requested_mode']} / aplicado: {telem.get('mode', '—')}")
        if not self.connection.connected:
            self.status.set("ROBÔ DESCONECTADO — controles bloqueados; rearme após reconexão")
        if telem:
            val = lambda key: "—" if telem.get(key) is None else str(telem[key])
            self.readings.set(
                f"Segurança: {val('safety')}   Bloqueio: {val('reason')}   Movimento: {val('motion')}   Rearmado: {val('armed')}\n"
                f"Interno: {val('temp_internal')} °C / {val('humidity_internal')} % (válido: {val('sensor_internal_valid')})   "
                f"Externo: {val('temp_external')} °C / {val('humidity_external')} % (válido: {val('sensor_external_valid')})\n"
                f"Esteiras comandadas E/D: {val('drive_left_commanded')} / {val('drive_right_commanded')}   "
                f"Servos comandados pan/tilt/câmera: {val('servo_pan_commanded')} / {val('servo_tilt_commanded')} / {val('camera_pan_commanded')}\n"
                f"Arref. interno/externo comandado: {val('cool_internal_commanded')} / {val('cool_external_commanded')}   "
                f"Canais instalados: {val('cool_internal_configured')} / {val('cool_external_configured')}\n"
                f"Válvula jato comandada: {val('jet_commanded')} (instalada: {val('jet_configured')})   "
                f"Jato virtual: {val('jet_virtual')}   LEDs comandados/configurados: {val('leds_commanded')}/{val('leds_configured')}   "
                f"Alertas térmicos I/E: {val('alert_internal')}/{val('alert_external')}\n"
                f"Água habilitada: {val('water_on')}   Pressão solicitada: {val('pressure_requested')}   "
                f"Foco SG90 solicitado: {val('focus_requested')}   Freio: {val('brake')}   "
                f"Emergência: {val('emergency')}\n"
                f"Atuador de pressão/foco instalado: {val('pressure_actuator_configured')}/"
                f"{val('focus_actuator_configured')}   Setup ESP32: {val('setup_name')}"
            )
            left = float(telem.get('drive_left_commanded') or 0)
            right = float(telem.get('drive_right_commanded') or 0)
            self._history.append((left, right))
            self.plot_commands()
            self.plot_speeds()
            values = estimate(left, right, self.config.data["geometry"])
            if values:
                self.readings.set(self.readings.get() +
                                  f"\nESTIMATIVA: E/D {values['left_rpm_est']:.1f}/{values['right_rpm_est']:.1f} rpm; "
                                  f"Vx chassi {values['vx_body_mps_est']:.3f} m/s; "
                                  f"Vy chassi 0; giro {values['yaw_rad_s_est']:.3f} rad/s")
        else:
            self.readings.set("Telemetria indisponível; comandos locais bloqueados até reconexão e REARMAR.")
            self._history.append((0., 0.))
            self.plot_commands()
            self.plot_speeds()
        self.root.after(60, self._tick)

    def run(self):
        self.connection.start()
        self.camera.start()
        self.vision.start()
        self.root.after(100, self._tick)
        self.root.mainloop()

    def close(self):
        self._closing = True
        self.inputs.action("stop")
        self.connection.stop()
        self.vision.stop()
        self.camera.stop()
        self.root.destroy()


# ===== __MAIN__ =====
import argparse

def main():
    parser = argparse.ArgumentParser(description="Central BLAZE independente do notebook")
    parser.add_argument("--profile", choices=("simulacao", "combate_real"),
                        default="simulacao", help="Perfil da janela de seleção")
    args = parser.parse_args()
    from launcher import run
    run(args.profile)




# ===== DETECÇÃO LOCAL PARA OS DOIS NOTEBOOKS =====
import base64
import subprocess
import sys
def probe(kind: str, value: str = ''):
    if kind == 'camera':
        import cv2

        index = int(value)
        device = cv2.VideoCapture(
            index, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
        try:
            return {'index': index, 'available': bool(device.isOpened())}
        finally:
            device.release()
    if kind == 'preview':
        import cv2

        source = int(value) if value.isdigit() else value
        device = cv2.VideoCapture(
            source, cv2.CAP_DSHOW if sys.platform == 'win32' and isinstance(source, int)
            else cv2.CAP_ANY)
        try:
            if not device.isOpened():
                return {'available': False, 'reason': 'Câmera não abriu'}
            frame = None
            for _ in range(5):
                ok, image = device.read()
                if ok and image is not None:
                    frame = image
                    break
            if frame is None:
                return {'available': False, 'reason': 'Sem quadro recebido'}
            height, width = frame.shape[:2]
            if width > 640:
                frame = cv2.resize(frame, (640, round(height * 640 / width)))
            ok, encoded = cv2.imencode('.jpg', frame)
            return {'available': bool(ok), 'image': base64.b64encode(encoded).decode('ascii') if ok else '',
                    'size': [width, height]}
        finally:
            device.release()
    if kind == 'serial':
        from serial.tools import list_ports

        return [{'device': p.device, 'description': p.description}
                for p in list_ports.comports()]
    if kind == 'joystick':
        import pygame

        pygame.joystick.init()
        try:
            return [{'index': i, 'name': pygame.joystick.Joystick(i).get_name()}
                    for i in range(pygame.joystick.get_count())]
        finally:
            pygame.joystick.quit()
    if kind == 'mdns':
        if value not in ('_rtsp._tcp.local.', '_blaze._tcp.local.'):
            raise ValueError('Tipo de serviço não permitido')
        return discover_services(value, seconds=0.7)
    raise ValueError('Sondagem desconhecida')



PREFIX = 'BLAZE_DEVICES:'


@dataclass(frozen=True)
class Probe:
    label: str
    kind: str
    value: str = ''
    timeout: float = 3.0


class DeviceScanner:
    def __init__(self, project_pc: Path, on_update: Callable,
                 command_factory: Callable | None = None):
        self.project_pc = Path(project_pc)
        self.on_update = on_update
        self.command_factory = command_factory or self._command
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._process = None
        self._thread = None

    @staticmethod
    def _command(task):
        return [sys.executable, '-c',
                'import json, sys; from runtime import probe; print(\"BLAZE_DEVICES:\" + json.dumps(probe(sys.argv[1], sys.argv[2]), ensure_ascii=False), flush=True)',
                task.kind, str(task.value)]

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, tasks):
        with self._lock:
            if self.running:
                return False
            self._cancel = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(tuple(tasks), self._cancel),
                                            name='blaze-device-scan', daemon=True)
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            self._cancel.set()
            if self._process is not None and self._process.poll() is None:
                self._process.kill()

    def _run(self, tasks, cancelled):
        try:
            for task in tasks:
                if cancelled.is_set():
                    break
                self.on_update(task.label, 'buscando', None)
                try:
                    command = self.command_factory(task)
                    with self._lock:
                        if cancelled.is_set():
                            break
                        process = subprocess.Popen(command, cwd=str(self.project_pc),
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                   text=True)
                        self._process = process
                    try:
                        out, err = process.communicate(timeout=task.timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        if not cancelled.is_set():
                            self.on_update(task.label, 'tempo esgotado', None)
                        continue
                    if cancelled.is_set():
                        break
                    lines = [line[len(PREFIX):] for line in out.splitlines() if line.startswith(PREFIX)]
                    if process.returncode or not lines:
                        explanation = (err.strip().splitlines()[-1][:180] if err.strip()
                                       else 'sonda sem resultado')
                        self.on_update(task.label, 'erro', explanation)
                        continue
                    value = json.loads(lines[-1])
                    available = bool(value.get('available')) if isinstance(value, dict) else bool(value)
                    self.on_update(task.label, 'detectado' if available else 'ausente', value)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    if not cancelled.is_set():
                        self.on_update(task.label, 'erro', str(exc)[:180])
                finally:
                    with self._lock:
                        self._process = None
            if cancelled.is_set():
                self.on_update('__overall__', 'interrompida', None)
            else:
                self.on_update('__overall__', 'concluída', None)
        except Exception as exc:
            self.on_update('__overall__', 'erro', repr(exc))


if __name__ == "__main__":
    main()
