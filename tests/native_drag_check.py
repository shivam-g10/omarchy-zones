#!/usr/bin/env python3
"""Run only with an idle desktop on the dedicated zones-poc workspace.

Requires a native-window titled 'Zones validation A' and saved zones. Uses real
input; aborts before starting each scenario if the workspace changed.
"""
import json
import os
from pathlib import Path
import subprocess
import time
from native_driver import NativeInput, hyprctl_json

ROOT = Path(__file__).resolve().parents[1]

def lua(code):
    result = subprocess.check_output(['hyprctl', 'repl', code], text=True)
    if 'error:' in result:
        raise RuntimeError(result)

def client():
    return next(c for c in hyprctl_json('clients') if c['title'] == 'Zones validation A')

def status():
    return dict(line.split(': ', 1) for line in subprocess.check_output(['hyprctl', 'zones'], text=True).splitlines() if ': ' in line)

def geometry():
    return {key: client()[key] for key in ('at', 'size', 'floating', 'xwayland')}

def main():
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'omarchy-zones/zones.conf'
    lines = [line.split() for line in config.read_text().splitlines()[1:] if line.strip() and not line.lstrip().startswith('#')]
    if len(lines) != 2 or any(line[0] != 'DP-2' for line in lines):
        raise SystemExit('This host-specific check requires two DP-2 zones.')
    right = list(map(int, lines[1][1:]))
    if not (right[0] > 750 and right[0] < 1700 and right[1] == 0 and right[3] > 550):
        raise SystemExit('The saved layout does not contain the test path; input was not started.')
    address = client()['address']
    rows = []
    with NativeInput(workspace='zones-poc') as inp:
        for mode in ('snap', 'ordinary', 'shift-cancel', 'escape-cancel', 'titlebar', 'tiled'):
            assert hyprctl_json('activeworkspace')['name'] == 'zones-poc', 'Workspace changed; input stopped.'
            lua(f'hl.dispatch(hl.dsp.window.float({{action="enable",window="address:{address}"}}));'
                f'hl.dispatch(hl.dsp.window.resize({{x=600,y=400,window="address:{address}"}}));'
                f'hl.dispatch(hl.dsp.window.move({{x=300,y=250,window="address:{address}"}}));'
                f'hl.dispatch(hl.dsp.focus({{window="address:{address}"}}))')
            if mode == 'tiled':
                lua(f'hl.dispatch(hl.dsp.window.float({{action="disable",window="address:{address}"}}))')
            time.sleep(.35)
            before, initial = geometry(), status()
            inp.move_to(520, 282 if mode == 'titlebar' else 440)
            if mode != 'titlebar': inp.key('KEY_LEFTMETA', True)
            if mode != 'ordinary': inp.key('KEY_LEFTSHIFT', True)
            inp.button(down=True)
            inp.move_to(750, 500)
            left = status()
            inp.move_to(1700, 550)
            time.sleep(.12)
            during = status()
            if mode == 'snap':
                subprocess.run(['grim', str(ROOT / 'evidence/overlay-right.png')], check=True)
            if mode == 'shift-cancel': inp.key('KEY_LEFTSHIFT', False)
            if mode == 'escape-cancel':
                inp.key('KEY_ESC', True); inp.key('KEY_ESC', False)
            inp.button(down=False)
            if mode not in ('ordinary', 'shift-cancel'): inp.key('KEY_LEFTSHIFT', False)
            if mode != 'titlebar': inp.key('KEY_LEFTMETA', False)
            time.sleep(.4)
            final = status()
            should_snap = mode in ('snap', 'titlebar', 'tiled')
            passed = int(final['snaps']) == int(initial['snaps']) + int(should_snap)
            passed &= final['overlay'] == 'hidden'
            if should_snap:
                passed &= geometry()['at'] == right[:2] and geometry()['size'] == right[2:]
                passed &= left['target-zone'] == '1' and during['target-zone'] == '2'
            if mode == 'ordinary':
                passed &= during['overlay'] == 'hidden' and geometry()['size'] == before['size'] and geometry()['at'] != before['at']
            row = dict(mode=mode, passed=passed, before=before, left=left, during=during, after=geometry(), final=final)
            rows.append(row)
            print(mode, 'PASS' if passed else 'FAIL', row['after'], flush=True)
    (ROOT / 'evidence/native-drag.json').write_text(json.dumps(rows, indent=2) + '\n')
    if not all(row['passed'] for row in rows):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
