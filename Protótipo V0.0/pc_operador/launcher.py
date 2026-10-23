"""Seletor de uma combinação completa e preparação do firmware pelo runtime."""
from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime
import json
import math
import os
import shutil
import time

import cv2
from PIL import Image, ImageTk

import profile_manager


def diagnostic_link_state(running, link, stamp, started, now=None):
    """Estado visual derivado somente de uma conexão ativa e telemetria recente."""
    now=time.monotonic() if now is None else now
    age=now-stamp if stamp else float('inf')
    recent=bool(running and link and link.connected and
                age<getattr(link,'TELEMETRY_TIMEOUT_SECONDS',3.0))
    if recent:
        return 'Recebendo/ enviando',f'{link.active_transport.upper()} · último pacote há {age:.2f}s',True
    if not running:
        return 'Não enviando','Clique Conectar USB/Wi-Fi',False
    error=link.last_error if link else ''
    if stamp and age<5:
        detail=f'Último pacote há {age:.1f}s; {error or "reconectando"}'
    elif now-started<8:
        detail=f'Tentando {link.attempting if link and link.attempting else "encontrar o ESP32"}; saídas neutras'
    else:
        detail=(f'Tentando {link.attempting if link and link.attempting else "outro meio"}; '
                f'{error or "nenhuma telemetria válida"}; último pacote: '
                +(f'{age:.1f}s' if stamp else 'nunca'))
    if any(word in error for word in ('PermissionError','Access is denied','Acesso negado')):
        detail+=' · COM ocupada: encerre o teste serial/central do notebook antes de abrir outra janela.'
    return 'Enviando',detail,False


