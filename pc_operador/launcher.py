"""Seletor de uma combinação completa e preparação do firmware pelo runtime."""
from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from datetime import datetime
import json
import os
import time

import cv2
from PIL import Image, ImageTk

import profile_manager


def open_camera_calibration(parent, config_path: Path, on_close) -> None:
    """Calibra câmera móvel e canhão com 12 correspondências físicas."""
    import runtime
    config = runtime.AppConfig(config_path)
    source_type = str(config.data['vision'].get('source_type','')).lower()
    camera_source=config.data['vision'].get('camera_source',config.camera_source())
    if source_type == 'video' or (isinstance(camera_source,str) and
                                    runtime.local_path(camera_source).is_file()):
        raise ValueError('Calibração física exige câmera ao vivo, não vídeo gravado.')
    profile = config.data.get('_official', {}).get('profile')
    name = config.data.get('_official', {}).get('name', '')
    store_path = profile_manager.USER / 'camera_cannon_calibrations.json'
    saved = runtime.read_json(store_path).get(name, {})
    angles = {str(a): dict(saved.get('angles', {}).get(str(a), {})) for a in (0, 90, 180)}
    dialog = tk.Toplevel(parent)
    dialog.title('BLAZE · Calibração da plataforma e da mira')
    dialog.geometry('1540x940')
    dialog.minsize(1220, 700)
    dialog.configure(bg='#122033')
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
    at_start = tk.BooleanVar(master=dialog,value=False)
    percent = tk.DoubleVar(master=dialog,value=float(saved.get('speed_percent',70)))
    times = {}
    sweep = {'start':None}


    def get_command():
        with lock:
            state = dict(command)
        reported = latest()
        signature = config.data.get('_official', {}).get('firmware_signature')
        matched = (profile == 'combate_real' and
                   reported.get('setup_name') == name and
                   reported.get('setup_signature') == signature)
        return runtime.control_message({
            'requested_mode': 'manual', 'stop': not (matched and mounted['value']), 'rearm': False,
            'calibrating': matched and mounted['value'], 'camera_pan_deg': state['camera_pan_deg'],
            'calibration_pan': state['calibration_pan'],
            'calibration_tilt': state['calibration_tilt'],
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
        on_telemetry, float(esp['reconnect_seconds']), str(esp.get('transport','auto')),
        str(esp.get('serial_port','auto')), int(esp.get('baudrate',115200)),
        str(esp.get('bluetooth_port','auto')),
        str(config.data.get('_official',{}).get('firmware_signature','')),
        preserve_wifi=isinstance(camera.source, str) and
        camera.source.lower().startswith(('rtsp://','rtsps://','http://','https://')))

    heading = tk.Frame(dialog, bg='#122033')
    heading.pack(fill='x', padx=12, pady=8)
    tk.Label(heading, text='Calibração física: plataforma 0° / 90° / 180°',
             font=('Segoe UI', 16, 'bold'), bg='#122033', fg='white').pack(anchor='w')
    tk.Label(heading, text='Use o firmware de COMBATE REAL da mesma combinação. Monte e alimente os '
             'três servos, conecte o ESP32 e a câmera. Mova pan/tilt até a mira coincidir com '
             'cada marca no vídeo e confirme o canto. Tração e válvulas permanecem bloqueadas. '
             'A telemetria informa ângulos comandados, sem medir o eixo do MG90S.',
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
    for title, var, lower, upper in (('2. Pan do canhão',pan,25,155),
                                     ('3. Tilt do canhão',tilt,35,145)):
        tk.Label(side, text=title, bg='#1e3044', fg='white').pack(anchor='w', padx=10, pady=(10, 0))
        tk.Scale(side, variable=var, from_=lower, to=upper, resolution=.5,
                 orient='horizontal', length=475, bg='#1e3044', fg='white',
                 highlightthickness=0, command=update_servo).pack(anchor='w', padx=10)
    # PWM transmite apenas a posição desejada. A chegada física é cronometrada pelo operador.
    speed_box=tk.LabelFrame(side,text='Ensaio supervisionado de velocidade',bg='#1e3044',fg='white')
    speed_box.pack(fill='x',padx=8,pady=5)
    tk.Label(speed_box,text='Faixas seguras: plataforma 0–180°, pan 25–155°, tilt 35–145°.\n'
             'Observe a chegada real dos três eixos. Solte água, tração e atuadores.',
             bg='#1e3044',fg='#d6e8f6',justify='left').pack(anchor='w',padx=5)
    def prerequisites():
        packet=latest()
        frame,stamp=camera.latest()
        return (profile=='combate_real' and installed.get() and link.connected and
                packet.get('setup_signature') == config.data['_official']['firmware_signature'] and
                packet.get('setup_name') == name and packet.get('camera_servo_configured') and
                packet.get('servos_configured') and frame is not None and
                time.monotonic()-stamp < 1.)
    def position_start():
        if not prerequisites():
            status.set('Faltam câmera real recente, ESP/firmware correspondente ou confirmação da montagem dos servos.')
            return
        at_start.set(False);times.clear();sweep['start']=None
        camera_angle.set(0);pan.set(25);tilt.set(35)
        with lock:command.update(camera_pan_deg=0.,calibration_pan=25.,calibration_tilt=35.)
        changed_at[0]=time.monotonic()
        status.set('Aguarde a chegada física aos mínimos: plataforma 0°, pan 25°, tilt 35°. Confirme visualmente.')
    ttk.Button(speed_box,text='1 · Enviar aos mínimos',command=position_start).pack(anchor='w',padx=5,pady=2)
    tk.Checkbutton(speed_box,text='Vi os 3 servos chegarem aos mínimos',variable=at_start,
                   bg='#1e3044',fg='white',selectcolor='#324e65',activebackground='#1e3044').pack(anchor='w',padx=5)
    def start_sweep():
        if not prerequisites() or not at_start.get() or time.monotonic()-changed_at[0]<1.:
            status.set('Primeiro confirme fisicamente os mínimos e aguarde pelo menos 1 s; verifique câmera e telemetria.')
            return
        camera_angle.set(180);pan.set(155);tilt.set(145)
        with lock:command.update(camera_pan_deg=180.,calibration_pan=155.,calibration_tilt=145.)
        sweep['start']=time.monotonic();times.clear();changed_at[0]=sweep['start']
        status.set('Os três máximos foram solicitados. Clique em cada chegada APÓS observar o eixo correspondente.')
    ttk.Button(speed_box,text='2 · Enviar aos máximos simultaneamente',command=start_sweep).pack(anchor='w',padx=5,pady=2)
    arrived_row=tk.Frame(speed_box,bg='#1e3044');arrived_row.pack(fill='x')
    speed_label=tk.StringVar(master=dialog,value='Velocidade ainda não estimada.')
    def update_speed_label(_=None):
        if len(times)!=3:
            speed_label.set(f'Tempos registrados: {len(times)}/3; confirme as chegadas reais.')
            return
        raw=min(360.,*(span/times[key] for key,span in (('plataforma',180),('pan',130),('tilt',110))))
        speed_label.set(' | '.join(f'{key}: {times[key]:.2f}s' for key in
                        ('plataforma','pan','tilt'))+
                        f' | comum: {raw:.1f}°/s; aplicado {percent.get():.0f}% = {raw*percent.get()/100:.1f}°/s.')
    def mark_arrival(motor):
        if sweep['start'] is None or motor in times or not prerequisites():
            status.set('Inicie a varredura com câmera, ESP e servos preparados; registre cada eixo uma vez.')
            return
        elapsed=time.monotonic()-sweep['start']
        if elapsed<.2:
            status.set('Tempo curto demais: observe a chegada física antes de confirmar.')
            return
        times[motor]=elapsed
        update_speed_label()
        status.set(f'{motor}: chegada registrada em {elapsed:.2f} s. ({len(times)}/3)')
    for motor in ('plataforma','pan','tilt'):
        ttk.Button(arrived_row,text='Chegou '+motor,command=lambda m=motor:mark_arrival(m)).pack(side='left',padx=3)
    tk.Scale(speed_box,variable=percent,from_=10,to=100,resolution=1,orient='horizontal',
             label='Porcentagem do limite medido (%)',bg='#1e3044',fg='white',
             highlightthickness=0,length=390,
             command=update_speed_label).pack(anchor='w',padx=5)
    tk.Label(speed_box,textvariable=speed_label,bg='#1e3044',fg='#9fe5c0').pack(anchor='w',padx=5)
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
    def refresh_cells():
        for (angle, corner), (pvar, tvar, button) in labels.items():
            value = angles[str(angle)].get(corner)
            pvar.set(f'{value[0]:.1f}' if value else '—')
            tvar.set(f'{value[1]:.1f}' if value else '—')
            button.configure(text='Registrado' if value else 'Confirmar')

    def confirm(angle, corner):
        if not prerequisites() or len(times)!=3:
            status.set('Confirme montagem, câmera/firmware e as três chegadas físicas antes dos 12 pontos.')
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
        if (packet.get('setup_name') != name or
                packet.get('setup_signature') != config.data['_official']['firmware_signature']):
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
        status.set(f'{corner} em {angle}° registrado. Confirme os 12 pontos e salve.')

    for row, (corner, title) in enumerate(corners, start=1):
        ttk.Label(table, text=title).grid(row=row, column=0, padx=2, pady=4, sticky='w')
        for group, angle in enumerate((0, 90, 180)):
            base = 1+group*4
            ttk.Label(table, text=f'{angle}°').grid(row=row, column=base)
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
        if not prerequisites() or len(times)!=3:
            status.set('Calibração requer câmera real, três servos verificados e tempos de chegada registrados.')
            return
        raw=min(360.,*(span/times[key] for key,span in (('plataforma',180),('pan',130),('tilt',110))))
        entry={'schema_version':2,'enabled':True,'angles':angles,
               'speed_measurements_s':times.copy(), 'speed_percent':percent.get(),
               'speed_limit_deg_s':round(raw*percent.get()/100,2),
               'frame_size':list(last_shape[0]),'recorded_at':time.strftime('%Y-%m-%dT%H:%M:%S')}
        if not runtime.camera_calibration_complete(entry):
            status.set('Faltam pontos: registre os quatro cantos nas três posições.')
            return
        records=runtime.read_json(store_path)
        records[name]=entry
        store_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=store_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,store_path)
        status.set(f'Calibração da combinação {name} salva. Feche a janela e abra a central.')

    last_shape=[(0,0)]
    footer=tk.Frame(dialog,bg='#122033')
    footer.pack(fill='x',padx=12,pady=7)
    ttk.Button(footer,text='Salvar os 12 pontos',command=save).pack(side='left')
    tk.Label(footer,textvariable=status,bg='#122033',fg='#ffdfa4',
             wraplength=1000,justify='left').pack(side='left',padx=14)

    def tick():
        if not running[0]:return
        frame, stamp = camera.latest()
        packet = latest()
        if frame is not None:
            height,width=frame.shape[:2]
            last_shape[0]=(width,height)
            view=frame.copy()
            angle=camera_angle.get()
            for corner,(u,v) in {'tl':(0,0),'tr':(1,0),'bl':(0,1),'br':(1,1)}.items():
                x=12 if u==0 else width-13
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
        elif packet.get('setup_signature') != config.data['_official']['firmware_signature']:
            status.set('Firmware diferente do setup escolhido: compile e grave este perfil.')
        if running[0]:dialog.after(120,tick)

    def close():
        running[0]=False
        link.stop()
        camera.stop()
        dialog.destroy()
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
    root.geometry('1180x860');root.minsize(980,710)
    root.configure(bg='#122033')
    message=tk.StringVar(master=root,value='Selecionando combinação completa...')
    name=tk.StringVar(master=root);choice_label=tk.StringVar(master=root);port=tk.StringVar(master=root)
    combination_labels={}
    build_name=tk.StringVar(master=root)
    events=queue.Queue();busy={'value':False}
    diagnostic={'link':None,'camera':None,'packet':{},'stamp':0.,'config':None,
                'running':False,'started':0.,'epoch':0,'lock':threading.Lock()}
    builds=[]
    panel=tk.Frame(root,bg='#122033');panel.pack(fill='both',expand=True,padx=16,pady=10)
    tk.Label(panel,text='BLAZE · '+('SIMULAÇÃO' if profile=='simulacao' else 'COMBATE REAL'),
             bg='#122033',fg='white',font=('Segoe UI',17,'bold')).pack(anchor='w')
    tk.Label(panel,text='Escolha um setup completo. A verificação abre automaticamente uma conexão neutra; '
             'Start no Xbox rearma o robô apenas dentro da central. Saídas de potência ficam desativadas nesta janela.',
             bg='#122033',fg='#c3d8e8',wraplength=1090,justify='left').pack(anchor='w',pady=(2,8))
    selection=tk.Frame(panel,bg='#122033');selection.pack(fill='x',pady=3)
    tk.Label(selection,text='Combinação completa:',bg='#122033',fg='white').pack(side='left')
    choice=ttk.Combobox(selection,textvariable=choice_label,state='readonly',width=75)
    choice.pack(side='left',padx=8,fill='x',expand=True)
    ttk.Button(selection,text='Atualizar setups/portas',command=lambda: refresh()).pack(side='left')
    upper=tk.Frame(panel,bg='#122033');upper.pack(fill='x',pady=5)
    local_network=tk.StringVar(master=root,value='Rede local: será gerada ao preparar o firmware.')
    tk.Label(panel,textvariable=local_network,bg='#122033',fg='#a8dfc3',
             wraplength=1090,justify='left').pack(anchor='w',pady=2)
    tk.Label(upper,text='Porta COM para upload:',bg='#122033',fg='white').pack(side='left')
    ports=ttk.Combobox(upper,textvariable=port,width=16);ports.pack(side='left',padx=6)
    def selected():
        if not name.get():raise ValueError('Selecione uma combinação completa.')
        return profile_manager.prepare(name.get(),profile)
    def stop_diagnostic():
        diagnostic['epoch']+=1
        diagnostic['running']=False
        camera,link=diagnostic['camera'],diagnostic['link']
        diagnostic['camera']=diagnostic['link']=None
        if link:link.stop()
        if camera:camera.stop()
        with diagnostic['lock']:
            diagnostic['packet']={};diagnostic['stamp']=0.
        connection_button.configure(text='Conectar USB/Wi-Fi/BT')
    def start_diagnostic():
        if diagnostic['running'] or busy['value']:return
        try:
            config=runtime.AppConfig(selected()[0])
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
                float(e['reconnect_seconds']),str(e.get('transport','auto')),
                str(e.get('serial_port','auto')),int(e.get('baudrate',115200)),
                str(e.get('bluetooth_port','auto')),
                str(config.data.get('_official',{}).get('firmware_signature','')))
            diagnostic.update(link=link,camera=camera,running=True,started=time.monotonic())
            if camera:camera.start()
            link.start()
            connection_button.configure(text='Desconectar USB/Wi-Fi/BT')
            message.set('Conexão de diagnóstico iniciada; verificando telemetria e quadros.')
        except Exception as exc:
            message.set(f'Diagnóstico: {type(exc).__name__}: {exc}')
    def toggle_diagnostic():
        if diagnostic['running']:
            stop_diagnostic();message.set('Comunicação de diagnóstico interrompida pelo operador.')
        else:start_diagnostic()
    connection_button=ttk.Button(upper,text='Conectar USB/Wi-Fi/BT',command=toggle_diagnostic)
    connection_button.pack(side='left',padx=8)
    ttk.Button(upper,text='Verificar versão no ESP32',command=lambda: show_firmware()).pack(side='left')
    firmware=tk.Frame(panel,bg='#1e3044');firmware.pack(fill='x',pady=5)
    tk.Label(firmware,text='Firmwares já compilados (nome · data · assinatura):',
             bg='#1e3044',fg='white').pack(anchor='w',padx=8,pady=(4,1))
    build_choice=ttk.Combobox(firmware,textvariable=build_name,state='readonly',width=95)
    build_choice.pack(fill='x',padx=8,pady=(0,5))
    state_box=tk.LabelFrame(panel,text='Recebimento e requisitos em tempo real',bg='#1e3044',fg='white')
    state_box.pack(fill='x',pady=5)
    checks=ttk.Treeview(state_box,columns=('item','state','detail'),show='headings',height=11)
    for key,title,width in [('item','Componente',190),('state','Estado',170),('detail','Leitura / requisito',750)]:
        checks.heading(key,text=title);checks.column(key,width=width,anchor='w')
    check_scroll=ttk.Scrollbar(state_box,orient='vertical',command=checks.yview)
    checks.configure(yscrollcommand=check_scroll.set)
    check_scroll.pack(side='right',fill='y',pady=5)
    checks.pack(side='left',fill='both',expand=True,padx=6,pady=5)
    components=['Comunicação ESP32','Versão do firmware','Fonte de vídeo','Controle Xbox',
                'Servo canhão · Pan','Servo canhão · Tilt','Servo câmera · MG90S',
                'DHT interno','DHT externo','Driver esquerdo','Driver direito',
                'Motor esquerdo','Motor direito','Relé · arrefecimento interno',
                'Relé · arrefecimento externo','Válvula do jato']
    for item in components:checks.insert('', 'end',iid=item,values=(item,'Aguardando','—'))
    guide=tk.LabelFrame(panel,text='O que cada botão faz e quando usar',bg='#1e3044',fg='white')
    guide.pack(fill='x',pady=5)
    instructions=[
      ('Atualizar','Relê setups e portas COM disponíveis no computador.'),
      ('Comunicação','Tenta USB e depois a rede local ESP32 (192.168.4.1). Se entrar na rede local, o PC troca de Wi-Fi; inicia sem movimento.'),
      ('Verificar versão','Consulta assinatura/nome recebidos por telemetria; ESP32 com firmware e cabo ou Wi-Fi ativos.'),
      ('Compilar','Gera firmware para a combinação selecionada. Não requer ESP32 conectado.'),
      ('Gravar','Usa exatamente o binário escolhido na lista, com porta COM livre e ESP32 em modo de gravação.'),
      ('Calibrar','Combate real: câmera ao vivo, firmware correspondente, três servos montados/alimentados e confirmação visual.'),
      ('Abrir central','Inicia vídeo, Xbox e conexão da operação. Na simulação bastam vídeo/modelos/Xbox; atuadores opcionais.')]
    for title,description in instructions:
        row=tk.Frame(guide,bg='#1e3044');row.pack(fill='x',padx=6)
        tk.Label(row,text=title+':',width=17,anchor='w',bg='#1e3044',fg='#9fe5c0').pack(side='left')
        tk.Label(row,text=description,anchor='w',bg='#1e3044',fg='#d6e8f6').pack(side='left')
    actions=tk.Frame(panel,bg='#122033');actions.pack(fill='x',pady=6)
    buttons=[]
    def set_busy(flag):
        busy['value']=flag
        for button in buttons:button.configure(state='disabled' if flag else 'normal')
        if flag:progress.start(12)
        else:progress.stop()
    def show_firmware():
        if not diagnostic['running']:start_diagnostic()
        with diagnostic['lock']:
            packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
        if not diagnostic['link'] or not diagnostic['link'].connected or time.monotonic()-stamp>1.5:
            message.set('Aguardando telemetria recente do ESP32. Confira USB/Wi-Fi e alimentação.')
            return
        expected=diagnostic['config'].data.get('_official',{}).get('firmware_signature','')
        sig=packet.get('setup_signature','');version=packet.get('setup_name','desconhecido')
        message.set(f'ESP32 gravado: {version} · assinatura {sig or "ausente"} · '
                    +('corresponde ao setup selecionado' if sig==expected else 'DIFERENTE do setup selecionado'))
    def refresh_builds():
        nonlocal builds
        builds=profile_manager.available_firmware(profile)
        choices=[f"{b['name']} · {b['built_at'][:19].replace('T',' ')} UTC · {b['signature']}" for b in builds]
        build_choice['values']=choices
        index=next((i for i,b in enumerate(builds) if b['name']==name.get()),None)
        build_choice.current(index) if index is not None else build_name.set('')
    def refresh():
        try:
            local=profile_manager.local_link_credentials(create=False)
            local_network.set((f'Rede local sem roteador: {local[0]} · IP 192.168.4.1 · '
                               f'Bluetooth: {local[2]} · PIN: {local[3]} (pareie uma vez no Windows). '
                               'O vídeo USB ou arquivo permanece independente da conexão do ESP32.')
                              if local else 'Rede local: senha exclusiva criada ao preparar o firmware; grave o novo firmware no ESP32.')
            available=profile_manager.names(profile)
            records=profile_manager._read(profile_manager.USER/'combinations.json')
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
            from serial.tools import list_ports
            found=[p.device for p in list_ports.comports()];ports['values']=found
            if not port.get() and found:port.set(found[0])
            refresh_builds()
            if not available:message.set('Sem combinação: crie e ative um setup completo na seção 7 do notebook.')
            elif not diagnostic['running'] and not busy['value']:root.after(100,start_diagnostic)
        except Exception as exc:message.set(f'Atualização: {type(exc).__name__}: {exc}')
    def selection_changed(_=None):
        if busy['value']:return
        selected_name=combination_labels.get(choice_label.get())
        if not selected_name:return
        name.set(selected_name)
        stop_diagnostic();refresh_builds();root.after(200,start_diagnostic)
    choice.bind('<<ComboboxSelected>>',selection_changed)
    def start():
        if busy['value']:return
        try:config_path,_=selected()
        except Exception as exc:message.set(str(exc));return
        set_busy(True);stop_diagnostic()
        message.set('Abrindo central e carregando modelos de visão...')
        def open_central():
            try:
                import central_operador
                config=runtime.AppConfig(config_path)
                central_operador.configure(config)
                app=central_operador.CentralOperador(config)
                central_operador.attach_controller(app)
                root.destroy();app.run()
            except Exception as exc:
                message.set(f'Central: {type(exc).__name__}: {exc}')
                if root.winfo_exists():set_busy(False);start_diagnostic()
        root.after(70,open_central)
    def calibrate():
        if busy['value']:return
        try:
            path,data=selected()
            if profile!='combate_real' or data['vision'].get('source_type')=='video':
                raise ValueError('Requer perfil de combate real e câmera ao vivo, não arquivo de vídeo.')
            config=diagnostic['config']
            with diagnostic['lock']:
                packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
            frame,frame_stamp=diagnostic['camera'].latest() if diagnostic['camera'] else (None,0)
            if not diagnostic['running'] or time.monotonic()-stamp>3.5 or frame is None or not frame_stamp:
                raise ValueError('Aguarde câmera ao vivo e telemetria recentes do ESP32.')
            if packet.get('setup_name')!=data['_official']['name'] or packet.get('setup_signature')!=data['_official']['firmware_signature']:
                raise ValueError('Grave primeiro o firmware da mesma combinação.')
            if not packet.get('servos_configured') or not packet.get('camera_servo_configured'):
                raise ValueError('O firmware não habilita os três canais dos servos.')
            set_busy(True);stop_diagnostic()
            def completed():set_busy(False);start_diagnostic()
            open_camera_calibration(root,path,completed)
        except Exception as exc:
            set_busy(False);message.set(f'Calibração bloqueada: {exc}');start_diagnostic()
    def operation(upload=False):
        if busy['value']:return
        try:
            _,data=selected();chosen=data['_official']['name']
            build=None
            if upload:
                index=build_choice.current()
                if index<0 or index>=len(builds):raise ValueError('Selecione um firmware compilado na lista.')
                build=builds[index]
                if build['name']!=chosen:raise ValueError('Escolha o firmware da combinação completa selecionada.')
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
    button('Gravar firmware selecionado',lambda:operation(True))
    progress=ttk.Progressbar(panel,mode='indeterminate');progress.pack(fill='x',pady=2)
    tk.Label(panel,textvariable=message,bg='#122033',fg='#ffe5aa',wraplength=1100,
             justify='left').pack(fill='x',pady=3)
    tk.Label(panel,text='Gravação manual: segure BOOT, pressione e solte EN, clique Gravar; '
             'solte BOOT após a identificação do chip. Encerre o monitor serial antes.',
             bg='#122033',fg='#c3d8e8',wraplength=1090,justify='left').pack(anchor='w')
    log=tk.Text(panel,bg='#1f3147',fg='white',height=5,state='disabled',wrap='word',font=('Consolas',9))
    log.pack(fill='both',expand=True,pady=4)
    def update_checks():
        config=diagnostic['config'];link=diagnostic['link'];camera=diagnostic['camera']
        with diagnostic['lock']:
            packet=dict(diagnostic['packet']);stamp=diagnostic['stamp']
        age=time.monotonic()-stamp if stamp else 1e9
        recent=bool(diagnostic['running'] and link and link.connected and age<1.5)
        last_packet=dict(packet)
        if not recent:packet={}
        frame,frame_stamp=camera.latest() if camera else (None,0)
        source_kind=config.data.get('vision',{}).get('source_type') if config else None
        hw=config.data.get('hardware',{}) if config else {}
        drive=hw.get('drive_kind','bts7960_12v');cannon=hw.get('cannon_kind','mg996r')
        driver={'dc_3_6v':'BTS7960','bts7960_12v':'BTS7960','bldc_ktc86':'KTC-J-DR-BLDC750'}.get(drive,'desconhecido')
        expected=config.data.get('_official',{}).get('firmware_signature','') if config else ''
        matched=bool(recent and packet.get('setup_signature')==expected)
        if recent:link_state='Recebendo';link_detail=f'{link.active_transport.upper()} · último pacote há {age:.1f}s'
        elif diagnostic['running'] and age<5:
            link_state='Intermitente';link_detail=f'Último pacote há {age:.1f}s; {link.last_error or "reconectando"}'
        elif diagnostic['running'] and time.monotonic()-diagnostic['started']<8:
            link_state='Conectando';link_detail=f'Tentando {link.attempting or "encontrar o ESP32"}; saídas neutras'
        elif diagnostic['running']:
            link_state='Sem resposta';link_detail=f'Tentando {link.attempting or "outro meio"}; {link.last_error or "nenhuma telemetria válida"}; último pacote: '+(f'{age:.1f}s' if stamp else 'nunca')
        else:link_state='Desligado';link_detail='Clique Conectar USB/Wi-Fi/BT'
        def configured(flag,detail):
            return ('Canal habilitado' if matched and packet.get(flag) else
                    'Config. pendente' if matched else 'Aguardando',detail+' · ligação física exige observação')
        if drive=='bldc_ktc86':
            driver_state=('Integração pendente','Driver selecionado; entradas 0–5 V e feedback requerem interface validada')
        else:
            driver_state=configured('drive_configured',f'{driver} · PWM/direção')
        if cannon=='ht23_ec1000':
            cannon_state=('Integração pendente','KTC-DR23EC-K: pulso/direção/encoder; canal PWM de MG996R desativado')
        else:
            cannon_state=configured('servos_configured','MG996R · PWM 50 Hz')
        video_file=bool(source_kind=='video' and config and
                        runtime.local_path(config.data['vision'].get('camera_source','')).is_file())
        if video_file:
            video_state=('Arquivo disponível','Será aberto ao entrar na central; não serve para calibração')
        elif frame is not None:
            video_state=('Vídeo salvo' if source_kind=='video' else 'Recebendo',
                         'Quadros disponíveis; vídeo salvo não serve para calibração' if source_kind=='video' else 'Quadros recentes da câmera')
        else:video_state=('Pendente',camera.last_error if camera else 'Selecione a fonte')
        details={
          'Comunicação ESP32':(link_state,link_detail),
          'Versão do firmware':('Compatível' if matched else 'Diferente' if recent else 'Última leitura' if stamp else 'Aguardando',
                f"{last_packet.get('setup_name','—')} · {last_packet.get('setup_signature','—')} · há {age:.1f}s" if stamp else 'Verificar versão após conexão'),
          'Fonte de vídeo':video_state,
          'Servo canhão · Pan':cannon_state,
          'Servo canhão · Tilt':cannon_state,
          'Servo câmera · MG90S':configured('camera_servo_configured','Plataforma · PWM 50 Hz'),
          'DHT interno':('Leitura válida' if packet.get('sensor_internal_valid') else 'Pendente',
                           str(packet.get('temp_internal','—'))+' °C'),
          'DHT externo':('Leitura válida' if packet.get('sensor_external_valid') else 'Pendente',
                           str(packet.get('temp_external','—'))+' °C'),
          'Driver esquerdo':driver_state,'Driver direito':driver_state,
          'Motor esquerdo':('Saída habilitada' if driver_state[0]=='Canal habilitado' else driver_state[0],
                             'Giro exige inspeção física/encoder'),
          'Motor direito':('Saída habilitada' if driver_state[0]=='Canal habilitado' else driver_state[0],
                             'Giro exige inspeção física/encoder'),
          'Relé · arrefecimento interno':configured('cool_internal_configured','GPIO 22'),
          'Relé · arrefecimento externo':configured('cool_external_configured','GPIO 13'),
          'Válvula do jato':configured('jet_configured','GPIO 21')}
        try:
            import pygame
            pygame.joystick.init();count=pygame.joystick.get_count()
            details['Controle Xbox']=('Detectado' if count else 'Aguardando',f'{count} controle(s) no sistema')
        except Exception:details['Controle Xbox']=('Aguardando','Conecte o Xbox antes de abrir a central')
        for key in components:checks.item(key,values=(key,*details[key]))
        if root.winfo_exists():root.after(1000,update_checks)
    def drain():
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='line':
                log.configure(state='normal');log.insert('end',value+'\n');log.see('end');log.configure(state='disabled')
                if 'Connecting' in value:message.set('Connecting... mantenha BOOT pressionado até identificar o chip.')
                match=re.search(r'Writing at[^\n]*\((\d+)\s*%\)',value)
                if match:message.set(f'Gravação: {match.group(1)}%')
            else:
                set_busy(False);refresh_builds();message.set(value);root.after(250,start_diagnostic)
        if root.winfo_exists():root.after(100,drain)
    def close():stop_diagnostic();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    refresh();root.after(100,drain);root.after(800,update_checks);root.mainloop()
