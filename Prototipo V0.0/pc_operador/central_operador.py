"""Central independente dos notebooks: usa a mesma apresentação da seção 12."""
import math
import os
import time
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageTk

import runtime as blaze_runtime

_R12_SIM = False
_r12_bindings = {}

def configure(config):
    global _R12_SIM, _r12_bindings
    _R12_SIM = str(config.data.get('vision', {}).get('combat_mode', '')).lower() in (
        'simulation', 'simulacao', 'simulação')
    control = config.data.get('control', {})
    _r12_bindings = {}
    for key, (kind, index) in _R12_DEFAULT.items():
        fallback = {'kind': kind, 'index': index}
        if kind == 'hat':
            fallback['direction'] = {'camera_left':[-1,0], 'camera_right':[1,0],
                                     'overlay':[0,1], 'stop':[0,-1]}[key]
        _r12_bindings[key] = dict(control.get('input_bindings', {}).get(key, fallback))
        if int(control.get('schema_version', 0)) < 4 and key in ('stop', 'camera_left', 'camera_right'):
            _r12_bindings[key] = fallback

class _SessionMarker:
    def close(self):
        pass  # VisionWorker encerra a sessão após parar a thread.

def _r12_vision_adapter(app):
    if app.vision.engine.session is None:
        return None, app.vision.engine.model_error
    return _SessionMarker(), ''

class _R12LiveReader:
    """Detecta conexão tardia e desconexão do controle no processo do runtime."""
    def __init__(self, index=0):
        self.index = index
        self.joy = None
        self.info = {'name':'Aguardando Xbox', 'index':index}
        self.pygame = None
        self._cached = None
        self._cached_at = 0.
        try:
            import pygame
            self.pygame = pygame
            pygame.init()
            pygame.joystick.init()
        except Exception:
            pass

    def snapshot(self):
        if self.pygame is None:
            return None
        if time.monotonic()-self._cached_at < .025:
            return self._cached
        try:
            self.pygame.event.pump()
            count = self.pygame.joystick.get_count()
            if not count or self.index >= count:
                self.joy = None
                self._cached=None
                self._cached_at=time.monotonic()
                return None
            if self.joy is None or not self.joy.get_init():
                self.joy = self.pygame.joystick.Joystick(self.index)
                self.joy.init()
                self.info = {'name':self.joy.get_name(), 'index':self.index}
            self._cached={'axes':[self.joy.get_axis(i) for i in range(self.joy.get_numaxes())],
                    'buttons':[self.joy.get_button(i) for i in range(self.joy.get_numbuttons())],
                    'hats':[self.joy.get_hat(i) for i in range(self.joy.get_numhats())]}
            self._cached_at=time.monotonic()
            return self._cached
        except Exception:
            self.joy = None
            self._cached=None
            return None

    def close(self):
        if self.joy is not None:
            try:self.joy.quit()
            except Exception:pass
        self.joy = None

class _JoystickProxy:
    def __init__(self, reader):self.reader=reader
    def get_init(self):return self.reader.snapshot() is not None
    def get_numaxes(self):return len((self.reader.snapshot() or {}).get('axes', []))
    def get_numbuttons(self):return len((self.reader.snapshot() or {}).get('buttons', []))
    def get_numhats(self):return len((self.reader.snapshot() or {}).get('hats', []))
    def get_axis(self, i):
        a=(self.reader.snapshot() or {}).get('axes', [])
        return a[i] if 0<=i<len(a) else 0.
    def get_button(self, i):
        a=(self.reader.snapshot() or {}).get('buttons', [])
        return a[i] if 0<=i<len(a) else 0
    def get_hat(self, i):
        a=(self.reader.snapshot() or {}).get('hats', [])
        return a[i] if 0<=i<len(a) else (0,0)
    def quit(self):pass

class _PygameProxy:
    class event:
        @staticmethod
        def pump():pass
    class joystick:
        @staticmethod
        def get_count():return 0

def attach_controller(app):
    reader=_R12LiveReader(int(app.config.data.get('xbox_index', 0)))
    app.xbox_reader=reader
    app.inputs.joy=_JoystickProxy(reader)
    app.inputs.pygame=_PygameProxy()
    return reader

_R12_DEFAULT = {
    'lt': ('axis', 4), 'drive_x': ('axis', 0), 'drive_y': ('axis', 1),
    'lb': ('button', 4), 'rt': ('axis', 5), 'rb': ('button', 5),
    'r3': ('button', 9), 'cannon_x': ('axis', 2), 'cannon_y': ('axis', 3),
    'mode': ('button', 2), 'cool_internal': ('button', 0),
    'cool_external': ('button', 1), 'leds': ('button', 3),
    'camera_left': ('hat', 0), 'camera_right': ('hat', 0), 'overlay': ('hat', 0),
    'link_hold': ('button', 7), 'stop': ('hat', 0), 'water': ('button', 6),
}

_R12_NAMES = {
    'lt': 'LT', 'drive_x': 'Stick esquerdo X', 'drive_y': 'Stick esquerdo Y',
    'lb': 'LB', 'rt': 'RT', 'rb': 'RB', 'r3': 'R3',
    'cannon_x': 'Stick direito X', 'cannon_y': 'Stick direito Y',
    'mode': 'X', 'cool_internal': 'A', 'cool_external': 'B', 'leds': 'Y',
    'camera_left': 'Seta esquerda', 'camera_right': 'Seta direita',
    'overlay': 'Seta para cima',
    'link_hold': 'Start 2 s', 'stop': 'Seta para baixo 1 s', 'water': 'View',
}

def _r12_decode(packet):
    axes = packet.get('axes', []) if packet else []
    buttons = packet.get('buttons', []) if packet else []
    hats = packet.get('hats', []) if packet else []
    result = {}
    for key, binding in _r12_bindings.items():
        kind = binding.get('kind')
        index = int(binding.get('index', -1))
        if kind == 'axis' and 0 <= index < len(axes):
            raw = float(axes[index])
            if key in ('lt', 'rt'):
                rest = float(binding.get('rest', -1))
                active = float(binding.get('active', 1))
                result[key] = (max(0., min(1., (raw-rest)/(active-rest)))
                               if abs(active-rest) > .1 else 0.)
            else:
                result[key] = max(-1., min(1., raw))
        elif kind == 'button':
            result[key] = bool(buttons[index]) if 0 <= index < len(buttons) else False
        elif kind == 'hat':
            result[key] = (tuple(hats[index]) == tuple(binding.get('direction', (0, 0)))
                           if 0 <= index < len(hats) else False)
        else:
            result[key] = 0. if key in ('lt', 'rt', 'drive_x', 'drive_y',
                                        'cannon_x', 'cannon_y') else False
    return result