def open_camera_calibration(parent, config_path: Path, on_close,
                            transport_override: str = 'setup', usb_port: str = '',
                            camera_override: int | None = None) -> None:
    """Calibra câmera móvel e canhão com 12 correspondências físicas."""
    import runtime
    config = runtime.AppConfig(config_path)
    if transport_override != 'setup':
        config.data['esp']['transport'] = transport_override
        if transport_override == 'usb' and usb_port:
            config.data['esp']['serial_port'] = usb_port
    if camera_override is not None:
        config.data['vision']['camera_source'] = camera_override
        config.data['vision']['source_type'] = 'camera'
        config.data['camera']['source'] = camera_override
    source_type = str(config.data['vision'].get('source_type','')).lower()
    camera_source=config.data['vision'].get('camera_source',config.camera_source())
    if source_type == 'video' or (isinstance(camera_source,str) and
                                    runtime.local_path(camera_source).is_file()):
        raise ValueError('Calibração física exige câmera ao vivo, não vídeo gravado.')
    profile = config.data.get('_official', {}).get('profile')
    name = config.data.get('_official', {}).get('name', '')
    store_path = profile_manager.USER / 'camera_cannon_calibrations.json'
    collection = runtime.saved_camera_calibrations(name)
    selected_profile = collection['active']
    saved = collection['profiles'].get(selected_profile,{})
    def editable_points(record):
        result={str(a):dict(record.get('angles',{}).get(str(a),{})) for a in (0,90,180)}
        if int(record.get('schema_version',0)) < 5:
            # Os registros nos cantos inalcançáveis precisam de nova medida.
            for a, redo in ((0,('tl','bl')),(180,('tr','br'))):
                for corner in redo:result[str(a)].pop(corner,None)
        return result
    angles=editable_points(saved)
    dialog = tk.Toplevel(parent)
    dialog.title('BLAZE · Calibração da plataforma e da mira')
    dialog.geometry('1540x940')
    dialog.minsize(1220, 700)
    dialog.configure(bg='#122033')
    profile_label=tk.StringVar(master=dialog,value=selected_profile)
    profile_name=tk.StringVar(master=dialog,value=selected_profile)
    pan = tk.DoubleVar(master=dialog, value=90.)
    tilt = tk.DoubleVar(master=dialog, value=90.)
    camera_angle = tk.IntVar(master=dialog, value=90)
    status = tk.StringVar(master=dialog, value='Iniciando vídeo e comunicação com o ESP32...')
    command = {'camera_pan_deg': 90., 'calibration_pan': 90., 'calibration_tilt': 90.}
    telemetry = {'value': {}, 'stamp': 0.}
    lock = threading.Lock()
    changed_at = [time.monotonic()]
    photo = [None]
    running = [True]
    labels = {}
    installed = tk.BooleanVar(master=dialog,value=False)
    mounted={'value':False}
    installed.trace_add('write',lambda *_: mounted.update(value=installed.get()))
    original_limits=saved.get('angle_limits', {})
    limit_vars={}
    for axis in ('camera','pan','tilt'):
        pair=original_limits.get(axis, [0,180])
        if not isinstance(pair,(list,tuple)) or len(pair)!=2: pair=[0,180]
        limit_vars[axis]=(tk.DoubleVar(master=dialog,value=float(pair[0])),
                          tk.DoubleVar(master=dialog,value=float(pair[1])))
    def read_limits():
        limits={}
        for axis,(minimum,maximum) in limit_vars.items():
            a,b=minimum.get(),maximum.get()
            if not 0 <= a < b <= 180:
                raise ValueError(f'{axis}: informe mínimo < máximo entre 0° e 180°.')
            limits[axis]=[a,b]
        return limits
    try: limits_state=read_limits()
    except ValueError: limits_state={'camera':[0,180],'pan':[0,180],'tilt':[0,180]}
    def update_limit_state(*_):
        try: current=read_limits()
        except (ValueError, tk.TclError): return
        with lock: limits_state.update(current)
    for minimum,maximum in limit_vars.values():
        minimum.trace_add('write',update_limit_state)
        maximum.trace_add('write',update_limit_state)

    def get_command():
        with lock:
            state = dict(command)
            limits = dict(limits_state)
        reported = latest()
        signature = config.data.get('_official', {}).get('firmware_signature')
        matched = (profile == 'combate_real' and
                   reported.get('setup_signature') == signature and
                   runtime.protocol_compatible(reported) and
                   reported.get('servos_configured') and
                   reported.get('camera_servo_configured'))
        return runtime.control_message({
            'requested_mode': 'manual', 'stop': not (matched and mounted['value']), 'rearm': False,
            'calibrating': matched and mounted['value'], 'camera_pan_deg': state['camera_pan_deg'],
            'calibration_pan': state['calibration_pan'],
            'calibration_tilt': state['calibration_tilt'],
            **{axis+'_'+edge: limits[axis][index] for axis in limits
               for index,edge in enumerate(('min','max'))},
            'drive_x': 0, 'drive_y': 0, 'cannon_x': 0, 'cannon_y': 0,
            'water_on': False, 'jet_enable': False, 'cool_manual': False,
            'cool_internal': False, 'cool_external': False,
            'leds_on': False, 'pressure': 0, 'focus': 0,
        }, {'valid': False, 'target_valid': False, 'person_detected': False})

    def on_telemetry(packet):
        with lock:
            telemetry['value'] = dict(packet)
            telemetry['stamp'] = time.monotonic()

    def latest():
        with lock:
            if time.monotonic() - telemetry['stamp'] > 1.0:
                return {}
            return dict(telemetry['value'])

    cam_cfg = config.data['camera']
    camera = runtime.CameraSource(
        config.data['vision'].get('camera_source', config.camera_source()),
        float(cam_cfg['reconnect_seconds']), cam_cfg.get('mdns_name', ''),
        cam_cfg.get('stream_path', '/live'), cam_cfg.get('fallback_source', ''))
    esp = config.data['esp']
    link = runtime.ESPConnection(str(esp['host']), int(esp['port']), get_command,
        on_telemetry, float(esp['reconnect_seconds']), str(esp.get('transport','wifi_local')),
        str(esp.get('serial_port','auto')), int(esp.get('baudrate',460800)),
        str(config.data.get('_official',{}).get('firmware_signature','')),
        preserve_wifi=isinstance(camera.source, str) and
        camera.source.lower().startswith(('rtsp://','rtsps://','http://','https://')))

    navigation=tk.Frame(dialog,bg='#122033')
    navigation.pack(fill='x',padx=12,pady=(7,0))
    ttk.Button(navigation,text='← Voltar à primeira janela',
               command=lambda:close()).pack(side='right')
    heading = tk.Frame(dialog, bg='#122033')
    heading.pack(fill='x', padx=12, pady=8)
    tk.Label(heading, text='Calibração física: plataforma 0° / 90° / 180°',
             font=('Segoe UI', 16, 'bold'), bg='#122033', fg='white').pack(anchor='w')
    tk.Label(heading, text='Use o firmware de COMBATE REAL da mesma combinação. Monte e alimente os '
             'três servos, conecte o ESP32 e a câmera. Mova pan/tilt até a mira coincidir com '
             'cada marca no vídeo e confirme o ponto. Em 0°, as duas marcas esquerdas ficam '
             'na linha central; em 180°, as duas direitas também. '
             'Tração e válvulas permanecem bloqueadas. '
             'A telemetria informa ângulos comandados; valide o posicionamento físico.',
             bg='#122033', fg='#d6e8f6', wraplength=1250,
             justify='left').pack(anchor='w', pady=(5, 0))
    body = tk.Frame(dialog, bg='#122033')
    body.pack(fill='both', expand=True, padx=12)
    video = tk.Label(body, bg='#090e16', fg='white', text='Aguardando vídeo...')
    video.pack(side='left', fill='both', expand=True, padx=(0, 10))
    side_host = tk.Frame(body, bg='#1e3044', width=670)
    side_host.pack(side='right', fill='y')
    side_host.pack_propagate(False)
    side_canvas=tk.Canvas(side_host,bg='#1e3044',highlightthickness=0,width=645)
    side_scroll=ttk.Scrollbar(side_host,orient='vertical',command=side_canvas.yview)
    side_canvas.configure(yscrollcommand=side_scroll.set)
    side_scroll.pack(side='right',fill='y');side_canvas.pack(side='left',fill='both',expand=True)
    side=tk.Frame(side_canvas,bg='#1e3044')
    side_canvas.create_window((0,0),window=side,anchor='nw')
    side.bind('<Configure>',lambda _:side_canvas.configure(scrollregion=side_canvas.bbox('all')))
    side_canvas.bind('<MouseWheel>',lambda event:side_canvas.yview_scroll(-int(event.delta/120),'units'))
    tk.Checkbutton(side, text='Servos instalados, alimentados e eixos livres para percorrer as faixas',
                   variable=installed, bg='#1e3044', fg='white', selectcolor='#324e65',
                   activebackground='#1e3044').pack(anchor='w',padx=10,pady=4)
    tk.Label(side, text='1. Selecione a posição da plataforma', bg='#1e3044', fg='white',
             font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=10, pady=(9, 2))
    positions = tk.Frame(side, bg='#1e3044')
    positions.pack(fill='x', padx=10)
    def select_angle():
        with lock:
            command['camera_pan_deg'] = float(camera_angle.get())
        changed_at[0] = time.monotonic()
    for angle in (0, 90, 180):
        ttk.Radiobutton(positions, text=f'{angle}°', value=angle,
                        variable=camera_angle, command=select_angle).pack(side='left', padx=12)
    def update_servo(_=None):
        with lock:
            command['calibration_pan'] = pan.get()
            command['calibration_tilt'] = tilt.get()
        changed_at[0] = time.monotonic()
    limit_box=tk.LabelFrame(side,text='Limites angulares individuais (graus)',
                            bg='#1e3044',fg='white')
    limit_box.pack(fill='x',padx=8,pady=6)
    for axis,label in (('camera','Plataforma'),('pan','Canhão pan'),('tilt','Canhão tilt')):
        row=tk.Frame(limit_box,bg='#1e3044');row.pack(anchor='w',padx=8,pady=2)
        tk.Label(row,text=label,bg='#1e3044',fg='white',width=19,anchor='w').pack(side='left')
        for edge,variable in zip(('Mín.','Máx.'),limit_vars[axis]):
            tk.Label(row,text=edge,bg='#1e3044',fg='white').pack(side='left')
            tk.Spinbox(row,from_=0,to=180,increment=1,textvariable=variable,width=6).pack(side='left',padx=4)
    tk.Label(limit_box,text='Padrão 0–180° por eixo. Confirme mecanicamente a faixa do seu servo; '
             'o ângulo em telemetria é apenas o setpoint PWM.',bg='#1e3044',fg='#d6e8f6',
             wraplength=550,justify='left').pack(anchor='w',padx=8,pady=2)
    pulse_live=tk.StringVar(master=dialog,value='PWM canhão/plataforma: aguardando telemetria')
    tk.Label(limit_box,textvariable=pulse_live,bg='#1e3044',fg='#9ad3ff',
             font=('Consolas',9),wraplength=550,justify='left').pack(anchor='w',padx=8,pady=3)
    for title, var, lower, upper in (('2. Pan do canhão',pan,0,180),
                                     ('3. Tilt do canhão',tilt,0,180)):
        tk.Label(side, text=title, bg='#1e3044', fg='white').pack(anchor='w', padx=10, pady=(10, 0))
        tk.Scale(side, variable=var, from_=lower, to=upper, resolution=.5,
                 orient='horizontal', length=475, bg='#1e3044', fg='white',
                 highlightthickness=0, command=update_servo).pack(anchor='w', padx=10)

    def prerequisites():
        packet=latest()
        frame,stamp=camera.latest()
        return (profile=='combate_real' and installed.get() and link.connected and
                runtime.protocol_compatible(packet) and
                packet.get('setup_signature') == config.data['_official']['firmware_signature'] and
                packet.get('camera_servo_configured') and
                packet.get('servos_configured') and frame is not None and
                time.monotonic()-stamp < 1.)

    tk.Label(side, text='4. Confirme cada canto; a tabela possui 4 linhas × 13 campos '
             '(canto + 4 campos para cada ângulo).', bg='#1e3044', fg='#d6e8f6',
             wraplength=500, justify='left').pack(anchor='w', padx=10, pady=(12, 4))
    table = tk.Frame(side, bg='#1e3044')
    table.pack(padx=7)
    ttk.Label(table, text='Canto').grid(row=0, column=0)
    for column, angle in enumerate((0, 90, 180)):
        for offset, title in enumerate(('Pos.', 'Pan', 'Tilt', 'Registro')):
            ttk.Label(table, text=f'{angle}° {title}').grid(
                row=0, column=1+4*column+offset, padx=1)
    corners = (('tl','Sup. esq.'),('tr','Sup. dir.'),
               ('bl','Inf. esq.'),('br','Inf. dir.'))
    def point_label(angle, corner):
        vertical='Sup.' if corner in ('tl','tr') else 'Inf.'
        horizontal=('centro' if (angle==0 and corner in ('tl','bl')) or
                    (angle==180 and corner in ('tr','br')) else
                    'esq.' if corner in ('tl','bl') else 'dir.')
        return f'{vertical} {horizontal}'
    def refresh_cells():
        for (angle, corner), (pvar, tvar, button) in labels.items():
            value = angles[str(angle)].get(corner)
            pvar.set(f'{value[0]:.1f}' if value else '—')
            tvar.set(f'{value[1]:.1f}' if value else '—')
            button.configure(text='Registrado' if value else 'Confirmar')

    def confirm(angle, corner):
        if not prerequisites():
            status.set('Confirme a montagem, câmera ao vivo e firmware correspondente antes dos 12 pontos.')
            return
        if profile != 'combate_real':
            status.set('Este setup é de simulação. Selecione uma combinação de combate real para calibrar servos físicos.')
            return
        if camera_angle.get() != angle:
            status.set(f'Selecione primeiro a plataforma em {angle}°.')
            return
        packet = latest()
        frame, stamp = camera.latest()
        if not link.connected or not packet:
            status.set('ESP32 sem telemetria recente. Confira USB/Wi-Fi e o firmware.')
            return
        if packet.get('setup_signature') != config.data['_official']['firmware_signature']:
            status.set('Firmware diferente: grave a combinação selecionada antes de calibrar.')
            return
        if not packet.get('camera_servo_configured') or not packet.get('servos_configured'):
            status.set('Firmware sem saídas de servo habilitadas. Use o perfil de combate real.')
            return
        if frame is None or not stamp:
            status.set('A câmera ainda não entregou um quadro recente.')
            return
        if time.monotonic() - changed_at[0] < .6:
            status.set('Aguarde pelo menos 0,6 s após mover um slider ou a plataforma.')
            return
        for key, target in (('camera_pan_commanded', angle),
                            ('servo_pan_commanded',pan.get()),
                            ('servo_tilt_commanded',tilt.get())):
            if abs(float(packet.get(key, -999))-target)>1.1:
                status.set(f'Aguardando telemetria de {key} alcançar {target:.1f}°.')
                return
        angles[str(angle)][corner]=[round(pan.get(),2),round(tilt.get(),2)]
        refresh_cells()
        status.set(f'{point_label(angle,corner)} em {angle}° registrado. Confirme os 12 pontos e salve.')

    for row, (corner, title) in enumerate(corners, start=1):
        ttk.Label(table, text=title).grid(row=row, column=0, padx=2, pady=4, sticky='w')
        for group, angle in enumerate((0, 90, 180)):
            base = 1+group*4
            ttk.Label(table, text=point_label(angle,corner)).grid(row=row, column=base)
            pvar=tk.StringVar(master=dialog)
            tvar=tk.StringVar(master=dialog)
            ttk.Label(table, textvariable=pvar, width=5).grid(row=row, column=base+1)
            ttk.Label(table, textvariable=tvar, width=5).grid(row=row, column=base+2)
            button=ttk.Button(table, text='Confirmar', width=10,
                              command=lambda a=angle,c=corner: confirm(a,c))
            button.grid(row=row, column=base+3, padx=2)
            labels[(angle,corner)]=(pvar,tvar,button)
    refresh_cells()

    def save():
        if not prerequisites():
            status.set('Calibração requer câmera real, firmware correspondente e três servos instalados.')
            return
        try: limits=read_limits()
        except ValueError as exc:
            status.set(str(exc));return
        entry={'schema_version':5,'enabled':True,'angles':angles,
               'angle_limits':limits,
               'frame_size':list(last_shape[0]),'recorded_at':time.strftime('%Y-%m-%dT%H:%M:%S')}
        if not runtime.camera_calibration_complete(entry):
            status.set('Faltam pontos: confirme os 12 alvos, inclusive os quatro centrais dos extremos.')
            return
        label=profile_name.get().strip()
        if not label or len(label)>80 or any(char in label for char in '\\/:*?"<>|'):
            status.set('Informe um nome de calibração com até 80 caracteres, sem \\/:*?"<>|.');return
        records=runtime.read_json(store_path)
        group=runtime.calibration_collection(records.get(name,{}))
        previous=group['profiles'].get(label,{})
        group['profiles'][label]=entry
        group['active']=label
        records[name]=group
        store_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=store_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,store_path)
        profile_label.set(label)
        profile_options['values']=sorted(group['profiles'])
        status.set(f'Calibração “{label}” salva e selecionada. Feche a janela e abra a central.')

    last_shape=[(0,0)]
    footer=tk.Frame(dialog,bg='#122033')
    footer.pack(fill='x',padx=12,pady=7)
    profile_row=tk.Frame(side,bg='#1e3044');profile_row.pack(fill='x',padx=10,pady=6)
    tk.Label(profile_row,text='Calibrações desta combinação:',bg='#1e3044',fg='white').pack(side='left')
    profile_options=ttk.Combobox(profile_row,textvariable=profile_label,state='readonly',width=23,
                                  values=sorted(collection['profiles']))
    profile_options.pack(side='left',padx=4)
    def load_profile(_=None):
        nonlocal saved
        label=profile_label.get()
        group=runtime.saved_camera_calibrations(name)
        if label not in group['profiles']:return
        saved=group['profiles'][label]
        angles.clear()
        angles.update(editable_points(saved))
        limits=saved.get('angle_limits',{})
        for axis,pair in limit_vars.items():
            values=limits.get(axis,[0,180])
            pair[0].set(values[0]);pair[1].set(values[1])
        profile_name.set(label)
        refresh_cells()
        status.set(f'Carregada “{label}”. Use Salvar para defini-la como ativa no runtime.')
    profile_options.bind('<<ComboboxSelected>>',load_profile)
    tk.Label(profile_row,text='Nome para salvar:',bg='#1e3044',fg='white').pack(side='left',padx=(8,2))
    ttk.Entry(profile_row,textvariable=profile_name,width=26).pack(side='left')
    def delete_profile():
        label=profile_label.get()
        records=runtime.read_json(store_path)
        group=runtime.calibration_collection(records.get(name,{}))
        if label not in group['profiles']:
            status.set('Selecione uma calibração salva para excluir.');return
        group['profiles'].pop(label)
        group['active']=next(iter(sorted(group['profiles'])),'')
        records[name]=group
        store_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=store_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,store_path)
        profile_options['values']=sorted(group['profiles'])
        profile_label.set(group['active'])
        if group['active']:load_profile()
        else:profile_name.set('')
        status.set(f'Calibração “{label}” excluída. A seleção ativa foi atualizada.')
    ttk.Button(profile_row,text='Excluir selecionada',command=delete_profile).pack(side='left',padx=5)
    ttk.Button(footer,text='Salvar calibração nomeada (12 pontos)',command=save).pack(side='left')
    ttk.Button(footer,text='Voltar à primeira janela',command=lambda:close()).pack(side='left',padx=8)
    tk.Label(footer,textvariable=status,bg='#122033',fg='#ffdfa4',
             wraplength=1000,justify='left').pack(side='left',padx=14)

    def tick():
        if not running[0]:return
        frame, stamp = camera.latest()
        packet = latest()
        if packet:
            pulse_live.set('PWM comandado (não é posição medida): '+
                ' / '.join(f'{axis} {float(packet[key]):.0f} µs'
                         for axis,key in (('pan','servo_pan_pulse_us'),
                                          ('tilt','servo_tilt_pulse_us'),
                                          ('plataforma','camera_pan_pulse_us'))
                         if packet.get(key) is not None))
        if frame is not None:
            height,width=frame.shape[:2]
            last_shape[0]=(width,height)
            view=frame.copy()
            angle=camera_angle.get()
            for corner in ('tl','tr','bl','br'):
                u,v=runtime.calibration_marker(corner,angle)
                x=12 if u==0 else width-13 if u==1 else width//2
                y=20 if v==0 else height-20
                color=(40,200,50) if corner in angles[str(angle)] else (30,30,240)
                cv2.circle(view,(x,y),8,color,-1,cv2.LINE_AA)
                cv2.putText(view,corner.upper(),(max(0,x-12),y+24 if v==0 else y-13),
                            cv2.FONT_HERSHEY_SIMPLEX,.5,color,1,cv2.LINE_AA)
            screen_w=max(480,video.winfo_width()-10)
            screen_h=max(320,video.winfo_height()-10)
            ratio=min(screen_w/width,screen_h/height)
            shown=cv2.resize(view,(max(1,int(width*ratio)),max(1,int(height*ratio))))
            photo[0]=ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown,cv2.COLOR_BGR2RGB)),master=dialog)
            video.configure(image=photo[0],text='')
        elif not stamp:
            video.configure(image='',text='Aguardando câmera: '+str(camera.last_error or runtime.redacted_source(camera.source)))
        if profile != 'combate_real':
            status.set('Prévia de simulação: escolha uma combinação de combate real para registrar os 12 pontos físicos.')
        elif not packet:
            status.set('Aguardando telemetria do ESP32. Verifique cabo/Wi-Fi, porta e firmware.')
        elif (packet.get('setup_signature') != config.data['_official']['firmware_signature']
              or not runtime.protocol_compatible(packet)):
            status.set('Firmware diferente ou antigo: compile e grave novamente este perfil.')
        if running[0]:dialog.after(120,tick)

    def close():
        if not running[0]:
            return
        running[0]=False
        try:
            link.stop()
            camera.stop()
        finally:
            try:
                dialog.destroy()
            finally:
                on_close()
    dialog.protocol('WM_DELETE_WINDOW',close)
    camera.start()
    link.start()
    dialog.after(120,tick)


