"""Janela para revisar e editar arquivos no GitHub sem clonar manualmente.

Execute no VS Code: python scripts/gerenciar_github.py
O script usa o Git for Windows e a autenticação Git já configurada no PC.
Nenhuma operação remota é feita até o botão Confirmar commit e envio.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
import unicodedata
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, simpledialog, ttk

_SCRIPT_PARENT = Path(__file__).resolve().parents[1]
ROOT = _SCRIPT_PARENT if (_SCRIPT_PARENT/'pc_operador').is_dir() else Path.cwd()
DESTINATION = 'Protótipo V0.0'
URL = 'https://github.com/Projeto-Bombeiros/project_repository.git'
SECRET_KEYS = ('password', 'ssid', 'token', 'secret', 'api_key', 'bt_pin', 'credential')
PRIVATE_NAMES = {'config.json', 'secrets.h', 'setup_generated.h', 'network_credentials.json'}
SKIP_DIRS = {'.git', '.bootstrap', '.pio', '__pycache__', 'output', 'runs', 'videos_input',
             '.venv', 'venv', 'arquivo_setups_v11'}
SKIP_SUFFIXES = {'.pyc', '.mp4', '.avi', '.mov', '.mkv', '.bin', '.elf', '.map', '.log', '.zip'}
PORTABLE_JSON = {'connection.json', 'control.json', 'vision.json', 'hardware.json',
                 'combinations.json', 'camera_cannon_calibrations.json'}
ASCII_PATH = re.compile(r'^[A-Za-z0-9._/ -]*$')
ASCII_NAME = re.compile(r'^[A-Za-z0-9._ -]*$')
ASCII_EMAIL = re.compile(r'^[A-Za-z0-9._%+@-]*$')
ASCII_URL = re.compile(r'^[A-Za-z0-9._~:/@?&=%+\-]*$')


def valid_path_field(value: str) -> bool:
    """Somente ASCII digitado; conserva o nome obrigatório Protótipo V0.0."""
    return bool(ASCII_PATH.fullmatch(value) or DESTINATION.startswith(value) or
                (value.startswith(DESTINATION+'/') and
                 ASCII_PATH.fullmatch(value[len(DESTINATION)+1:])))


def ascii_name(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value)
                   if ord(c) < 128 and ASCII_NAME.fullmatch(c))


def validate_entry(field: str, value: str) -> bool:
    matcher = {'Repositório': ASCII_URL, 'Branch': ASCII_PATH,
               'Pasta no GitHub': None, 'Nome para commit': ASCII_NAME,
               'E-mail para commit': ASCII_EMAIL}[field]
    return valid_path_field(value) if matcher is None else bool(matcher.fullmatch(value))


class Tooltip:
    def __init__(self, widget, message):
        self.widget, self.message = widget, message
        self.pending = None
        self.window = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')

    def schedule(self, _event=None):
        self.hide()
        self.pending = self.widget.after(450, self.show)

    def show(self):
        self.pending = None
        x, y = self.widget.winfo_pointerxy()
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f'+{x+12}+{y+16}')
        tk.Label(self.window, text=self.message, bg='#fff6cd', fg='#182331',
                 relief='solid', borderwidth=1, wraplength=340,
                 justify='left', padx=8, pady=5).pack()

    def hide(self, _event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class PathDialog(tk.simpledialog.Dialog):
    """Entrada de caminho que bloqueia caracteres não aceitos enquanto digita."""
    def __init__(self, parent, title, prompt, initial):
        self.prompt, self.initial = prompt, initial
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self.prompt).pack(anchor='w', pady=(0, 8))
        check = (master.register(valid_path_field), '%P')
        self.entry = ttk.Entry(master, width=60, validate='key', validatecommand=check)
        self.entry.insert(0, self.initial)
        self.entry.pack(fill='x')
        return self.entry

    def validate(self):
        try:
            safe_path(self.entry.get())
            if not valid_path_field(self.entry.get()):raise ValueError('Use apenas letras sem acento, números, espaço, /, ponto, _ e -.')
            return True
        except ValueError as exc:
            messagebox.showerror('Caminho inválido', str(exc), parent=self)
            return False

    def apply(self):
        self.result = self.entry.get().strip()


def safe_path(raw: str) -> Path:
    """Rejeita caminhos absolutos, ascendentes e a pasta interna do Git."""
    name = raw.strip().replace('\\', '/')
    p = PurePosixPath(name)
    windows_reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)),
                        *('LPT'+str(i) for i in range(1,10))}
    if (not name or not p.parts or p.is_absolute() or ':' in name or
            any(part in ('', '.', '..', '.git') or part.rstrip(' .') != part or
                part.split('.')[0].upper() in windows_reserved or
                any(ch in part for ch in '<>"|?*') for part in p.parts)):
        raise ValueError('Caminho inválido: ' + raw)
    return Path(*p.parts)


def run(*args, cwd: Path, check=True) -> str:
    p = subprocess.run(['git', '-C', str(cwd), *map(str, args)],
                       text=True, encoding='utf-8', errors='replace',
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()


def portable_json(path: Path, root: Path) -> bytes:
    data = copy.deepcopy(json.loads(path.read_text(encoding='utf-8')))
    def clean(value, key=''):
        if isinstance(value, dict):
            result = {}
            for k, item in value.items():
                if any(secret in k.casefold() for secret in SECRET_KEYS):
                    continue
                if k == 'trajectory_export_dir':
                    result[k] = '../output/visao'
                    continue
                result[k] = clean(item, k)
            if isinstance(result.get('vision'), dict):
                vision = result['vision']
                for model_key in ('fire_model', 'person_model', 'firefighter_model'):
                    original = str(vision.get(model_key) or '')
                    if original:
                        model_name = original.replace('\\', '/').split('/')[-1]
                        vision[model_key] = ('models/' + model_name if
                                             (root/'pc_operador/models'/model_name).is_file() else '')
                source = str(vision.get('camera_source', ''))
                if (vision.get('source_type') == 'video' or
                    re.match(r'^(?:[A-Za-z]:[\\/]|/|\\\\|\w+://)', source)):
                    vision.update(source_type='local', camera_source=0)
            return result
        if isinstance(value, list):
            return [clean(v, key) for v in value]
        if isinstance(value, str) and (re.match(r'^(?:[A-Za-z]:[\\/]|/|\\\\)', value) or
                                       re.match(r'^\w+://[^/]*@', value)):
            return ''
        return value
    return (json.dumps(clean(data), ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def allowed(rel: Path) -> bool:
    if any(p in SKIP_DIRS for p in rel.parts) or rel.name in PRIVATE_NAMES:
        return False
    if rel.suffix.lower() in SKIP_SUFFIXES or rel.name.startswith('.file.'):
        return False
    if 'parameters_setups' in rel.parts and 'user' in rel.parts:
        return rel.name in PORTABLE_JSON
    return True


class RepoSession:
    def __init__(self, url: str, branch: str):
        if not re.fullmatch(r'(?:https://github\.com/[^\s/]+/[^\s/]+|git@github\.com:[^\s/]+/[^\s/]+)(?:\.git)?', url):
            raise ValueError('Informe a URL HTTPS ou SSH de um repositório GitHub.')
        self.temp = tempfile.TemporaryDirectory(prefix='blaze-repo-')
        self.path = Path(self.temp.name)/'repo'
        try:
            p = subprocess.run(['git', 'clone', '--quiet', '--branch', branch, '--', url, str(self.path)],
                               text=True, encoding='utf-8', errors='replace', capture_output=True)
            if p.returncode:
                raise RuntimeError((p.stderr or p.stdout).strip())
        except Exception:
            self.temp.cleanup()
            raise
        self.branch = branch
        run('config', 'core.quotePath', 'false', cwd=self.path)

    def tracked(self) -> list[str]:
        return [s for s in run('ls-files', '-z', cwd=self.path).split('\0') if s]

    def all_local(self, root: Path) -> list[Path]:
        selected = []
        for current, directories, files in os.walk(root):
            directories[:] = [name for name in directories if name not in SKIP_DIRS]
            for name in files:
                path = Path(current)/name
                relative = path.relative_to(root)
                if allowed(relative):
                    selected.append(relative)
        return sorted(selected)

    def send(self, root: Path, selected: list[Path], folder: str, replace=False) -> tuple[int,int]:
        target_root = safe_path(folder)
        if replace:
            tracked = self.tracked()
            if tracked:
                run('rm', '-r', '-f', '--', *tracked, cwd=self.path)
        copied = 0
        for rel in selected:
            rel = safe_path(rel.as_posix())
            if not allowed(rel):
                continue
            source = root/rel
            if not source.is_file():
                continue
            dst = self.path/target_root/rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if 'parameters_setups' in rel.parts and 'user' in rel.parts and rel.name in PORTABLE_JSON:
                dst.write_bytes(portable_json(source, root))
            else:
                shutil.copy2(source, dst)
            copied += 1
        run('add', '-A', '-f', '--', target_root, cwd=self.path)
        return copied, len(self.tracked())

    def mkdir(self, name: str):
        path = self.path/safe_path(name)
        path.mkdir(parents=True, exist_ok=True)
        (path/'.gitkeep').touch(exist_ok=True)
        run('add', '-f', '--', path.relative_to(self.path), cwd=self.path)

    def move(self, names: list[str], dest: str):
        target = self.path/safe_path(dest)
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = self.path/safe_path(name)
            if not source.exists():
                raise FileNotFoundError(name)
            destination = target/source.name
            if destination.exists():
                raise ValueError('Já existe: ' + str(destination.relative_to(self.path)))
            run('mv', '--', source.relative_to(self.path), destination.relative_to(self.path), cwd=self.path)

    def remove(self, names: list[str]):
        for name in names:
            path = safe_path(name)
            run('rm', '-r', '-f', '--', path, cwd=self.path)

    def summary(self) -> str:
        run('add', '-A', cwd=self.path)
        changed = run('diff', '--cached', '--name-status', cwd=self.path)
        stat = run('diff', '--cached', '--stat', cwd=self.path)
        return (stat+'\n\n'+changed).strip() or 'Nenhuma alteração pendente.'

    def compare(self, root: Path, selected: list[Path], folder: str) -> str:
        base = safe_path(folder)
        lines=[]
        for rel in selected:
            if not allowed(rel):
                continue
            src=root/rel; dst=self.path/base/rel
            if not src.is_file():
                continue
            new=portable_json(src,root) if 'parameters_setups' in rel.parts and 'user' in rel.parts else src.read_bytes()
            old=dst.read_bytes() if dst.is_file() else None
            state='NOVO' if old is None else 'IGUAL' if old==new else 'DIFERENTE'
            lines.append(f'{state:10} {base/rel}')
            if old is not None and old!=new and len(old)+len(new)<100000:
                try:
                    diff=difflib.unified_diff(old.decode('utf-8').splitlines(),new.decode('utf-8').splitlines(),
                                              fromfile='GitHub',tofile='PC',lineterm='')
                    lines.extend('  '+line for line in list(diff)[:36])
                except UnicodeDecodeError:
                    lines.append('  Arquivo binário: SHA256 '+hashlib.sha256(new).hexdigest()[:12])
        return '\n'.join(lines) if lines else 'Selecione arquivos locais para comparar.'

    def download(self, remote: list[str], folder: Path):
        for name in remote:
            rel=safe_path(name)
            source=self.path/rel
            if not source.is_file():
                continue
            dest=folder/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest)

    def publish(self, name: str, email: str):
        if not name.strip() or not email.strip():
            raise ValueError('Informe nome e e-mail para registrar o commit.')
        if not run('diff', '--cached', '--name-only', cwd=self.path):
            raise ValueError('Não há alterações preparadas.')
        run('config','user.name',name.strip(),cwd=self.path)
        run('config','user.email',email.strip(),cwd=self.path)
        run('commit','-m','Organizar BLAZE em Protótipo V0.0',cwd=self.path)
        run('push','origin','HEAD:'+self.branch,cwd=self.path)

    def close(self):
        self.temp.cleanup()


class Window:
    def __init__(self):
        self.app = tk.Tk()
        self.app.title('BLAZE · Gerenciador interativo do GitHub')
        self.app.geometry('1440x920')
        self.app.minsize(1080, 700)
        self.session = None
        self.busy = False
        self.background = False
        self.buttons = []
        self.root = tk.StringVar(value=str(ROOT))
        self.url = tk.StringVar(value=URL)
        self.branch = tk.StringVar(value='main')
        self.folder = tk.StringVar(value=DESTINATION)
        self.name = tk.StringVar(value='')
        self.email = tk.StringVar(value='')
        try:
            self.name.set(ascii_name(run('config', '--global', '--get', 'user.name', cwd=ROOT, check=False)))
            saved_email = run('config', '--global', '--get', 'user.email', cwd=ROOT, check=False)
            self.email.set(saved_email if ASCII_EMAIL.fullmatch(saved_email) else '')
        except FileNotFoundError:
            pass

        header = ttk.LabelFrame(self.app, text='Repositório e pacote', padding=10)
        header.pack(fill='x', padx=10, pady=(10, 4))
        for field, variable in (('Repositório', self.url), ('Branch', self.branch),
                                ('Pasta no GitHub', self.folder), ('Pacote no PC', self.root),
                                ('Nome para commit', self.name), ('E-mail para commit', self.email)):
            row = ttk.Frame(header)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=field, width=20).pack(side='left')
            if field == 'Pacote no PC':
                ttk.Entry(row, textvariable=variable, state='readonly').pack(side='left', fill='x', expand=True)
                self.button(row, 'Escolher pasta (browse)', self.choose_root,
                            'Abre a seleção de uma pasta local. O caminho do Windows pode conter acentos; '
                            'somente os nomes digitados para o repositório são limitados a ASCII.').pack(side='left', padx=4)
            else:
                check = row.register(lambda proposed, f=field: validate_entry(f, proposed))
                entry = ttk.Entry(row, textvariable=variable, validate='key',
                                  validatecommand=(check, '%P'))
                entry.pack(side='left', fill='x', expand=True)
                Tooltip(entry, f'{field}: este campo bloqueia caracteres inválidos ao digitar. '
                        'O nome obrigatório Protótipo V0.0 é permitido como exceção.')
        self.button(header, '1. Carregar GitHub (clone)', self.load,
                    'Cria uma cópia temporária da branch do GitHub. Não altera arquivos locais '
                    'nem envia nada ao repositório.').pack(anchor='w', pady=(8, 2))

        lists = ttk.Frame(self.app, padding=(10, 3))
        lists.pack(fill='both', expand=True)
        self.local = self.tree(lists, 'Pacote no computador · escolha pasta ou arquivo', 0)
        self.remote = self.tree(lists, 'Branch do GitHub · escolha pasta ou arquivo', 1)

        actions = ttk.LabelFrame(self.app, text='Operações', padding=8)
        actions.pack(fill='x', padx=10, pady=4)
        specs = (
            ('Comparar seleção (diff)', self.compare, 'Compara conteúdo do pacote e da cópia temporária do GitHub. Não modifica arquivos.'),
            ('Preparar envio (add)', self.upload, 'Copia somente a seleção local para a pasta de destino e prepara as alterações. Ainda não envia.'),
            ('Substituição completa (rm + add)', self.replace, 'Prepara exclusão dos arquivos atuais da branch e inclusão do pacote na pasta escolhida. Ainda não envia.'),
            ('Baixar seleção (clone/copy)', self.download, 'Copia os arquivos selecionados na árvore remota para uma pasta escolhida no PC.'),
            ('Criar pasta (add)', self.mkdir, 'Cria uma pasta na cópia temporária com .gitkeep para que o Git a armazene.'),
            ('Mover seleção (mv)', self.move, 'Move as pastas ou arquivos selecionados para outra pasta do repositório na cópia temporária.'),
            ('Excluir seleção (rm)', self.delete, 'Prepara a exclusão da seleção remota. Nada é excluído do GitHub antes do commit e push.'),
            ('Prévia (status/diff)', self.preview, 'Mostra todas as inclusões, alterações, movimentos e exclusões preparados.'),
            ('2. Confirmar envio (commit/push)', self.publish, 'Após confirmação, registra as alterações em um commit e envia para a branch. Não usa force push.'),
        )
        for i, (title, fn, tip) in enumerate(specs):
            actions.columnconfigure(i % 3, weight=1)
            self.button(actions, title, fn, tip).grid(row=i // 3, column=i % 3,
                                                       sticky='ew', padx=3, pady=3)

        progress_row = ttk.Frame(self.app, padding=(10, 2))
        progress_row.pack(fill='x')
        self.progress_label = tk.StringVar(value='Pronto para carregar o repositório.')
        ttk.Label(progress_row, textvariable=self.progress_label, width=42).pack(side='left')
        self.progress = ttk.Progressbar(progress_row, mode='indeterminate', maximum=100)
        self.progress.pack(side='left', fill='x', expand=True, padx=8)
        ttk.Label(self.app, text='Selecione pastas ou arquivos com Ctrl/Shift. Expanda as pastas pela seta. '
                  'As alterações ficam na cópia temporária até Confirmar envio.', padding=(10, 3)).pack(anchor='w')
        self.log = tk.Text(self.app, height=12, wrap='none')
        self.log.pack(fill='both', expand=True, padx=10, pady=(3, 10))
        self.app.protocol('WM_DELETE_WINDOW', self.close)

    def button(self, parent, title, fn, help_text):
        button = ttk.Button(parent, text=title, command=lambda: self.guard(fn))
        self.buttons.append(button)
        Tooltip(button, help_text)
        return button

    def tree(self, parent, title, column):
        frame = ttk.LabelFrame(parent, text=title, padding=3)
        frame.grid(row=0, column=column, sticky='nsew', padx=4)
        parent.columnconfigure(column, weight=1)
        parent.rowconfigure(0, weight=1)
        box = ttk.Treeview(frame, show='tree', selectmode='extended')
        box.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=box.yview)
        scroll.pack(side='right', fill='y')
        box.configure(yscrollcommand=scroll.set)
        return box

    @staticmethod
    def populate(box, paths):
        box.delete(*box.get_children())
        for full_name in sorted(paths, key=lambda p: (p.casefold(), p)):
            parts = PurePosixPath(full_name).parts
            parent = ''
            for depth in range(len(parts) - 1):
                folder = '/'.join(parts[:depth + 1])
                iid = 'd:' + folder
                if not box.exists(iid):
                    box.insert(parent, 'end', iid=iid, text=parts[depth] + '/',
                               values=(folder, 'folder'), open=True)
                parent = iid
            file_id = 'f:' + full_name
            box.insert(parent, 'end', iid=file_id, text=parts[-1],
                       values=(full_name, 'file'))

    @staticmethod
    def selected(box, expand=False):
        chosen = []
        for item in box.selection():
            path, kind = box.item(item, 'values')
            if kind == 'file' or not expand:
                chosen.append(path + ('/' if kind == 'folder' else ''))
                continue
            def descendants(node):
                for child in box.get_children(node):
                    values = box.item(child, 'values')
                    if values[1] == 'file':
                        chosen.append(values[0])
                    else:
                        descendants(child)
            descendants(item)
        unique = sorted(set(chosen), key=lambda item: (item.count('/'), item))
        if expand:
            return unique
        return [item for item in unique
                if not any(parent.endswith('/') and item.startswith(parent)
                           for parent in unique if parent != item)]

    def write(self, message):
        self.log.delete('1.0', 'end')
        self.log.insert('end', message)
        self.log.see('end')

    def set_busy(self, description):
        self.busy = True
        self.progress_label.set(description)
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        for button in self.buttons:
            button.state(['disabled'])

    def finish(self, label='Pronto.'):
        self.progress.stop()
        self.progress.configure(mode='determinate', value=100)
        self.progress_label.set(label)
        self.busy = False
        self.background = False
        for button in self.buttons:
            button.state(['!disabled'])
        self.app.after(1100, lambda: self.progress.configure(value=0) if not self.busy else None)

    def guard(self, action):
        if self.busy:
            return
        self.set_busy('Preparando operação...')
        try:
            action()
        except Exception as exc:
            self.write('FALHA: ' + str(exc))
            messagebox.showerror('BLAZE GitHub', str(exc), parent=self.app)
            self.finish('Falha. Confira a mensagem abaixo.')
        else:
            if not self.background:
                self.finish()

    def run_async(self, description, operation, success):
        """Git e cópia de arquivos fora da thread do Tk; animação continua visível."""
        self.background = True
        self.progress_label.set(description)
        def worker():
            try:
                result = operation()
                error = None
            except Exception as exc:
                result, error = None, exc
            def complete():
                if error is not None:
                    self.write('FALHA: ' + str(error))
                    messagebox.showerror('BLAZE GitHub', str(error), parent=self.app)
                    self.finish('Falha. Confira a mensagem abaixo.')
                    return
                try:
                    success(result)
                except Exception as exc:
                    self.write('FALHA: ' + str(exc))
                    messagebox.showerror('BLAZE GitHub', str(exc), parent=self.app)
                    self.finish('Falha. Confira a mensagem abaixo.')
                else:
                    self.finish('Operação concluída.')
            self.app.after(0, complete)
        threading.Thread(target=worker, daemon=True).start()

    def require(self):
        if not self.session:
            raise RuntimeError('Clique primeiro em Carregar GitHub (clone).')
        return self.session

    def validate_settings(self, author=False):
        for field, value in (('Repositório', self.url.get()), ('Branch', self.branch.get()),
                             ('Pasta no GitHub', self.folder.get())):
            if not value.strip() or not validate_entry(field, value):
                raise ValueError(f'{field}: remova acentos e caracteres especiais inválidos.')
        safe_path(self.folder.get())
        branch_check = subprocess.run(['git', 'check-ref-format', '--branch', self.branch.get()],
                                      capture_output=True, encoding='utf-8', errors='replace')
        if branch_check.returncode:
            raise ValueError('Branch inválida para o Git: ' + self.branch.get())
        if author:
            for field, value in (('Nome para commit', self.name.get()),
                                 ('E-mail para commit', self.email.get())):
                if not value.strip() or not validate_entry(field, value):
                    raise ValueError(f'{field}: preencha usando caracteres ASCII válidos.')

    def choose_root(self):
        folder = filedialog.askdirectory(initialdir=self.root.get(), parent=self.app)
        if folder:
            self.root.set(folder)
            self.populate_local()

    def populate_local(self):
        root = Path(self.root.get())
        self.populate(self.local, [p.as_posix() for p in RepoSession.all_local(self, root)] if root.is_dir() else [])

    def populate_remote(self):
        self.populate(self.remote, self.session.tracked() if self.session else [])

    def load(self):
        self.validate_settings()
        url, branch = self.url.get().strip(), self.branch.get().strip()
        old_session = self.session
        def work():
            return RepoSession(url, branch)
        def done(new_session):
            self.session = new_session
            if old_session:
                old_session.close()
            self.populate_local()
            self.populate_remote()
            self.write(f'Branch {branch}: {len(new_session.tracked())} arquivos. '
                       f'Destino para envio: {self.folder.get()}/. Selecione arquivos ou pastas.')
        self.run_async('Clonando a branch e montando as árvores...', work, done)

    def compare(self):
        session = self.require()
        self.validate_settings()
        files = [Path(p) for p in self.selected(self.local, expand=True)]
        root, folder = Path(self.root.get()), self.folder.get()
        self.run_async('Comparando os arquivos selecionados...',
                       lambda: session.compare(root, files, folder), self.write)

    def upload(self):
        session = self.require()
        self.validate_settings()
        files = [Path(p) for p in self.selected(self.local, expand=True)]
        if not files:
            raise ValueError('Selecione arquivos ou pastas na árvore da esquerda.')
        root, folder = Path(self.root.get()), self.folder.get()
        def done(_):
            self.populate_remote()
            self.write(session.summary())
        self.run_async('Preparando arquivos para envio (add)...',
                       lambda: session.send(root, files, folder), done)

    def replace(self):
        session = self.require()
        self.validate_settings()
        root, folder = Path(self.root.get()), self.folder.get()
        files = session.all_local(root)
        if not files:
            raise ValueError('Nenhum arquivo publicável foi encontrado na pasta local.')
        count = len(session.tracked())
        if not messagebox.askyesno('Preparar substituição',
                f'Preparar exclusão de {count} arquivos e inclusão de {len(files)} '
                f'arquivos em {folder}/? O GitHub ainda não será modificado.', parent=self.app):
            return
        def done(_):
            self.populate_remote()
            self.write(session.summary())
        self.run_async('Preparando substituição (rm + add)...',
                       lambda: session.send(root, files, folder, replace=True), done)

    def download(self):
        session = self.require()
        names = self.selected(self.remote, expand=True)
        if not names:
            raise ValueError('Selecione arquivos ou pastas na árvore da direita.')
        folder = filedialog.askdirectory(title='Onde baixar a seleção?', parent=self.app)
        if folder:
            self.run_async('Baixando arquivos selecionados...',
                           lambda: session.download(names, Path(folder)),
                           lambda _: self.write(f'{len(names)} arquivos copiados para {folder}.'))

    def mkdir(self):
        session = self.require()
        dialog = PathDialog(self.app, 'Criar pasta (add)', 'Caminho da nova pasta:',
                            self.folder.get() + '/nova_pasta')
        if dialog.result:
            self.run_async('Criando pasta e preparando .gitkeep...',
                           lambda: session.mkdir(dialog.result),
                           lambda _: (self.populate_remote(), self.write(session.summary())))

    def move(self):
        session = self.require()
        names = self.selected(self.remote)
        if not names:
            raise ValueError('Selecione arquivos ou pastas na árvore da direita.')
        dialog = PathDialog(self.app, 'Mover seleção (mv)', 'Pasta de destino:', self.folder.get())
        if dialog.result:
            self.run_async('Movendo seleção...',
                           lambda: session.move(names, dialog.result),
                           lambda _: (self.populate_remote(), self.write(session.summary())))

    def delete(self):
        session = self.require()
        names = self.selected(self.remote)
        if not names:
            raise ValueError('Selecione arquivos ou pastas na árvore da direita.')
        if messagebox.askyesno('Preparar exclusão',
                f'Preparar exclusão de {len(names)} itens? O GitHub só muda após commit/push.',
                parent=self.app):
            self.run_async('Preparando exclusão (rm)...',
                           lambda: session.remove(names),
                           lambda _: (self.populate_remote(), self.write(session.summary())))

    def preview(self):
        session = self.require()
        self.run_async('Calculando status e diferenças...', session.summary, self.write)

    def publish(self):
        session = self.require()
        self.validate_settings(author=True)
        summary = session.summary()
        if summary == 'Nenhuma alteração pendente.':
            raise ValueError(summary)
        self.write(summary)
        if not messagebox.askyesno('Confirmar commit e push',
                'Revise a prévia. Criar o commit e enviar estas mudanças ao GitHub?', parent=self.app):
            return
        author, email = self.name.get(), self.email.get()
        def done(_):
            self.write('Revisão enviada com sucesso.\n\n' + summary)
        self.run_async('Criando commit e enviando (push)...',
                       lambda: session.publish(author, email), done)

    def close(self):
        if self.busy:
            messagebox.showinfo('Operação em andamento', 'Aguarde o término antes de fechar.', parent=self.app)
            return
        if self.session:
            self.session.close()
        self.app.destroy()


if __name__ == '__main__':
    Window().app.mainloop()