def _r12_new_control_state():
    return {'connected':False,'emergency':False,'mode':'manual',
      'cool_internal':False,'cool_external':False,'leds':False,'water':False,
      'overlay':False,'camera_pan_deg':90.,'scan_direction':1,
      'last_recenter':0.,'edge_latched':False,'focus':0.,'pan':0.,'tilt':45.,
      'aim_x':0.,'aim_y':0.,'x':750.,'y':470.,'heading':0.,
      'left_rpm':0.,'right_rpm':0.,'v_mps':0.,'omega':0.,
      'throttle':0.,'pressure':0.,'link_hold_since':None,'hold_latched':False,
      'stop_hold_since':None,'stop_latched':False,
      'previous':{},'hint':'Segure Start por 2 s para conectar o robô (simulado).'}

def _r12_deadzone(value,threshold=.08):
    value=float(value)
    return 0. if abs(value)<threshold else max(-1.,min(1.,value))

def _r12_apply_control(s, c, now, dt, rpm_limit, geometry, camera_settings=None):
    """Simula a máquina de estados; não envia sinais ao ESP32."""
    camera_settings = camera_settings or {}
    dt=max(0.,min(.12,float(dt)))
    prev=s['previous'];rising=lambda key: bool(c.get(key)) and not prev.get(key,False)
    if c.get('stop'):
        if s['stop_hold_since'] is None:s['stop_hold_since']=now
        if not s['stop_latched'] and now-s['stop_hold_since']>=1.:
            s.update(emergency=not s['emergency'],water=False,
                     cool_internal=False,cool_external=False,throttle=0.,pressure=0.,
                     left_rpm=0.,right_rpm=0.)
            s['hint']=('PARADA DE EMERGÊNCIA: segure a seta para baixo 1 s para rearmar.'
                       if s['emergency'] else 'Rearmado; comunicação mantida.')
            s['stop_latched']=True
    else:
        s['stop_hold_since']=None;s['stop_latched']=False
    start=bool(c.get('link_hold'))
    if start:
        if s['link_hold_since'] is None:s['link_hold_since']=now
        if not s['hold_latched'] and now-s['link_hold_since']>=2.:
            neutral=(abs(float(c.get('drive_x',0)))<.08 and abs(float(c.get('drive_y',0)))<.08
                      and float(c.get('lt',0))<.08 and float(c.get('rt',0))<.08
                      and not c.get('stop'))
            if not neutral:
                s['hint']='Solte LT/RT e a seta para baixo; centralize os sticks para conectar/rearmar.'
            elif s['connected']:
                s.update(connected=False,water=False,pressure=0.,throttle=0.,
                         cool_internal=False,cool_external=False,leds=False)
                s['hint']='Conexão cortada. Segure Start por 2 s para reconectar.'
                s['hold_latched']=True
            else:
                s['connected']=True
                s['hint']='Conectado (simulado). View libera água; LT acelera; LB freia.'
                s['hold_latched']=True
    else:s['link_hold_since']=None;s['hold_latched']=False
    if not s['connected'] or s['emergency']:
        s['throttle']=s['pressure']=s['v_mps']=s['omega']=0.
        s['left_rpm']=s['right_rpm']=0.
        if not s['emergency'] and not start and (float(c.get('lt',0))>.08 or
             float(c.get('rt',0))>.08 or any(rising(k) for k in ('water','mode','rb','r3'))):
            s['hint']='Primeiro segure Start por 2 s para conectar.'
    else:
        for key,field in (('mode','mode'),('water','water'),('cool_internal','cool_internal'),
                          ('cool_external','cool_external'),('leds','leds'),('overlay','overlay')):
            if not rising(key):continue
            if key=='mode':s['mode']='auto' if s['mode']=='manual' else 'manual'
            else:s[field]=not s[field]
            s['hint']=f'{_R12_NAMES[key]}: comando atualizado.'
        if c.get('rb') and c.get('r3'):
            s['hint']='Solte RB ou R3: focalizar e dispersar são comandos opostos.'
        elif c.get('rb'):s['focus']=min(1.,s['focus']+.35*dt)
        elif c.get('r3'):s['focus']=max(0.,s['focus']-.35*dt)
        throttle=max(0.,min(1.,float(c.get('lt',0))))
        if c.get('lb'):
            if throttle>.08:s['hint']='LB acionado: solte o freio para acelerar.'
            throttle=0.
        x=_r12_deadzone(c.get('drive_x',0));y=-_r12_deadzone(c.get('drive_y',0))
        s['throttle']=throttle
        left=throttle*max(-1.,min(1.,y+x))
        right=throttle*max(-1.,min(1.,y-x))
        s['left_rpm']=rpm_limit*left;s['right_rpm']=rpm_limit*right
        pressure=max(0.,min(1.,float(c.get('rt',0))))
        s['pressure']=pressure if s['water'] else 0.
        if pressure>.08 and not s['water']:
            s['hint']='Aperte View para liberar água antes de pressionar RT.'
        radius=float(geometry.get('sprocket_radius_m') or 0)
        width=float(geometry.get('track_width_m') or 0)
        if radius>0 and width>0:
            vl=left*rpm_limit*2*math.pi*radius/60
            vr=right*rpm_limit*2*math.pi*radius/60
            s['v_mps']=(vl+vr)/2;s['omega']=(vr-vl)/width
            # Ângulo positivo na tela aponta à direita; yaw cinemático positivo é anti-horário.
            s['heading']-=s['omega']*dt
            travel=s['v_mps']*115*dt
        else:
            s['v_mps']=s['omega']=0.
            s['heading']-=(right-left)*1.2*dt
            travel=(left+right)*42*dt
        s['x']=(s['x']+math.sin(s['heading'])*travel-110)%1280+110
        s['y']=(s['y']-math.cos(s['heading'])*travel-225)%515+225
        if s['mode']=='manual':
            sx=_r12_deadzone(c.get('cannon_x',0));sy=_r12_deadzone(c.get('cannon_y',0))
            direction=int(c.get('camera_right',False))-int(c.get('camera_left',False))
            (s['pan'],s['tilt'],s['camera_pan_deg'],s['aim_x'],s['aim_y']) = (
                blaze_runtime.coupled_manual_pose(
                    s['pan'],s['tilt'],s['camera_pan_deg'],sx,sy,direction,dt,
                    float(camera_settings.get('camera_manual_speed_deg_s',45.)),
                    float(camera_settings.get('camera_edge_offset_px',8.)),370.,
                    float(camera_settings.get('camera_recenter_step_deg',20.))))
        # Na simulação, a câmera procura fogo no modo automático.
        if s['mode']=='auto' and not c.get('stop') and not s['emergency']:
            record=s.get('vision_record',{})
            if not record.get('person_detected') and not record.get('firefighter_detected'):
                size=int(record.get('frame_width') or 0)
                aim=record.get('aim_px')
                if record.get('target_valid') and aim and size:
                    margin=int(camera_settings.get('camera_edge_offset_px',8))
                    direction=-1 if aim[0]<=margin else 1 if aim[0]>=size-1-margin else 0
                    if not direction and margin+12<aim[0]<size-margin-13:
                        s['edge_latched']=False
                    if direction and not s['edge_latched'] and now-s['last_recenter']>.6:
                        s['camera_pan_deg']=max(0.,min(180.,s['camera_pan_deg']+direction*
                            float(camera_settings.get('camera_recenter_step_deg',20.))))
                        s['last_recenter']=now
                        s['edge_latched']=True
                else:
                    s['edge_latched']=False
                    s['camera_pan_deg']+=(s['scan_direction']*
                        float(camera_settings.get('camera_scan_speed_deg_s',12.))*dt)
                    if s['camera_pan_deg']>=180:s['camera_pan_deg']=180.;s['scan_direction']=-1
                    if s['camera_pan_deg']<=0:s['camera_pan_deg']=0.;s['scan_direction']=1
    s['previous']={k:bool(c.get(k)) for k in _R12_DEFAULT if _R12_DEFAULT[k][0]!='axis'}
    return s