def run(profile: str) -> None:
    """Seleção de setup, diagnóstico vivo e firmware antes da central."""
    if profile not in ('simulacao', 'combate_real'):
        raise ValueError(profile)
    import runtime
    root=tk.Tk()
    root.title('BLAZE · '+('Simulação' if profile=='simulacao' else 'Combate real'))
    screen_width,screen_height=root.winfo_screenwidth(),root.winfo_screenheight()
    root.geometry(f'{min(1460,screen_width-30)}x{min(900,screen_height-90)}')
    root.minsize(min(1000,screen_width-30),min(540,screen_height-90))
    root.configure(bg='#122033')
    message=tk.StringVar(master=root,value='Selecionando combinação completa...')
    name=tk.StringVar(master=root);choice_label=tk.StringVar(master=root)
    port=tk.StringVar(master=root);port_label=tk.StringVar(master=root)
    port_labels={}
    combination_labels={}
    version_result=tk.StringVar(master=root,value='Versão gravada: clique Verificar versão após conectar.')
    version_pending={'started':0.}
    events=queue.Queue();busy={'value':False}
    diagnostic={'link':None,'camera':None,'packet':{},'stamp':0.,'config':None,
                'running':False,'started':0.,'epoch':0,'lock':threading.Lock()}
    builds=[]
    footer=tk.Frame(root,bg='#122033')
    footer.pack(side='bottom',fill='x',padx=16,pady=(4,8))
    viewport=tk.Frame(root,bg='#122033')
    viewport.pack(side='top',fill='both',expand=True,padx=16,pady=(8,0))
    scroll=tk.Scrollbar(viewport,orient='vertical')
    scroll.pack(side='right',fill='y')
    canvas=tk.Canvas(viewport,bg='#122033',highlightthickness=0,
                     yscrollcommand=scroll.set)
    canvas.pack(side='left',fill='both',expand=True)
    scroll.configure(command=canvas.yview)
    panel=tk.Frame(canvas,bg='#122033')
    panel_id=canvas.create_window((0,0),window=panel,anchor='nw')
    panel.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda event:canvas.itemconfigure(panel_id,width=event.width))
    tk.Label(panel,text='BLAZE · '+('SIMULAÇÃO' if profile=='simulacao' else 'COMBATE REAL'),
             bg='#122033',fg='white',font=('Segoe UI',17,'bold')).pack(anchor='w')
    tk.Label(panel,text='Escolha a combinação e o meio USB ou Wi-Fi. Clique Conectar para conferir '
             'versão e componentes. Na central, segure Start por 2 s para iniciar a comunicação; '
             'seta para baixo por 1 s solicita parada ou rearme.',
             bg='#122033',fg='#c3d8e8',wraplength=1090,justify='left').pack(anchor='w',pady=(2,8))
    selection=tk.Frame(panel,bg='#122033');selection.pack(fill='x',pady=3)
    tk.Label(selection,text='Combinação completa:',bg='#122033',fg='white').pack(side='left')
    choice=ttk.Combobox(selection,textvariable=choice_label,state='readonly',width=75)
    choice.pack(side='left',padx=8,fill='x',expand=True)
    ttk.Button(selection,text='Atualizar setups/portas',command=lambda: refresh()).pack(side='left')
    def import_previous():
        old=filedialog.askdirectory(parent=root,title='Escolha a pasta BLAZE da instalação anterior')
        if not old:return
        try:
            source=Path(old)
            if (source/'pc_operador').is_dir():source=source/'pc_operador'
            prior=source/'parameters_setups'
            if not (prior/'user'/'combinations.json').is_file():
                raise ValueError('Escolha a pasta que contém pc_operador/parameters_setups/user/combinations.json.')
            if profile_manager.names() or any(profile_manager._read(profile_manager.USER/f'{key}.json')
                                              for key in ('connection','vision','control','hardware')
                                              if (profile_manager.USER/f'{key}.json').is_file()):
                raise ValueError('Esta instalação já contém setups; preserve os JSON atuais antes de importar.')
            paths=[]
            for section in ('connection','vision','control','hardware','combinations','camera_cannon_calibrations'):
                path=prior/'user'/f'{section}.json'
                if path.is_file():
                    if not isinstance(json.loads(path.read_text(encoding='utf-8')),dict):
                        raise ValueError(f'JSON inválido: {path}')
                    paths.append(path)
            profile_manager.USER.mkdir(parents=True,exist_ok=True)
            for path in paths:shutil.copy2(path,profile_manager.USER/path.name)
            active=prior/'official'/'active.json'
            if active.is_file():
                target=profile_manager.PC/'parameters_setups'/'official'/'active.json'
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(active,target)
            refresh()
            message.set('Setups importados: '+', '.join(p.stem for p in paths)+'. Confira caminhos dos modelos/vídeos; '
                        'compile e grave este firmware antes de usar a rede Wi-Fi da nova instalação.')
        except (OSError, ValueError, KeyError) as exc:
            message.set('Importação: '+str(exc))
    ttk.Button(selection,text='Importar setups anteriores',command=lambda: import_previous()).pack(side='left',padx=(6,0))
    upper=tk.Frame(panel,bg='#122033');upper.pack(fill='x',pady=5)
    transport_override=tk.StringVar(master=root,value='Conforme setup')
    camera_choice=tk.StringVar(master=root,value='Conforme setup')
    camera_default={'label':'Conforme setup'}
    tk.Label(upper,text='Comunicação nesta execução:',bg='#122033',fg='white').pack(side='left')
    transport_options=ttk.Combobox(upper,textvariable=transport_override,state='readonly',width=20,
                                   values=('Conforme setup','USB','Wi-Fi local'))
    transport_options.pack(side='left',padx=6)
    local_network=tk.StringVar(master=root,value='Rede local: será gerada ao preparar o firmware.')
    local_guide=tk.LabelFrame(panel,text='Conexão local do ESP32 por Wi-Fi',bg='#1e3044',fg='white')
    local_guide.pack(fill='x',pady=4)
    tk.Label(local_guide,textvariable=local_network,bg='#1e3044',fg='#a8dfc3',
             wraplength=1320,justify='left').pack(anchor='w',padx=8,pady=3)
    tk.Label(local_guide,text='1. Grave o firmware desta combinação por USB.  2. No Wi-Fi do Windows, escolha o SSID abaixo e informe a senha; '
             'a central usa a mesma rede.  3. Selecione Wi-Fi local no setup ou nesta janela.  '
             '4. Clique Conectar e Verificar versão. Feche testes seriais do notebook antes de usar USB.',
             bg='#1e3044',fg='#d6e8f6',wraplength=1320,justify='left').pack(anchor='w',padx=8,pady=(0,4))
    local_secret={'password':''}
    def copy_password():
        if not local_secret['password']:
            message.set('Prepare o firmware para gerar a senha da rede local.');return
        root.clipboard_clear();root.clipboard_append(local_secret['password'])
        message.set('Senha da rede local copiada para a área de transferência.')
    ttk.Button(local_guide,text='Copiar senha Wi-Fi',command=copy_password).pack(anchor='w',padx=8,pady=(0,5))
    tk.Label(upper,text='Porta COM para upload:',bg='#122033',fg='white').pack(side='left')
    ports=ttk.Combobox(upper,textvariable=port_label,width=38,state='readonly');ports.pack(side='left',padx=6)
    video_row=tk.Frame(panel,bg='#122033');video_row.pack(fill='x',pady=3)
    tk.Label(video_row,text='Vídeo nesta execução:',bg='#122033',fg='white').pack(side='left')
    camera_select=ttk.Combobox(video_row,textvariable=camera_choice,state='readonly',width=54)
    camera_select.pack(side='left',padx=8)
    tk.Label(video_row,text='Escolha USB 0–5 ou a fonte do setup. A linha “Fonte de vídeo” testa os quadros; '
             'a central usa a mesma escolha.',bg='#122033',fg='#c3d8e8',
             wraplength=750,justify='left').pack(side='left',fill='x',expand=True)
    calibration_row=tk.Frame(panel,bg='#122033');calibration_row.pack(fill='x',pady=3)
    tk.Label(calibration_row,text='Calibração da mira:',bg='#122033',fg='white').pack(side='left')
    calibration_choice=tk.StringVar(master=root)
    calibration_select=ttk.Combobox(calibration_row,textvariable=calibration_choice,
                                    state='readonly',width=38)
    calibration_select.pack(side='left',padx=8)
    tk.Label(calibration_row,text='Escolha uma calibração salva da combinação. “Aproximada” '
             'usa limites provisórios; o jato automático exige os 12 pontos físicos.',
             bg='#122033',fg='#c3d8e8',wraplength=850,justify='left').pack(side='left')
    def refresh_calibration_options():
        group=runtime.saved_camera_calibrations(name.get()) if name.get() else {'active':'','profiles':{}}
        options=['Aproximada (sem calibração)']+sorted(group['profiles'])
        calibration_select['values']=options
        calibration_choice.set(group['active'] or options[0])
    def calibration_changed(_=None):
        if not name.get():return
        records=runtime.read_json(profile_manager.USER/'camera_cannon_calibrations.json')
        group=runtime.calibration_collection(records.get(name.get(),{}))
        chosen=calibration_choice.get()
        group['active']=chosen if chosen in group['profiles'] else ''
        records[name.get()]=group
        path=profile_manager.USER/'camera_cannon_calibrations.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,path)
        stop_diagnostic()
        message.set('Calibração selecionada: '+(group['active'] or 'mapa aproximado')+'. Reconecte para conferir.')
    calibration_select.bind('<<ComboboxSelected>>',calibration_changed)
    def selected_camera_override():
        value=camera_choice.get()
        return int(value.split(' · ',1)[0][4:]) if value.startswith('USB ') else None
    def apply_transport(config):
        override={'USB':'usb','Wi-Fi local':'wifi_local'}.get(transport_override.get())
        if override:
            config.data['esp']['transport']=override
            if override=='usb' and port.get():config.data['esp']['serial_port']=port.get()
        camera_override=selected_camera_override()
        if camera_override is not None:
            config.runtime_camera_override=camera_override
            config.data['vision']['camera_source']=camera_override
            config.data['vision']['source_type']='camera'
            config.data['camera']['source']=camera_override
        return config
    def selected():
        if not name.get():raise ValueError('Selecione uma combinação completa.')
        return profile_manager.prepare(name.get(),profile)
    def stop_diagnostic():
        diagnostic['epoch']+=1
        diagnostic['running']=False
        camera,link=diagnostic['camera'],diagnostic['link']
        diagnostic['camera']=diagnostic['link']=None
        diagnostic['config']=None
        if link:link.stop()
        if camera:camera.stop()
        with diagnostic['lock']:
            diagnostic['packet']={};diagnostic['stamp']=0.
        connection_button.configure(text='Conectar USB/Wi-Fi')
        return camera
    def start_diagnostic():
        if diagnostic['running'] or busy['value']:return
        try:
            config=apply_transport(runtime.AppConfig(selected()[0]))
            diagnostic['config']=config
            source=config.data['vision'].get('camera_source',config.camera_source())
            c=config.data['camera'];e=config.data['esp']
            # A janela inicial não reproduz vídeo gravado: leitura contínua
            # concorreria com a telemetria sem mostrar prévia ao operador.
            camera=None if config.data['vision'].get('source_type')=='video' else runtime.CameraSource(
                source,float(c['reconnect_seconds']),c.get('mdns_name',''),
                c.get('stream_path','/live'),c.get('fallback_source',''))
            def telemetry(packet):
                with diagnostic['lock']:
                    diagnostic['packet']=dict(packet);diagnostic['stamp']=time.monotonic()
            def neutral():
                return runtime.control_message({'stop':True,'requested_mode':'manual',
                       'camera_pan_deg':90.,'cannon_rate_deg_s':90.},
                       {'valid':False,'target_valid':False,'person_detected':False})
            link=runtime.ESPConnection(str(e['host']),int(e['port']),neutral,telemetry,
                float(e['reconnect_seconds']),str(e.get('transport','wifi_local')),
                str(e.get('serial_port','auto')),int(e.get('baudrate',460800)),
                str(config.data.get('_official',{}).get('firmware_signature','')))
            diagnostic.update(link=link,camera=camera,running=True,started=time.monotonic())
            if camera:camera.start()
            link.start()
            connection_button.configure(text='Desconectar USB/Wi-Fi')
            message.set('Conexão de diagnóstico iniciada; verificando telemetria e quadros.')
        except Exception as exc:
            message.set(f'Diagnóstico: {type(exc).__name__}: {exc}')
    def toggle_diagnostic():
        if diagnostic['running']:
            stop_diagnostic();message.set('Comunicação de diagnóstico interrompida pelo operador.')
        else:start_diagnostic()
    connection_button=ttk.Button(upper,text='Conectar USB/Wi-Fi',command=toggle_diagnostic)
    connection_button.pack(side='left',padx=8)
    def transport_changed(_=None):
        if busy['value']:return
        stop_diagnostic()
    transport_options.bind('<<ComboboxSelected>>',transport_changed)
    def port_changed(_=None):
        port.set(port_labels.get(port_label.get(),''))
        if transport_override.get()=='USB':transport_changed()
    ports.bind('<<ComboboxSelected>>',port_changed)
    def camera_changed(_=None):
        if not diagnostic['config'] or not diagnostic['running']:return
        try:
            config=apply_transport(runtime.AppConfig(selected()[0]))
        except Exception as exc:
            message.set(f'Fonte de vídeo: {type(exc).__name__}: {exc}')
            return
        previous=diagnostic['camera']
        diagnostic['camera']=None
        diagnostic['config']=config
        if previous:previous.stop()
        def restart_camera():
            if not diagnostic['running'] or diagnostic['config'] is not config:return
            if previous and previous._thread and previous._thread.is_alive():
                root.after(150,restart_camera);return
            source=config.data['vision'].get('camera_source',config.camera_source())
            if config.data['vision'].get('source_type')=='video':
                message.set('Fonte do setup: vídeo salvo. A central abrirá o arquivo selecionado.')
                return
            c=config.data['camera']
            camera=runtime.CameraSource(source,float(c['reconnect_seconds']),
                c.get('mdns_name',''),c.get('stream_path','/live'),c.get('fallback_source',''))
            diagnostic['camera']=camera
            camera.start()
            message.set(f'Testando câmera USB {source}; veja “Fonte de vídeo” na lista.')
        restart_camera()
    camera_select.bind('<<ComboboxSelected>>',camera_changed)
    version_area=tk.Frame(panel,bg='#122033');version_area.pack(fill='x',pady=4)
    ttk.Button(version_area,text='Verificar versão no ESP32',
               command=lambda:show_firmware()).pack(anchor='w')
    tk.Label(version_area,textvariable=version_result,bg='#122033',fg='#a8dfc3',
             wraplength=1200,justify='left').pack(anchor='w',pady=3)
    state_box=tk.LabelFrame(panel,text='Recebimento e requisitos em tempo real',bg='#1e3044',fg='white')
    state_box.pack(fill='x',pady=5)
    checks=ttk.Treeview(state_box,columns=('item','model','port','state','detail'),show='headings',height=13)
    for key,title,width in [('item','Componente',200),('model','Modelo selecionado',220),
                            ('port','Porta / GPIO / interface',220),('state','Estado',185),
                            ('detail','Leitura / requisito',500)]:
        checks.heading(key,text=title);checks.column(key,width=width,anchor='w',stretch=key=='detail')
    checks.tag_configure('connected',foreground='#116b35',background='#e0f4e7')
    checks.tag_configure('waiting',foreground='#a42432',background='#ffe8ea')
    checks.tag_configure('output',foreground='#15568b',background='#eaf3fb')
    checks.tag_configure('neutral',foreground='#253a50',background='#f0f4f8')
    check_scroll=ttk.Scrollbar(state_box,orient='vertical',command=checks.yview)
    checks.configure(yscrollcommand=check_scroll.set)
    check_scroll.pack(side='right',fill='y',pady=5)
    checks.pack(side='left',fill='both',expand=True,padx=6,pady=5)
    components=['Comunicação ESP32','Versão do firmware','Fonte de vídeo','Controle Xbox',
                 'Servo canhão · Pan','Servo canhão · Tilt',
                 'Servo câmera','Microservo foco',
                'DHT interno','DHT externo','Driver esquerdo','Driver direito',
                'Motor esquerdo','Motor direito','Relé · arrefecimento interno',
                'Relé · arrefecimento externo','Válvula do jato','LEDs']
    for item in components:checks.insert('', 'end',iid=item,values=(item,'—','—','Não enviando','—'),tags=('neutral',))
    actions=tk.Frame(footer,bg='#122033');actions.pack(fill='x',pady=3)
    buttons=[]
    def set_busy(flag):
        busy['value']=flag
        for button in buttons:button.configure(state='disabled' if flag else 'normal')
    def show_firmware():
        if not diagnostic['running']:
            version_pending['started']=time.monotonic()
            version_result.set('Conectando ao ESP32 para ler a versão gravada...')
            start_diagnostic()
        with diagnostic['lock']:
            packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
        if (not diagnostic['link'] or not diagnostic['link'].connected or
                time.monotonic()-stamp>diagnostic['link'].TELEMETRY_TIMEOUT_SECONDS):
            if version_pending['started'] and time.monotonic()-version_pending['started'] < 8:
                root.after(200,show_firmware)
            else:
                version_pending['started']=0.
                version_result.set('Sem telemetria recente: confira USB/Wi-Fi e alimentação.')
            return
        version_pending['started']=0.
        expected=diagnostic['config'].data.get('_official',{}).get('firmware_signature','')
        sig=packet.get('setup_signature','')
        protocol_ok=runtime.protocol_compatible(packet)
        version=(packet.get('setup_name') or
                 (diagnostic['config'].data.get('_official',{}).get('name','')+
                  ' (identificado pela assinatura; aguardando pacote completo)'
                  if sig and sig==expected else 'desconhecido'))
        compiled=next((b for b in builds if b['name']==name.get()),None)
        compiled_detail=(f" · compilado neste PC: {compiled['built_at'][:19].replace('T',' ')} UTC"
                         +(' (versão antiga: recompilar)' if compiled['signature'][:16]!=expected else '')
                         if compiled else ' · sem compilação local deste setup')
        version_result.set(f'ESP32 gravado: {version} · assinatura {sig or "ausente"} · '
                    +('corresponde ao setup selecionado'
                      if sig==expected and protocol_ok else 'DIFERENTE ou protocolo antigo: regrave')
                    +f' · protocolo {packet.get("protocol_version","antigo")}'
                    +compiled_detail)
    def refresh_builds():
        nonlocal builds
        builds=profile_manager.available_firmware(profile)
        current=next((b for b in builds if b['name']==name.get()),None)
        if current and not diagnostic['running']:
            try: expected=selected()[1]['_official']['firmware_signature']
            except (ValueError,KeyError,OSError): expected=''
            version_result.set(f"Compilado: {current['name']} · {current['built_at'][:19].replace('T',' ')} UTC. "
                               +( 'Versão antiga; compile antes de gravar. '
                                  if current['signature'][:16]!=expected else '' )+
                               "Conecte e clique Verificar versão para ler o que está gravado.")

    def refresh_camera_options():
        if not name.get():return
        chosen=profile_manager.assemble(name.get())['vision']
        source=chosen.get('camera_source',0)
        label=('vídeo salvo: '+Path(str(source)).name if chosen.get('source_type')=='video'
               else 'USB '+str(source))
        camera_default['label']='Conforme setup · '+label
        camera_select['values']=[camera_default['label']]+[
            f'USB {i} · câmera local' for i in range(6)]
        if not camera_choice.get().startswith('USB '):
            camera_choice.set(camera_default['label'])
    def refresh():
        try:
            local=profile_manager.local_link_credentials(create=False)
            local_secret['password']=local[1] if local else ''
            local_network.set((f'SSID: {local[0]}  ·  Senha: {local[1]}  ·  Endereço: 192.168.4.1:8765  ·  '
                               'Esses dados pertencem a esta instalação; grave o firmware gerado aqui para usá-los.')
                              if local else 'Rede local: senha exclusiva criada ao preparar o firmware; grave o novo firmware no ESP32.')
            available=profile_manager.names(profile)
            combos_path=profile_manager.USER/'combinations.json'
            records=profile_manager._read(combos_path) if combos_path.is_file() else {}
            combination_labels.clear()
            for raw in available:
                saved=records.get(raw,{}).get('saved_at')
                try:
                    when=datetime.fromisoformat(saved).astimezone().strftime('%d/%m/%Y %H:%M:%S') if saved else 'data não registrada (legado)'
                except (ValueError,TypeError):when='data inválida'
                combination_labels[f'{raw}  ·  {when}']=raw
            choice['values']=list(combination_labels)
            official_path=profile_manager.ROOT/'pc_operador/parameters_setups/official/active.json'
            official=profile_manager._read(official_path) if official_path.is_file() else {}
            preferred=official.get('_official',{}).get('name','')
            if name.get() not in available:name.set(preferred if preferred in available else available[0] if available else '')
            choice_label.set(next((label for label,raw in combination_labels.items() if raw==name.get()),''))
            refresh_camera_options()
            refresh_calibration_options()
            from serial.tools import list_ports
            discovered=list(list_ports.comports())
            port_labels.clear()
            for entry in discovered:
                description=(entry.description or entry.manufacturer or 'Dispositivo serial').strip()
                port_labels[f'{entry.device} · {description}']=entry.device
            found=[entry.device for entry in discovered]
            ports['values']=list(port_labels)
            preferred=[p for p in runtime.serial_candidates('auto') if p in found]
            if port.get() not in found:port.set((preferred or found or [''])[0])
            port_label.set(next((label for label,device in port_labels.items()
                                 if device==port.get()),''))
            refresh_builds()
            if not available:message.set('Sem combinação deste perfil. Salve uma na seção 6 do notebook ou use Importar setups anteriores.')
        except Exception as exc:message.set(f'Atualização: {type(exc).__name__}: {exc}')
    def selection_changed(_=None):
        if busy['value']:return
        selected_name=combination_labels.get(choice_label.get())
        if not selected_name:return
        name.set(selected_name)
        camera_choice.set('Conforme setup')
        stop_diagnostic();refresh_camera_options();refresh_calibration_options();refresh_builds()
    choice.bind('<<ComboboxSelected>>',selection_changed)
    def start():
        if busy['value']:return
        try:config_path,_=selected()
        except Exception as exc:message.set(str(exc));return
        set_busy(True);previous_camera=stop_diagnostic()
        message.set('Abrindo central e carregando modelos de visão...')
        waiting_since=time.monotonic()
        def open_central():
            try:
                if previous_camera and previous_camera._thread and previous_camera._thread.is_alive():
                    if time.monotonic()-waiting_since > 8:
                        raise RuntimeError('A prévia ainda usa a câmera. Feche outras prévias e tente novamente.')
                    message.set('Aguardando a prévia liberar a câmera USB...')
                    root.after(150,open_central)
                    return
                import central_operador
                config=apply_transport(runtime.AppConfig(config_path))
                central_operador.configure(config)
                app=central_operador.CentralOperador(config)
                central_operador.attach_controller(app)
                root.destroy();app.run()
                if app.return_to_launcher:
                    run(profile)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                try:
                    if root.winfo_exists():
                        message.set(f'Central: {type(exc).__name__}: {exc}')
                        set_busy(False)
                    else:
                        messagebox.showerror('Central do operador',f'{type(exc).__name__}: {exc}')
                except tk.TclError:
                    print(f'Central: {type(exc).__name__}: {exc}')
        root.after(70,open_central)
    def calibrate():
        if busy['value']:return
        try:
            path,data=selected()
            if profile!='combate_real' or (data['vision'].get('source_type')=='video'
                                           and selected_camera_override() is None):
                raise ValueError('Requer perfil de combate real e câmera ao vivo, não arquivo de vídeo.')
            config=diagnostic['config']
            with diagnostic['lock']:
                packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
            frame,frame_stamp=diagnostic['camera'].latest() if diagnostic['camera'] else (None,0)
            if not diagnostic['running'] or time.monotonic()-stamp>3.5 or frame is None or not frame_stamp:
                raise ValueError('Aguarde câmera ao vivo e telemetria recentes do ESP32.')
            if (packet.get('setup_signature')!=data['_official']['firmware_signature']
                    or not runtime.protocol_compatible(packet)):
                raise ValueError('Firmware diferente ou anterior à versão 4: compile e grave novamente.')
            if not packet.get('servos_configured') or not packet.get('camera_servo_configured'):
                raise ValueError('Aguarde telemetria completa que confirme os três canais dos servos; '
                                 'se persistir, confira se a saída física está habilitada.')
            set_busy(True);stop_diagnostic()
            def completed():
                set_busy(False)
                try:
                    if root.winfo_exists():
                        root.deiconify()
                        root.lift()
                        refresh_calibration_options()
                        message.set('Calibração encerrada; reconectando câmera e ESP32...')
                        # A porta serial e a câmera precisam terminar de fechar
                        # antes que o diagnóstico reabra os mesmos dispositivos.
                        root.after(1200,start_diagnostic)
                except tk.TclError:
                    pass
            mode={'USB':'usb','Wi-Fi local':'wifi_local'}.get(
                transport_override.get(),'setup')
            open_camera_calibration(root,path,completed,mode,port.get(),selected_camera_override())
        except Exception as exc:
            set_busy(False);message.set(f'Calibração bloqueada: {exc}')
    def operation(upload=False):
        if busy['value']:return
        try:
            _,data=selected();chosen=data['_official']['name']
            build=None
            if upload:
                build=next((b for b in builds if b['name']==chosen and
                            b['signature'][:16]==data['_official']['firmware_signature']),None)
                if build is None:
                    raise ValueError('Compile o firmware atualizado desta combinação antes de gravar por USB.')
                if not port.get():raise ValueError('Selecione a porta COM do ESP32.')
        except Exception as exc:message.set(f'Operação bloqueada: {exc}');return
        chosen_port=port.get()
        set_busy(True);stop_diagnostic()
        message.set(('Gravando '+chosen+' em '+chosen_port) if upload else ('Compilando '+chosen))
        def worker():
            try:
                binary=(profile_manager.upload_compiled_firmware(build,chosen_port,
                         lambda line:events.put(('line',line))) if upload else
                        profile_manager.run_pio(chosen,False,'',lambda line:events.put(('line',line))))
                events.put(('done',f'Firmware {chosen}: '+
                            ('gravado; verifique a versão no ESP32.' if upload else f'compilado em {binary}.')))
            except Exception as exc:events.put(('error',f'{type(exc).__name__}: {exc}'))
        threading.Thread(target=worker,daemon=True).start()
    def button(text,callback):
        b=ttk.Button(actions,text=text,command=callback);b.pack(side='left',padx=3);buttons.append(b)
    button('Abrir central',start)
    button('Calibrar câmera e canhão',calibrate)
    button('Compilar firmware deste setup',lambda:operation(False))
    button('Gravar firmware por USB (COM)',lambda:operation(True))
    tk.Label(footer,textvariable=message,bg='#122033',fg='#ffe5aa',wraplength=1100,
             justify='left').pack(fill='x',pady=2)
    tk.Label(footer,text='Gravação manual: segure BOOT, pressione e solte EN, clique Gravar; '
             'solte BOOT após a identificação do chip. Encerre o monitor serial antes.',
             bg='#122033',fg='#c3d8e8',wraplength=1090,justify='left').pack(anchor='w')
    log=tk.Text(footer,bg='#1f3147',fg='white',height=2,state='disabled',wrap='word',font=('Consolas',9))
    log.pack(fill='x',pady=3)
    def update_checks():
        config=diagnostic['config'];link=diagnostic['link'];camera=diagnostic['camera']
        if config is None and name.get():
            try:
                from types import SimpleNamespace
                config=SimpleNamespace(data=profile_manager.assemble(name.get()))
            except (ValueError, OSError, KeyError):
                pass
        with diagnostic['lock']:
            packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
        age=time.monotonic()-stamp if stamp else 1e9
        link_state,link_detail,recent=diagnostic_link_state(
            diagnostic['running'],link,stamp,diagnostic['started'])
        if link and diagnostic['running']:
            link_detail += (f' · pacotes {link.telemetry_count} · perdas {link.disconnect_count}'
                            f' · último intervalo {link.last_interval_seconds*1000:.0f} ms'
                            f' · ida e volta {link.round_trip_seconds*1000:.0f} ms'
                            if link.round_trip_seconds is not None else
                            f' · pacotes {link.telemetry_count} · perdas {link.disconnect_count}'
                            f' · último intervalo {link.last_interval_seconds*1000:.0f} ms')
            if link.active_transport=='wifi_local':
                link_detail += f' · SSID {getattr(link,"wifi_ssid","?")}'
            link_detail += (f' · pacotes completos {link.full_telemetry_count}'
                            + (f' (há {time.monotonic()-link.last_full_packet_at:.1f}s)'
                               if link.last_full_packet_at else ' (aguardando)'))
        last_packet=dict(packet)
        if not recent:packet={}
        frame,frame_stamp=camera.latest() if camera else (None,0)
        source_kind=config.data.get('vision',{}).get('source_type') if config else None
        hw=config.data.get('hardware',{}) if config else {}
        drive=hw.get('drive_kind','bts7960_12v');cannon=hw.get('cannon_kind','mg996r')
        driver=hw.get('drive_driver_model') or 'não selecionado'
        motor=hw.get('drive_motor_model') or drive
        servo=hw.get('cannon_motor_model') or ('HT23-EC1000-K' if cannon=='ht23_ec1000' else 'MG996R')
        cannon_driver=hw.get('cannon_driver_model') or 'não selecionado'
        transport=str(config.data.get('esp',{}).get('transport','wifi_local') if config else 'wifi_local')
        serial_port=str(config.data.get('esp',{}).get('serial_port','auto') if config else 'auto')
        link_port=('USB '+serial_port if transport=='usb' else
                   'AP ESP32 192.168.4.1:8765' if transport=='wifi_local' else
                   'Wi-Fi local do ESP32')
        if recent:
            medium=str(link.active_transport or '').lower()
            link_port=('USB '+str(getattr(getattr(link,'_stream',None),'port',serial_port)) if medium=='usb' else
                       'AP ESP32 192.168.4.1:8765' if medium in ('wifi','wifi_local') else link_port)
        expected=config.data.get('_official',{}).get('firmware_signature','') if config else ''
        matched=bool(recent and expected and packet.get('setup_signature')==expected
                     and runtime.protocol_compatible(packet))
        def configured(flag,detail):
            return ('Enviando' if matched and packet.get(flag) else
                    'Não enviando',detail+' · PWM/relé não confirma ligação física')
        if drive=='bldc_ktc86':
            driver_state=('Não enviando','2× MCP4725 → SV; MCP23017 → F/R, EN, BRK; firmware físico pendente')
        else:
            driver_state=configured('drive_configured',f'{driver} · PWM/direção')
        if cannon=='ht23_ec1000':
            cannon_state=('Não enviando','STEP/DIR com interface elétrica validada; pan 25/26, tilt 32/33, câmera 14/27; sem homing/firmware')
        else:
            cannon_state=configured('servos_configured','PWM 50 Hz; posição física exige feedback externo')
        def sensor_text(location):
            valid=bool(packet.get(f'sensor_{location}_valid'))
            sensor_type=packet.get(f'sensor_{location}_type',
                                   22 if hw.get(f'dht_{location}_type')=='DHT22' else 11)
            error=packet.get(f'sensor_{location}_error',4)
            cause={0:'leitura íntegra',1:'timeout: confira DATA/alimentação',
                   2:'checksum: confira cabo/pull-up',
                   3:'valor fora da faixa do modelo',
                   4:'aguardando primeira amostra'}.get(error,f'erro {error}')
            def reading(field,unit):
                value=packet.get(f'{field}_{location}') if valid else None
                try:
                    return f'{float(value):.1f}{unit}' if value is not None and math.isfinite(float(value)) else '—'
                except (TypeError,ValueError):return '—'
            return (f"DHT{sensor_type}: {reading('temp',' °C')} / "
                    f"{reading('humidity',' % UR')} · {cause}")
        video_file=bool(source_kind=='video' and config and
                        runtime.local_path(config.data['vision'].get('camera_source','')).is_file())
        if video_file:
            video_state=('Não enviando','Arquivo disponível; a central abrirá o vídeo')
        elif frame is not None and frame_stamp and time.monotonic()-frame_stamp < 1.:
            video_state=('Recebendo/ enviando',
                         'Quadros disponíveis; vídeo salvo não serve para calibração' if source_kind=='video' else
                         f'Índice {camera.source} · {camera.backend_name} · quadros recentes')
        else:video_state=('Não enviando',camera.last_error if camera else 'Selecione a fonte')
        details={
          'Comunicação ESP32':(link_state,link_detail),
          'Versão do firmware':('Recebendo/ enviando' if matched else 'Enviando' if recent else 'Não enviando',
                f"{last_packet.get('setup_name') or ('Nome pendente; assinatura válida' if matched else '—')} · "
                f"{last_packet.get('setup_signature','—')} · há {age:.1f}s" if stamp else 'Verificar versão após conexão'),
          'Fonte de vídeo':video_state,
          'Servo canhão · Pan':cannon_state,
          'Servo canhão · Tilt':cannon_state,
          'Driver canhão · Pan':cannon_state,
          'Driver canhão · Tilt':cannon_state,
          'Placa de interface':('Não enviando',
                                'BLAZE-KTC-MOD-02: montar módulos, ensaiar e integrar firmware'
                                if hw.get('interface_board_id')=='blaze_ktc_modular_v2'
                                else 'Backends de ponte H/PWM RC'),
          'Servo câmera':(('Não enviando','Terceiro stepservo PUL/DIR; backend ausente')
                            if cannon=='ht23_ec1000' else
                            configured('camera_servo_configured',hw.get('camera_servo_model', 'SG90')+' · PWM 50 Hz')),
          'Microservo foco':configured('focus_actuator_configured',
                              'SG90 · RB focaliza, R3 dispersa; ângulo comandado '
                              +str(packet.get('focus_angle_commanded','—'))+'°'),
          'DHT interno':('Recebendo/ enviando' if packet.get('sensor_internal_valid') else 'Enviando' if matched else 'Não enviando',
                           sensor_text('internal')),
          'DHT externo':('Recebendo/ enviando' if packet.get('sensor_external_valid') else 'Enviando' if matched else 'Não enviando',
                           sensor_text('external')),
          'Driver esquerdo':driver_state,'Driver direito':driver_state,
          'Motor esquerdo':(driver_state[0],
                             'Giro exige inspeção física/encoder'),
          'Motor direito':(driver_state[0],
                             'Giro exige inspeção física/encoder'),
          'Relé · arrefecimento interno':configured('cool_internal_configured','GPIO 22'),
          'Relé · arrefecimento externo':configured('cool_external_configured','GPIO 13'),
          'Válvula do jato':configured('jet_configured','GPIO 21'),
          'LEDs':configured('leds_configured','GPIO do LED no firmware')}
        try:
            import pygame
            pygame.joystick.init();count=pygame.joystick.get_count()
            details['Controle Xbox']=('Recebendo/ enviando' if count else 'Não enviando',f'{count} controle(s) no sistema')
        except Exception:details['Controle Xbox']=('Não enviando','Conecte o Xbox antes de abrir a central')
        driver_id=hw.get('drive_driver_id')
        drive_pins = ('SV via 2× MCP4725; controle via MCP23017' if drive=='bldc_ktc86' else
                      'IN1/2 GPIO25/26 + ENA GPIO27; IN3/4 GPIO32/33 + ENB GPIO23'
                      if driver_id=='l298n' else
                      'AIN1/2 GPIO25/26; BIN1/2 GPIO32/33; nSLEEP externo'
                      if driver_id=='drv8833' else 'RPWM/LPWM/EN GPIO25/26/27 e 32/33/23')
        driver_port=drive_pins
        servo_port = ('GPIO25/26 pan; GPIO32/33 tilt · interface PUL/DIR 5 V' if cannon=='ht23_ec1000'
                      else 'GPIO18 pan / GPIO19 tilt · 50 Hz')
        model_port={
          'Comunicação ESP32':('ESP32',link_port),
          'Versão do firmware':(last_packet.get('setup_name','—'),'USB / AP local'),
          'Fonte de vídeo':(str(camera.source) if camera else
                            str(config.data.get('vision',{}).get('camera_source','—')) if config else '—',
                            'USB' if source_kind!='video' else 'Arquivo'),
          'Controle Xbox':('Xbox / SDL','USB / Bluetooth'),
          'Servo canhão · Pan':(hw.get('pan_servo_model') or servo,servo_port),
          'Servo canhão · Tilt':(hw.get('tilt_servo_model') or servo,servo_port),
          'Driver canhão · Pan':(cannon_driver,servo_port),
          'Driver canhão · Tilt':(cannon_driver,servo_port),
          'Placa de interface':('BLAZE-KTC-MOD-02' if hw.get('interface_board_id')=='blaze_ktc_modular_v2'
                                 else 'Sem placa','GPIO18/19 I²C; 2× MCP4725 e 2× MCP23017'
                                 if hw.get('interface_board_id')=='blaze_ktc_modular_v2' else '—'),
          'Servo câmera':(hw.get('camera_servo_model') or servo,
                           'GPIO14/27 · PUL/DIR via interface' if cannon=='ht23_ec1000'
                           else 'GPIO4 · PWM 50 Hz'),
          'Microservo foco':(hw.get('focus_actuator_model') or 'SG90',
                              'GPIO14 · PWM 50 Hz; alimentação externa'),
          'DHT interno':('DHT11 · dados '+hw.get('dht_internal_type','DHT22'),'GPIO16'),
          'DHT externo':('DHT11 · dados '+hw.get('dht_external_type','DHT22'),'GPIO17'),
          'Driver esquerdo':(driver,driver_port),
          'Driver direito':(driver,driver_port),
          'Motor esquerdo':(motor,drive_pins+' · driver esquerdo'),
          'Motor direito':(motor,drive_pins+' · driver direito'),
          'Relé · arrefecimento interno':('Relé','GPIO22'),
          'Relé · arrefecimento externo':('Relé','GPIO13'),
          'Válvula do jato':('Relé','GPIO21'),
          'LEDs':('LED de status','GPIO no setup de pinos')}
        # Um canal habilitado não prova a ligação física; só a comunicação
        # e o recebimento de dados recebem o rótulo 'Conectado'.
        for key in components:
            state, detail=details[key]
            model, port_label=model_port[key]
            tag=('connected' if state=='Recebendo/ enviando' else
                 'output' if state=='Enviando' and key in {
                     'Servo canhão · Pan','Servo canhão · Tilt','Servo câmera',
                     'Microservo foco','Motor esquerdo','Motor direito',
                     'Driver esquerdo','Driver direito','Relé · arrefecimento interno',
                     'Relé · arrefecimento externo','Válvula do jato','LEDs'} else
                 'waiting' if state=='Enviando' else 'neutral')
            checks.item(key,values=(key,model,port_label,state,detail),tags=(tag,))
        if root.winfo_exists():root.after(100,update_checks)
    def drain():
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='line':
                log.configure(state='normal');log.insert('end',value+'\n');log.see('end');log.configure(state='disabled')
                if 'Connecting' in value:message.set('Connecting... mantenha BOOT pressionado até identificar o chip.')
                match=re.search(r'Writing at[^\n]*\((\d+)\s*%\)',value)
                if match:message.set(f'Gravação: {match.group(1)}%')
            else:
                set_busy(False);refresh_builds();message.set(value)
        if root.winfo_exists():root.after(100,drain)
    def close():stop_diagnostic();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    refresh();root.after(100,drain);root.after(800,update_checks);root.mainloop()

