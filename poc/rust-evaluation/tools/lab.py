#!/usr/bin/env python3
"""Run an isolated native Hyprland instance without changing desktop config."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'lab'

def shell(command, env=None):
    return subprocess.check_output(command, env=env, text=True).strip()

def environment():
    result = os.environ.copy()
    result.update(json.loads((LAB / 'environment.json').read_text()))
    return result

def ctl(*args):
    return shell(['hyprctl', *args], environment())

def start():
    if (LAB / 'pid').exists():
        pid = int((LAB / 'pid').read_text())
        if Path(f'/proc/{pid}').exists():
            raise SystemExit('Lab already running')
    LAB.mkdir(parents=True, exist_ok=True)
    for name in ['runtime', 'config', 'state', 'data', 'cache']:
        (LAB / name).mkdir(mode=0o700, exist_ok=True)
    desktop = {name: json.loads(shell(['hyprctl', '-j', name])) for name in ['clients', 'activeworkspace', 'cursorpos']}
    desktop['zones_status'] = shell(['hyprctl', 'zones'])
    desktop['hashes'] = {}
    for directory in ['hypr', 'omarchy', 'omarchy-zones']:
        for file in (Path.home() / '.config' / directory).rglob('*'):
            if file.is_file():
                desktop['hashes'][str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
    (LAB / 'desktop-before.json').write_text(json.dumps(desktop, indent=2))
    config = LAB / 'hyprland.lua'
    config.write_text('''hl.config({
  general = { border_size = 3, gaps_in = 0, gaps_out = 0,
    col = {active_border = {colors = {"rgba(72f1ffff)", "rgba(ffc857ff)"}, angle = 45}, inactive_border = "rgba(26384a88)"}},
  decoration = {rounding = 12, shadow = {enabled = false}, blur = {enabled = false}},
  animations = {enabled = false},
  misc = {disable_hyprland_logo = true, disable_splash_rendering = true},
  cursor = {no_hardware_cursors = true},
  input = {follow_mouse = 1},
  xwayland = {enabled = false},
})
hl.monitor({output = "", mode = "1280x900@60", position = "0x0", scale = 1})
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), {mouse = true})
hl.bind("SUPER + SHIFT + mouse:272", hl.dsp.window.drag(), {mouse = true})
''')
    parent_runtime = os.environ['XDG_RUNTIME_DIR']
    parent_display = os.environ['WAYLAND_DISPLAY']
    if not parent_display.startswith('/'):
        parent_display = str(Path(parent_runtime) / parent_display)
    runtime = Path(tempfile.mkdtemp(prefix='ozr-'))
    variables = {
        'XDG_RUNTIME_DIR': str(runtime),
        'XDG_CONFIG_HOME': str(LAB / 'config'),
        'XDG_STATE_HOME': str(LAB / 'state'),
        'XDG_DATA_HOME': str(LAB / 'data'),
        'XDG_CACHE_HOME': str(LAB / 'cache'),
        'WAYLAND_DISPLAY': parent_display,
        'HYPRLAND_NO_SD_VARS': '1', 'HYPRLAND_NO_SD_NOTIFY': '1',
        'QT_QPA_PLATFORM': 'wayland',
    }
    (LAB / 'launch-environment.json').write_text(json.dumps(variables))
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), 'serve'])
    code = 'hl.exec_cmd(' + json.dumps(command) + ', {workspace="name:zones-rust-lab silent", float=true, no_focus=true, render_unfocused=true})'
    print(shell(['hyprctl', 'eval', code]))
    for _ in range(100):
        instances = list((runtime / 'hypr').glob('*/.socket.sock'))
        sockets = [p for p in runtime.glob('wayland-*') if p.is_socket()]
        if instances and sockets:
            variables['HYPRLAND_INSTANCE_SIGNATURE'] = instances[0].parent.name
            variables['WAYLAND_DISPLAY'] = sockets[0].name
            (LAB / 'environment.json').write_text(json.dumps(variables, indent=2))
            try:
                if json.loads(ctl('-j', 'monitors')):
                    print(ctl('configerrors'))
                    print(ctl('-j', 'monitors'))
                    return
            except subprocess.CalledProcessError:
                pass
        time.sleep(.1)
    raise SystemExit('Lab failed to initialize; inspect lab/hyprland.log')

def serve():
    env = os.environ.copy()
    env.update(json.loads((LAB / 'launch-environment.json').read_text()))
    env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    (LAB / 'pid').write_text(str(os.getpid()))
    with (LAB / 'hyprland.log').open('w') as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        os.execvpe('Hyprland', ['Hyprland', '--config', str(LAB / 'hyprland.lua')], env)

def stop():
    pid = int((LAB / 'pid').read_text())
    cmdline = Path(f'/proc/{pid}/cmdline')
    if cmdline.exists():
        if str(LAB / 'hyprland.lua').encode() not in cmdline.read_bytes():
            raise SystemExit('Refusing to stop a PID that is not this lab')
        os.kill(pid, 15)
    before = json.loads((LAB / 'desktop-before.json').read_text())
    changed = [path for path, digest in before['hashes'].items()
               if not Path(path).exists() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
    print(json.dumps({'configuration_files_checked': len(before['hashes']), 'changed': changed,
                      'installed_plugin': shell(['hyprctl', 'zones'])}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'serve', 'stop', 'ctl', 'run'])
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'start': start()
    elif args.action == 'serve': serve()
    elif args.action == 'stop': stop()
    elif args.action == 'ctl': print(ctl(*args.args))
    elif args.action == 'run': os.execvpe(args.args[0], args.args, environment())