class CentralOperador(blaze_runtime.OperatorApp):
    """Apresentação no PC; câmera, Xbox e telemetria usam o runtime existente."""

    BG = '#101b29'
    CARD = '#203044'
    FG = '#eef5fb'
    MUTED = '#a9bfd0'
    GREEN = '#dcf7e4'
    RED = '#ffe2df'
    YELLOW = '#fff3bf'
    NEUTRAL = '#e1e8f0'

    def __init__(self, config):
        self.return_to_launcher = False
        self._manual_aim_deg = None
        self._last_green_uv = (.5,.5)
        self._reticle_at = time.monotonic()
        self._last_secondary_update = 0.
        self._secondary_due = True
        self._previous_numbers = {}
        self.simulation = _R12_SIM
        self.sim_state = _r12_new_control_state() if self.simulation else None
        self.sim_controls = _r12_decode(None)
        self.sim_last_tick = time.monotonic()
        self.manual_trail = []
        self.vision_session = None
        self.vision_warning = ''
        super().__init__(config)
        if self.simulation:
            original_snapshot = self.inputs.snapshot
            def snapshot_for_local_vision():
                state = original_snapshot()
                state['mode'] = ('auto' if self.sim_state['connected'] and
                                 self.sim_state['mode'] == 'auto' else 'manual')
                state['requested_mode'] = state['mode']
                state['cannon_x'] = self.sim_controls.get('cannon_x', 0.)
                state['cannon_y'] = self.sim_controls.get('cannon_y', 0.)
                state['camera_pan_deg'] = self.sim_state['camera_pan_deg']
                return state
            self.inputs.snapshot = snapshot_for_local_vision
        try:
            self.vision_session, self.vision_warning = _r12_vision_adapter(self)
        except Exception as exc:
            self.vision_warning = f'Visão da seção 4 indisponível: {type(exc).__name__}: {exc}'

    def _command(self):
        if self.simulation or not self._matching_firmware():
            # Simulação e firmware de outra combinação enviam somente parada.
            return blaze_runtime.control_message({
                'requested_mode': 'manual', 'stop': True, 'rearm': False,
                'drive_x': 0, 'drive_y': 0, 'cannon_x': 0, 'cannon_y': 0,
                'cool_manual': False, 'cool_internal': False,
                'cool_external': False, 'jet_enable': False,
            }, {'valid': False, 'target_valid': False,
                'person_detected': False, 'pan': 90, 'tilt': 90})
        command = super()._command()
        state = self.inputs.snapshot()
        if command['mode']=='manual' and state.get('manual_target_valid'):
            command['manual_target_valid']=True
            command['manual_pan']=float(state['manual_pan'])
            command['manual_tilt']=float(state['manual_tilt'])
        if command['mode']=='auto':
            camera_angle=float(state.get('camera_pan_deg',90))
            shape=getattr(self.camera.latest()[0],'shape',None) or (540,960,3)
            pan_bounds,tilt_bounds=blaze_runtime.camera_view_limits(
                shape,self.config.vision.calibration,self.config.vision.params,camera_angle,
                self.config.data.get('control',{}).get('camera_edge_offset_px',8))
            if command['target_valid']:
                command['auto_pan']=blaze_runtime.clamp(command['auto_pan'],*pan_bounds)
                command['auto_tilt']=blaze_runtime.clamp(command['auto_tilt'],*tilt_bounds)
            elif (state.get('auto_follow_pan') is not None and
                  command.get('vision_valid') and not command.get('person_detected')):
                command['auto_pan']=blaze_runtime.clamp(state['auto_follow_pan'],*pan_bounds)
                command['auto_tilt']=blaze_runtime.clamp(state['auto_follow_tilt'],*tilt_bounds)
                command['target_valid']=True
                command['jet_enable']=False
        hardware = self.config.data.get('hardware', {})
        if hardware.get('drive_kind') == 'bldc_ktc86':
            command['drive_x'] = command['drive_y'] = 0.
        if hardware.get('cannon_kind') == 'ht23_ec1000':
            command['cannon_x'] = command['cannon_y'] = 0.
            command['target_valid'] = command['jet_enable'] = False
        if command['mode'] == 'auto' and (
                not blaze_runtime.camera_calibration_complete(self.config.vision.calibration)
                or not state.get('camera_settled', False)):
            command['jet_enable'] = False
        return command

    def _matching_firmware(self):
        if self.simulation or not hasattr(self, 'telemetry_lock'):
            return self.simulation
        with self.telemetry_lock:
            signature = self.telemetry.get('setup_signature')
            recent = time.monotonic() - self.telemetry_stamp < 1.5
        expected_signature = self.config.data.get('_official', {}).get('firmware_signature')
        # Pacotes rápidos trazem a assinatura; o nome só aparece nos completos.
        return bool(self.connection.connected and recent and
                    blaze_runtime.protocol_compatible(self.telemetry) and
                    expected_signature and signature == expected_signature)

    def _build(self):
        # Tamanho explícito: alguns temas do Tk no Windows iniciam com
        # geometria 1x1 antes de posicionar os widgets do notebook.
        screen_w = max(1100, self.root.winfo_screenwidth())
        screen_h = max(760, self.root.winfo_screenheight())
        width = min(1450, screen_w - 50)
        height = min(920, screen_h - 95)
        left = max(0, (screen_w - width) // 2)
        top = max(0, (screen_h - height) // 2)
        self.root.geometry(f'{width}x{height}+{left}+{top}')
        self.root.resizable(True, True)
        self.root.overrideredirect(False)
        self.root.minsize(950, 650)
        self.root.bind('<F11>', lambda _event: self.root.state(
            'normal' if self.root.state() == 'zoomed' else 'zoomed'))
        self.root.configure(bg=self.BG)

        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill='x', padx=16, pady=(10, 7))
        tk.Label(header, text='BLAZE  ·  CENTRAL DO OPERADOR',
                 font=('Segoe UI', 17, 'bold'), bg=self.BG, fg=self.FG).pack(side='left')
        name = self.config.data.get('_official', {}).get('name', 'sem nome')
        limit = self.config.data.get('control', {}).get('speed_limit_rpm', '—')
        hw=self.config.data.get('hardware',{})
        backend=f"{hw.get('drive_kind','bts7960_12v')} / {hw.get('cannon_kind','mg996r')}"
        tk.Label(header, text=f'Setup: {name[:72]}{"…" if len(name)>72 else ""}  ·  {backend}  ·  limite {limit} RPM',
                 font=('Segoe UI', 10), bg=self.BG, fg=self.MUTED).pack(side='left', padx=20)
        tk.Label(header, text='F5: recarregar parâmetros', bg=self.BG,
                 fg=self.MUTED, font=('Segoe UI', 9)).pack(side='right')
        navigation=tk.Frame(self.root,bg=self.BG)
        navigation.pack(fill='x',padx=16,pady=(0,6))
        tk.Button(navigation,text='← Voltar à primeira janela',
                  command=self._return_to_launcher).pack(side='right')

        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill='both', expand=True, padx=14, pady=(0, 5))
        body.grid_columnconfigure(0, weight=7)
        body.grid_columnconfigure(1, weight=3, minsize=330)
        body.grid_rowconfigure(0, weight=1)

        picture = tk.Frame(body, bg=self.CARD, highlightbackground='#567087',
                           highlightthickness=1)
        picture.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        tk.Label(picture, text=('Visão RGB · simulação virtual no PC' if self.simulation
                                else 'Visão RGB · combate real sem efeitos virtuais'),
                 bg=self.CARD, fg=self.FG, font=('Segoe UI', 11, 'bold')).pack(pady=6)
        tk.Label(picture, text='Verde: mira desejada · Azul: posição física medida (três sensores de ângulo calibrados)',
                 bg=self.CARD, fg='#b8d6ea', font=('Segoe UI', 9)).pack(pady=(0,3))
        tk.Label(picture, text='Escala verde: azimute em graus; traços a cada 5, campo horizontal ilustrativo de 120 graus',
                 bg=self.CARD, fg='#b8d6ea', font=('Segoe UI', 8)).pack(pady=(0,2))
        self.video_label = tk.Label(picture, bg='#080d13', fg=self.FG,
                                    text='Aguardando quadros da câmera')
        self.video_label.pack(fill='both', expand=True, padx=7, pady=(0, 7))
        # Compatibilidade com o atributo usado no runtime anterior.
        self.images = [self.video_label]

        state_box = tk.Frame(body, bg=self.CARD, highlightbackground='#567087',
                             highlightthickness=1)
        state_box.grid(row=0, column=1, sticky='nsew')
        tk.Label(state_box, text='Estados e parâmetros de controle',
                 bg=self.CARD, fg=self.FG,
                 font=('Segoe UI', 10, 'bold')).pack(pady=(3, 1))
        scroll = tk.Canvas(state_box, bg=self.CARD, highlightthickness=0)
        scrollbar = tk.Scrollbar(state_box, orient='vertical', command=scroll.yview)
        scroll.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        scroll.pack(side='left', fill='both', expand=True, padx=(7, 0), pady=(0, 7))
        rows = tk.Frame(scroll, bg=self.CARD)
        window = scroll.create_window((0, 0), window=rows, anchor='nw')
        rows.bind('<Configure>', lambda _event: scroll.configure(
            scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda event: scroll.itemconfig(window, width=event.width))

        self.state_values = {}
        sections = (
          ('Acionamentos', (
            ('mode', 'Modo canhão (X)'), ('water', 'Água (View)'),
            ('throttle', 'Aceleração (LT)'), ('brake', 'Freio (LB)'),
            ('pressure', 'Pressão (RT)'),
            ('drive_xy', 'Esteiras X / Y'),
            ('cannon_xy', 'Canhão X / Y'),
            ('left', 'Esteira E · comando'),
            ('right', 'Esteira D · comando'),
            ('left_rpm', 'Esteira E · RPM'),
            ('right_rpm', 'Esteira D · RPM'),
            ('pan_target', 'Alvo pan'),
            ('tilt_target', 'Alvo tilt'),
            ('focus', 'Focalização (RB / R3)'),
            ('leds', 'LEDs (Y)'),
            ('jet', 'Jato (View / automático)'),
            ('camera_select', 'Plataforma (setas ←/→)'),
            ('overlay', 'Informações (seta ↑)'),
          )),
          ('Sensoriamento e gestão térmica', (
            ('temp_int', 'Temperatura interna'),
            ('hum_int', 'Umidade interna'), ('temp_ext', 'Temperatura externa'),
            ('hum_ext', 'Umidade externa'),
            ('cool_int', 'Arref. interno (A/auto)'),
            ('cool_ext', 'Arref. externo (B/auto)'),
          )),
          ('Comunicação e demais estados', (
            ('esp', 'ESP32 (Start)'),
            ('armed', 'Armado (seta ↓)'),
            ('link_latency', 'Pacotes / ida e volta'),
            ('xbox', 'Controle Xbox'),
          )),
        )
        for heading, labels in sections:
            tk.Label(rows, text=heading, bg='#31465a', fg=self.FG,
                     font=('Segoe UI', 8, 'bold'), anchor='w',
                     padx=5, pady=1).pack(fill='x', pady=(3, 1))
            for key, label in labels:
                line = tk.Frame(rows, bg=self.CARD)
                line.pack(fill='x', padx=2, pady=0)
                tk.Label(line, text=label, bg=self.CARD, fg=self.FG,
                         font=('Segoe UI', 8), anchor='w', justify='left',
                         padx=2, pady=0).pack(side='left', fill='x', expand=True)
                value = tk.Label(line, text='—', bg=self.NEUTRAL, fg='#243345',
                                 font=('Segoe UI', 8, 'bold'), anchor='e', padx=3, pady=0)
                value.pack(side='right')
                self.state_values[key] = value

        self.status = tk.StringVar(master=self.root, value='Aguardando Start 2 s para iniciar comunicação')
        self.readings = tk.StringVar(master=self.root, value='Aguardando telemetria')
        tk.Label(self.root, textvariable=self.status, bg=self.BG,
                 fg='#ffe0a0', font=('Segoe UI', 10, 'bold'),
                 anchor='w').pack(fill='x', padx=17, pady=(2, 3))

        self.geometry_values = {}
        self.chart = None
        self.speed_chart = None

    def run(self):
        # Jupyter/Windows pode deixar a raiz em estado 'withdrawn'/'iconic'
        # mesmo após a montagem. A apresentação só começa depois de restaurá-la.
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.state('normal')
        if os.name == 'nt':
            self.root.state('zoomed')
        self.root.resizable(True, True)
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(450, lambda: self.root.attributes('-topmost', False)
                        if self.root.winfo_exists() else None)
        # A central começa sem comunicação; Start por 2 s abre o meio escolhido.
        self.camera.start()
        self.vision.start()
        self.root.after(100, self._tick)
        print('Janela Tk:', self.root.state(), self.root.geometry(),
              '— F11 alterna maximizar/restaurar.')
        self.root.mainloop()

    def close(self):
        try:
            super().close()
        finally:
            if self.vision_session is not None:
                self.vision_session.close()
            reader = getattr(self, 'xbox_reader', None)
            if reader is not None:
                reader.close()
                self.xbox_reader = None

    def _return_to_launcher(self):
        self.return_to_launcher = True
        self.close()

    def _set_state(self, key, value, kind='neutral'):
        # A interface mantém esteiras, canhão, jato e parada rápidos. Leituras
        # ambientais e estados auxiliares não precisam repintar a 10 Hz.
        if key in {'xbox','mode','water','brake','cool_int','cool_ext','leds','overlay',
                   'temp_int','hum_int','temp_ext','hum_ext'} and not self._secondary_due:
            return
        row = self.state_values[key]
        row.configure(text=str(value), bg={
            'good': self.GREEN, 'bad': self.RED, 'steady': self.YELLOW,
            'neutral': self.NEUTRAL,
        }[kind])

    def _set_numeric(self,key,value,unit='',digits=1):
        try:
            values=(tuple(float(x) for x in value) if isinstance(value,(tuple,list))
                    else (float(value),))
            if not all(math.isfinite(x) for x in values):raise ValueError
        except (ValueError,TypeError):
            self._previous_numbers.pop(key,None)
            self._set_state(key,'—','neutral');return
        stamp=time.monotonic()
        previous=self._previous_numbers.get(key)
        changed=(previous is None or len(previous[0])!=len(values) or
                 any(abs(a-b)>=10**(-digits)*.6 for a,b in zip(previous[0],values)))
        changed_at=stamp if changed else previous[1]
        self._previous_numbers[key]=(values,changed_at)
        display=' / '.join(f'{part:.{digits}f}' for part in values)+unit
        self._set_state(key,display,'good' if stamp-changed_at<1.1 else 'steady')

    @staticmethod
    def _number(value, unit='', digits=1):
        try:
            if value is None:
                return '—'
            return f'{float(value):.{digits}f}{unit}'
        except (TypeError, ValueError):
            return '—'

    @staticmethod
    def _state(value):
        if value is None:
            return '—', 'neutral'
        return ('Ligado', 'good') if bool(value) else ('Desligado', 'bad')

    @classmethod
    def _command_state(cls, value, confirmed):
        label, kind=cls._state(value)
        return label, kind

    @staticmethod
    def _reticle(frame, point, color):
        """Quatro traços radiais, deixando o ponto de referência visível."""
        if point is None:
            return
        x, y = map(int, point)
        for a, b in (((x-25,y),(x-10,y)), ((x+10,y),(x+25,y)),
                     ((x,y-25),(x,y-10)), ((x,y+10),(x,y+25))):
            cv2.line(frame,a,b,color,2,cv2.LINE_AA)

    @staticmethod
    def _angular_scale(frame, camera_angle, horizontal_fov=120.):
        """Escala de azimute comandado; 5° por traço, acompanhando a plataforma."""
        try:
            angle=float(camera_angle)
            if not math.isfinite(angle):return
        except (TypeError,ValueError):
            return
        h,w=frame.shape[:2]
        half=float(horizontal_fov)/2
        if w<100 or h<50:return
        band=frame[h-30:h].copy()
        cv2.rectangle(frame,(0,h-30),(w-1,h-1),(3,20,8),-1)
        frame[h-30:h]=cv2.addWeighted(frame[h-30:h],.57,band,.43,0)
        green=(45,230,65)  # BGR
        left,right=angle-half,angle+half
        first=math.ceil(left/5)*5
        label_step=10 if w>=850 else 20
        for degree in range(first,math.floor(right/5)*5+1,5):
            x=round((degree-left)/horizontal_fov*(w-1))
            if not 1<=x<w-1:continue
            cv2.line(frame,(x,h-29),(x,h-21 if degree%label_step==0 else h-24),green,1,cv2.LINE_AA)
            if degree%label_step:continue
            label=str(degree)
            tw=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,.32,1)[0][0]
            if tw//2+2<=x<=w-tw//2-2:
                cv2.putText(frame,label,(x-tw//2,h-5),cv2.FONT_HERSHEY_SIMPLEX,
                            .32,green,1,cv2.LINE_AA)

    def _overlay_aim(self, frame, operator, telemetry, vision_record):
        h,w=frame.shape[:2]
        now=time.monotonic()
        dt=max(0.,min(.15,now-self._reticle_at))
        self._reticle_at=now
        calibration=self.config.vision.calibration
        params=self.config.vision.params
        virtual=self.sim_state if self.simulation else None
        measured=(blaze_runtime.measured_servo_angles(telemetry,calibration)
                  if not virtual and blaze_runtime.camera_calibration_complete(calibration)
                  and telemetry.get('servos_configured')
                  and telemetry.get('camera_servo_configured') else None)
        camera_angle=(virtual['camera_pan_deg'] if virtual else
                      measured['camera'] if measured else
                      telemetry.get('camera_pan_commanded',operator.get('camera_pan_deg',90.)))
        if virtual:
            # Na ilustração o pan tem zero frontal; no mapa dos servos 90° é frontal.
            pan,tilt=90.+virtual['pan'],virtual['tilt']
            if virtual['mode']=='manual':
                green=(int(np.clip((virtual['aim_x']+1)*(w-1)/2,0,w-1)),
                       int(np.clip((virtual['aim_y']+1)*(h-1)/2,0,h-1)))
            else:
                green=vision_record.get('aim_px') if vision_record.get('target_valid') else None
                pan=virtual['pan']
        else:
            pan=telemetry.get('servo_pan_commanded')
            tilt=telemetry.get('servo_tilt_commanded')
            manual=operator.get('requested_mode')!='auto'
            if manual:
                if operator.get('manual_target_valid'):
                    self._manual_aim_deg=[float(operator['manual_pan']),
                                          float(operator['manual_tilt'])]
                elif self._manual_aim_deg is None:
                    self._manual_aim_deg=[float(pan if pan is not None else 90),
                                          float(tilt if tilt is not None else 90)]
                green=blaze_runtime.servos_to_pixel(*self._manual_aim_deg,frame.shape,
                                                       calibration,params,camera_angle)
            else:
                green=vision_record.get('aim_px') if vision_record.get('target_valid') else None
                self._manual_aim_deg=None
        blue=(blaze_runtime.servos_to_pixel(measured['pan'],measured['tilt'],frame.shape,
                                           calibration,params,measured['camera'])
              if measured is not None else None)
        if green is None:
            if not virtual and operator.get('requested_mode')!='auto' and self._manual_aim_deg:
                middle_pan,_=blaze_runtime.pixel_to_servos((w/2,h/2),frame.shape,
                                               calibration,params,camera_angle)
                green=(w-1 if self._manual_aim_deg[0]>=middle_pan else 0,
                       int(self._last_green_uv[1]*(h-1)))
                cv2.putText(frame,'MIRA FORA DO CAMPO DA CAMERA',(10,max(25,h-18)),
                            cv2.FONT_HERSHEY_SIMPLEX,.55,(0,200,255),2,cv2.LINE_AA)
            else:
                green=(int(self._last_green_uv[0]*(w-1)),
                       int(self._last_green_uv[1]*(h-1)))
        else:
            green=(int(np.clip(green[0],0,w-1)),int(np.clip(green[1],0,h-1)))
            self._last_green_uv=(green[0]/max(1,w-1),green[1]/max(1,h-1))
        # Deslocamento de 1 pixel no vídeo não altera o ponto lógico da mira.
        self._reticle(frame,blue,(255,135,0))
        self._reticle(frame,green,(20,235,30))

    def _tick(self):
        if self._closing:
            return
        try:
            now_slow=time.monotonic()
            self._secondary_due=now_slow-self._last_secondary_update>=1.
            if self._secondary_due:self._last_secondary_update=now_slow
            self.inputs.poll()
            want_link = bool(self.inputs.snapshot().get('want_link', False))
            if want_link and not self.connection._running:
                self.connection.start()
            elif not want_link and self.connection._running:
                self.connection.stop()
            self.inputs.set_link(self.connection.connected)
            operator = self.inputs.snapshot()
            reader = getattr(self, 'xbox_reader', None)
            packet = reader.snapshot() if reader is not None else None
            if self.simulation:
                now = time.monotonic()
                self.sim_controls = _r12_decode(packet)
                self.sim_state['vision_record']=getattr(self.vision.engine,'last_record',{})
                if packet is None:
                    # Perda do controle desarma a simulação local.
                    self.sim_state['connected'] = False
                    self.sim_state['water'] = False
                    self.sim_state['previous'] = {}
                    self.sim_state['link_hold_since'] = None
                    self.sim_state['stop_hold_since'] = None
                _r12_apply_control(self.sim_state, self.sim_controls, now,
                                   now-self.sim_last_tick,
                                   max(10, min(80, float(self.config.data.get('control', {})
                                                         .get('speed_limit_rpm', 80)))),
                                   self.config.data.get('geometry', {}),
                                   self.config.data.get('control', {}))
                target_record = self.sim_state['vision_record']
                if (self.sim_state['mode'] == 'auto' and target_record.get('target_valid')
                        and not target_record.get('blocked')):
                    self.sim_state['pan'] = target_record.get('pan_deg') or self.sim_state['pan']
                    self.sim_state['tilt'] = target_record.get('tilt_deg') or self.sim_state['tilt']
                self.sim_last_tick = now
            vision = self.vision.snapshot()
            stamp = getattr(vision, 'frame_stamp', 0) or 0
            vision_recent = bool(stamp and time.monotonic() - stamp < 1.0)
            raw_frame, raw_stamp = self.camera.latest()
            if not self.simulation:
                self.inputs.update_camera(getattr(self.vision.engine,'last_record',{}),
                    operator.get('requested_mode','manual'), vision_recent,
                    bool(vision.person_detected),
                    {**self.config.data.get('control',{}),
                     **{axis+'_'+edge: pair[i]
                        for axis,pair in self.config.vision.calibration.get('angle_limits',{}).items()
                        if axis in ('pan','tilt') and isinstance(pair,(tuple,list)) and len(pair)==2
                        for i,edge in enumerate(('min','max'))},
                     'cannon_rate_deg_s':operator.get('cannon_rate_deg_s',90.)},
                    raw_frame.shape if raw_frame is not None else (540,960,3),
                    self.config.vision.calibration,self.config.vision.params)
                operator = self.inputs.snapshot()
            with self.telemetry_lock:
                telemetry = (dict(self.telemetry) if self.connection.connected
                             and time.monotonic() - self.telemetry_stamp < 1.0 else {})

            if (vision_recent and self.simulation and self.vision_session is not None
                    and self.sim_state['mode'] == 'auto'):
                frame = getattr(vision, 'combat', None)
            elif vision_recent and self.simulation and self.vision_session is not None:
                frame = getattr(vision, 'live', None)
            elif vision_recent and not self.simulation and self.vision_session is not None:
                frame = getattr(vision, 'combat', None)
            else:
                # A câmera continua visível enquanto a inferência inicializa ou falha.
                frame = raw_frame
                stamp = raw_stamp
            if frame is not None and self.simulation and self.sim_state['mode'] == 'manual':
                frame = frame.copy()
                h0, w0 = frame.shape[:2]
                x = int((self.sim_state['aim_x']+1)*w0/2)
                y = int((self.sim_state['aim_y']+1)*h0/2)
                x, y = max(0, min(w0-1, x)), max(0, min(h0-1, y))
                params = self.config.data.get('vision', {}).get('params_override', {})
                lifetime = max(.1, float(params.get('restore_seconds', 6)))
                radius = max(2, int(params.get('erase_radius_px', 25)))
                self.manual_trail = [p for p in self.manual_trail if now-p[0] < lifetime]
                if (self.sim_state['connected'] and not self.sim_state['emergency'] and self.sim_state['water'] and
                        self.sim_state['pressure'] > .08 and
                        not getattr(vision, 'person_detected', False)):
                    self.manual_trail.append((now, x, y))
                self.manual_trail = self.manual_trail[-500:]
                for instant, px, py in self.manual_trail:
                    alpha = max(0., 1.-(now-instant)/lifetime)
                    x0, x1 = max(0, px-radius), min(w0, px+radius+1)
                    y0, y1 = max(0, py-radius), min(h0, py+radius+1)
                    roi = frame[y0:y1, x0:x1]
                    mask = np.zeros(roi.shape[:2], dtype=np.uint8)
                    cv2.circle(mask, (px-x0, py-y0), radius, 255, -1)
                    roi[mask > 0] = (roi[mask > 0]*(1.-alpha)).astype(np.uint8)
                if (self.sim_state['connected'] and not self.sim_state['emergency'] and self.sim_state['water'] and
                        self.sim_state['pressure'] > .08 and
                        not getattr(vision, 'person_detected', False)):
                    drop = float(params.get('jet_drop_px', 90))
                    points = []
                    for t in np.linspace(0., 1., 40):
                        points.append((round(w0/2+(x-w0/2)*t),
                                       round(h0-1+(y-(h0-1)-drop)*t+drop*t*t)))
                    cv2.polylines(frame, [np.asarray(points, np.int32)], False,
                                  (255, 110, 0), max(5, w0//120), cv2.LINE_AA)
            if frame is None or not stamp or time.monotonic() - stamp > 1.0:
                frame = np.zeros((540, 960, 3), dtype=np.uint8)
                cv2.putText(frame, 'AGUARDANDO CAMERA / QUADRO RECENTE', (35, 275),
                            cv2.FONT_HERSHEY_SIMPLEX, .75, (235, 235, 235), 2, cv2.LINE_AA)
            else:
                frame=frame.copy()
                self._overlay_aim(frame,operator,telemetry,
                                  getattr(self.vision.engine,'last_record',{}))
                camera_angle=(self.sim_state['camera_pan_deg'] if self.simulation else
                    telemetry.get('camera_pan_commanded',operator.get('camera_pan_deg',90.)))
                self._angular_scale(frame,camera_angle)
            width = max(600, self.video_label.winfo_width() - 8)
            height = max(360, self.video_label.winfo_height() - 8)
            h, w = frame.shape[:2]
            scale = min(width / w, height / h)
            shown = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
            image = cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)
            self._photos[0] = ImageTk.PhotoImage(Image.fromarray(image), master=self.root)
            self.video_label.configure(image=self._photos[0], text='')

            linked = bool(self.connection.connected and telemetry)
            transport = str(getattr(self.connection, 'active_transport', '') or '—').upper()
            interval=self.connection.last_interval_seconds
            rtt=self.connection.round_trip_seconds
            self._set_numeric('link_latency',
                              (interval*1000,rtt*1000) if linked and rtt is not None else None,
                              ' ms',digits=0)
            xbox_ok = packet is not None
            xbox_label = (f"{reader.info['name']} · dados recebidos" if xbox_ok else
                          'Sinal interrompido' if reader is not None else 'Aguardando')
            self._set_state('xbox', xbox_label,
                            'good' if xbox_ok else 'bad')
            virtual = self.sim_state if self.simulation else None
            start_held=(time.monotonic()-virtual['link_hold_since'] if virtual and
                        virtual['link_hold_since'] is not None else
                        operator.get('start_hold_seconds',0.))
            stop_held=(time.monotonic()-virtual['stop_hold_since'] if virtual and
                       virtual['stop_hold_since'] is not None else
                       operator.get('stop_hold_seconds',0.))
            if start_held>0:
                self._set_state('esp',f'Start {min(start_held,2.):.1f} / 2.0 s','steady')
            else:
                connected_ui=linked or bool(virtual and virtual['connected'])
                self._set_state('esp',f'Conectado ({transport})' if linked else
                                'Conectado (simulado)' if connected_ui else 'Desconectado',
                                'good' if connected_ui else 'bad')
            if stop_held>0:
                self._set_state('armed',f'Seta ↓ {min(stop_held,1.):.1f} / 1.0 s','steady')
            else:
                armed=(virtual['connected'] and not virtual['emergency'] if virtual else
                       telemetry.get('armed') if linked else False)
                self._set_state('armed','Armado' if armed else 'Desarmado',
                                'good' if armed else 'bad')
            mode=virtual['mode'] if virtual else operator.get('requested_mode')
            self._set_state('mode','Autônomo' if mode=='auto' else 'Manual' if mode=='manual' else '—',
                            'good' if mode=='auto' else 'bad' if mode=='manual' else 'neutral')
            self._set_state('water', *self._command_state(
                virtual['water'] if virtual else operator.get('water_on'), bool(virtual)))
            self._set_numeric('throttle',virtual['throttle'] if virtual else operator.get('throttle'),digits=2)
            self._set_state('brake', *self._command_state(
                self.sim_controls['lb'] if virtual else operator.get('brake'), bool(virtual)))
            self._set_numeric('pressure',virtual['pressure'] if virtual else operator.get('pressure'),digits=2)
            self._set_numeric('drive_xy',(operator.get('drive_x'),operator.get('drive_y')),digits=2)
            self._set_numeric('cannon_xy',(operator.get('cannon_x'),operator.get('cannon_y')),digits=2)
            left_cmd = virtual['left_rpm']/max(1., float(self.config.data.get('control', {}).get('speed_limit_rpm', 80))) if virtual else telemetry.get('drive_left_commanded')
            right_cmd = virtual['right_rpm']/max(1., float(self.config.data.get('control', {}).get('speed_limit_rpm', 80))) if virtual else telemetry.get('drive_right_commanded')
            if left_cmd is None or right_cmd is None:
                x,y=float(operator.get('drive_x',0)),float(operator.get('drive_y',0))
                left_cmd,right_cmd=(blaze_runtime.clamp(-y+x,-1,1),
                                    blaze_runtime.clamp(-y-x,-1,1))
            self._set_numeric('left',left_cmd,digits=2)
            self._set_numeric('right',right_cmd,digits=2)
            geometry = self.config.data.get('geometry', {})
            speeds = None
            if virtual:
                speeds = {'left_rpm_est': virtual['left_rpm'], 'right_rpm_est': virtual['right_rpm']}
            elif telemetry and hasattr(blaze_runtime, 'estimate'):
                speeds = blaze_runtime.estimate(
                    float(telemetry.get('drive_left_commanded') or 0),
                    float(telemetry.get('drive_right_commanded') or 0), geometry)
            self._set_numeric('left_rpm',(speeds or {}).get('left_rpm_est'),' rpm')
            self._set_numeric('right_rpm',(speeds or {}).get('right_rpm_est'),' rpm')
            target_record=getattr(self.vision.engine,'last_record',{})
            if virtual:
                target_pan,target_tilt=(virtual['pan'],virtual['tilt'])
            elif operator.get('requested_mode')=='auto':
                target_pan,target_tilt=(target_record.get('pan_deg'),target_record.get('tilt_deg'))
            else:
                target_pan,target_tilt=(self._manual_aim_deg or (None,None))
            self._set_numeric('pan_target',target_pan,'°')
            self._set_numeric('tilt_target',target_tilt,'°')
            self._set_numeric('focus',virtual['focus'] if virtual else operator.get('focus'),digits=2)
            for state_key,wire_key,manual_key in (
                    ('cool_int','cool_internal_commanded','cool_internal'),
                    ('cool_ext','cool_external_commanded','cool_external')):
                manual=bool(virtual[manual_key] if virtual else operator.get(manual_key))
                commanded=telemetry.get(wire_key)
                if virtual:
                    commanded=bool(commanded) or manual  # sem atuação física na simulação
                if commanded is None:
                    self._set_state(state_key,'—','neutral')
                elif commanded:
                    origin='manual' if manual else 'automático'
                    suffix=' virtual' if virtual else ''
                    self._set_state(state_key,f'Ligado ({origin}{suffix})','good')
                else:
                    self._set_state(state_key,'Desligado','bad')
            self._set_state('leds', *self._command_state(virtual['leds'] if virtual else operator.get('leds_on'), bool(virtual)))
            virtual_jet = None
            if virtual:
                if virtual['mode'] == 'auto':
                    last_record = getattr(self.vision.engine, 'last_record', {})
                    virtual_jet = (virtual['connected'] and not virtual['emergency'] and
                                   bool(last_record.get('jet_permitted')) and
                                   not getattr(vision, 'person_detected', False))
                else:
                    virtual_jet = (virtual['connected'] and not virtual['emergency'] and virtual['water'] and
                                   virtual['pressure'] > .08 and
                                   not getattr(vision, 'person_detected', False))
            self._set_state('jet', *self._command_state(virtual_jet if virtual else telemetry.get(
                'jet_commanded',operator.get('jet_enable')),bool(virtual)))
            self._set_numeric('camera_select',virtual['camera_pan_deg'] if virtual else
                              telemetry.get('camera_pan_commanded'),'°')
            self._set_state('overlay', *self._state(virtual['overlay'] if virtual else
                                                  operator.get('overlay_visible')))
            for display_key, reading_key, valid_key, unit in (
                ('temp_int', 'temp_internal', 'sensor_internal_valid', ' °C'),
                ('hum_int', 'humidity_internal', 'sensor_internal_valid', ' %'),
                ('temp_ext', 'temp_external', 'sensor_external_valid', ' °C'),
                ('hum_ext', 'humidity_external', 'sensor_external_valid', ' %')):
                value = telemetry.get(reading_key) if telemetry.get(valid_key) else None
                self._set_numeric(display_key,value,unit)
            if not raw_stamp:
                reason = self.camera.last_error or f'Aguardando fonte {self.camera.source}'
                self.status.set('Vídeo indisponível: ' + str(reason))
            elif self.vision_session is None:
                self.status.set(self.vision_warning or 'Câmera ativa; modelos de visão indisponíveis.')
            elif self.simulation and not vision_recent:
                self.status.set('Câmera ativa; vídeo bruto exibido enquanto a inferência inicia.')
            elif self.simulation:
                self.status.set('Simulação local: Xbox e visão independentes dos atuadores físicos. '
                                + (self.vision_warning or virtual['hint']))
            elif linked and not self._matching_firmware():
                self.status.set('FIRMWARE DIFERENTE DO SETUP SELECIONADO: saídas bloqueadas. '
                                'Compile e grave a combinação mostrada no início do runtime.')
            elif linked and operator.get('requested_mode') == 'auto' and not \
                    blaze_runtime.camera_calibration_complete(self.config.vision.calibration):
                self.status.set('CALIBRAÇÃO PENDENTE: registre os 12 pontos no seletor inicial. '
                                'O jato automático permanece bloqueado.')
            elif linked:
                self.status.set('ESP32 conectado · controle e visão ativos conforme os intertravamentos')
            else:
                self.status.set('ESP32 desconectado ou telemetria desatualizada · '
                                'comandos bloqueados; rearme após reconexão · '
                                + (self.connection.last_error or 'verifique cabo, COM e alimentação'))
        except Exception as exc:
            self.status.set(f'Falha ao atualizar a central: {type(exc).__name__}: {exc}')
        finally:
            if not self._closing:
                self.root.after(100, self._tick)
