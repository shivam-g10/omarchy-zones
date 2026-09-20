#!/usr/bin/env python3
"""Exercise the actual C++ editor widgets on the private native Wayland seat."""
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from common import ARTIFACTS, Input, geometry, get, info, place, require, wait_for
from lab import LAB, ROOT, environment, ctl
from measure import sample

TITLE = 'Omarchy Zones native check'
SENTINEL = 'Zones editor sentinel'
ARTIFACTS = ROOT / 'evidence/editor-fixes'
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def reports(log):
    return [json.loads(line.split('AUTOMATION ', 1)[1]) for line in log.read_text().splitlines()
            if 'AUTOMATION ' in line]


def refresh(device, log):
    count = len(reports(log))
    device.key(88, True)
    device.key(88, False)
    return wait_for(lambda: reports(log)[-1] if len(reports(log)) > count else None)


def click(device, point, offset):
    device.move(point['x'] + offset[0], point['y'] + offset[1])
    device.button(True)
    device.button(False)


def numeric(device, point, offset, value):
    click(device, point, offset)
    device.key(29, True)
    device.key(30, True)
    device.key(30, False)
    device.key(29, False)
    for digit in str(value):
        code = 11 if digit == '0' else int(digit) + 1
        device.key(code, True)
        device.key(code, False)
    device.key(28, True)
    device.key(28, False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true')
    args = parser.parse_args()
    env = environment()
    require(env['XDG_RUNTIME_DIR'].startswith('/tmp/ozr-') and not info(), 'Private empty lab required')
    config = Path(env['XDG_CONFIG_HOME']) / 'omarchy-zones/zones.conf'
    theme = Path(env['XDG_STATE_HOME']) / 'omarchy/current/theme'
    require(config.resolve().is_relative_to(LAB.resolve()) and theme.resolve().is_relative_to(LAB.resolve()), 'Fixture escaped lab')
    config.parent.mkdir(parents=True, exist_ok=True)
    theme.mkdir(parents=True, exist_ok=True)
    # Mirror the configured font alias into the private environment so native
    # previews use the same family as the user's shell without editing it.
    source_fonts = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'fontconfig'
    if source_fonts.is_dir():
        shutil.copytree(source_fonts, Path(env['XDG_CONFIG_HOME'])/'fontconfig', dirs_exist_ok=True)
    user_fonts = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'fonts'
    private_fonts = Path(env['XDG_DATA_HOME']) / 'fonts'
    if user_fonts.is_dir() and not private_fonts.exists():
        # Fontconfig also needs the user-installed faces behind the alias.
        # Read-only consumers use this link; no test writes inside it.
        private_fonts.symlink_to(user_fonts, target_is_directory=True)
    previous = {p: p.read_bytes() if p.exists() else None for p in [config, theme/'colors.toml', theme/'shell.toml']}
    config.write_text('omarchy-zones-v2\nprofile "Split"\nWAYLAND-1 0 0 640 900\nWAYLAND-1 640 0 640 900\n')
    for name in ['colors.toml', 'shell.toml']:
        shutil.copyfile(Path.home()/'.local/state/omarchy/current/theme'/name, theme/name)
    original_colors = (theme/'colors.toml').read_text()
    original_shell = (theme/'shell.toml').read_text()
    processes = []
    result = {'passed': False, 'checks': []}
    log = ARTIFACTS/'editor-native.log'
    try:
        with (ARTIFACTS/'editor-sentinel.log').open('w') as output:
            sentinel = subprocess.Popen([str(ROOT/'build/tests/native-window'), SENTINEL], env=env, stdout=output, stderr=output)
        processes.append(sentinel)
        wait_for(lambda: get(SENTINEL))
        place(SENTINEL, 1000, 700, 250, 180)
        unchanged = geometry(get(SENTINEL))
        with log.open('w') as output:
            editor = subprocess.Popen([str(ROOT/'build/editor-native-check')], env=env, stdout=output, stderr=output)
        processes.append(editor)
        wait_for(lambda: get(TITLE), timeout=10)
        place(TITLE, 40, 40, 1160, 740)
        require(not get(TITLE)['xwayland'], 'Editor must be native Wayland')
        with Input() as device:
            def ready():
                state = refresh(device, log)
                return state if (state['width'], state['height']) == (1160, 740) and state['theme']['borderWidth'] == 3 else None
            state = wait_for(ready)
            offset = get(TITLE)['at']
            require(state['fieldsDoNotOverlapHelp'], 'Numeric controls overlap help text')
            require(state['profileIconFits'], 'Profile thumbnail is clipped by its control')
            require(state['theme']['borderColors'] == ['72f1ffff', 'ffc857ff'] and state['theme']['borderAngle'] == 45
                    and state['theme']['rounding'] == 12, state)
            result['checks'].append({'name': 'native live border and theme controls', 'state': state, 'passed': True})
            numeric(device, state['input'], offset, 768)
            state = refresh(device, log)
            require(state['rectangles'] == [[0, 0, 768, 900], [768, 0, 512, 900]], state)
            require(geometry(get(SENTINEL)) == unchanged, 'Numeric editing moved another window')
            result['checks'].append({'name': 'exact numeric shared boundary', 'passed': True})

            # A second launch must target the existing unsaved editor, even
            # when it is behind another real native window.
            saved_before_relaunch = config.read_bytes()
            place(SENTINEL, 1000, 700, 250, 180)
            duplicates = [subprocess.Popen([str(ROOT/'build/omarchy-zones-editor')], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(3)]
            processes.extend(duplicates)
            require(all(p.wait(timeout=6) == 0 for p in duplicates), 'Secondary launch failed')
            wait_for(lambda: json.loads(ctl('-j', 'activewindow')).get('pid') == editor.pid)
            require(len([c for c in info() if c['class'] == 'omarchy-zones-editor']) == 1,
                    'Relaunch created another editor window')
            state = refresh(device, log)
            require(state['rectangles'] == [[0, 0, 768, 900], [768, 0, 512, 900]],
                    'Relaunch discarded unsaved edits')
            require(config.read_bytes() == saved_before_relaunch, 'Relaunch saved or reloaded profiles')
            require(geometry(get(SENTINEL)) == unchanged, 'Relaunch moved another window')
            result['checks'].append({'name': 'concurrent relaunch activates one editor and preserves unsaved changes', 'passed': True})

            click(device, state['newProfile'], offset)
            wait_for(lambda: get('New profile'))
            place(SENTINEL, 1000, 700, 250, 180)
            duplicate = subprocess.Popen([str(ROOT/'build/omarchy-zones-editor')], env=env,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(duplicate)
            require(duplicate.wait(timeout=6) == 0, 'Relaunch during dialog failed')
            wait_for(lambda: json.loads(ctl('-j', 'activewindow')).get('title') == 'New profile')
            require(len([c for c in info() if c['pid'] == editor.pid]) == 2,
                    'Relaunch replaced or duplicated the active dialog')
            device.key(30, True); device.key(30, False)
            subprocess.run(['grim', str(ARTIFACTS/'editor-dialog.png')], env=env, check=True)
            device.key(1, True); device.key(1, False)
            wait_for(lambda: not any(c['title'] == 'New profile' for c in info()))
            # The compositor may restore the sentinel's prior focus when a
            # modal closes. Resume editing through an ordinary native click.
            click(device, {'x': 80, 'y': 38}, offset)
            state = refresh(device, log)
            require(state['boundaryValue'] == 768, 'Closing dialog changed unsaved geometry')
            result['checks'].append({'name': 'relaunch preserves active modal dialog', 'passed': True})

            click(device, state['profile'], offset)
            time.sleep(.15)
            subprocess.run(['grim', str(ARTIFACTS/'editor-profile-popup.png')], env=env, check=True)
            device.key(1, True); device.key(1, False)
            state = refresh(device, log)
            result['checks'].append({'name': 'profile thumbnail fits and native popup opens', 'passed': True})
            point = state['boundary']
            device.move(point['x']+offset[0], point['y']+offset[1])
            device.button(True)
            for delta in range(5, 46, 5): device.move(point['x']+offset[0]+delta, point['y']+offset[1])
            device.button(False)
            state = refresh(device, log)
            left, right = state['rectangles']
            require(left[2] > 768 and left[2] == right[0] and left[2]+right[2] == 1280, state)
            require(geometry(get(SENTINEL)) == unchanged, 'Mouse editing moved another window')
            result['checks'].append({'name': 'mouse shared boundary', 'state': state, 'passed': True})
            click(device, state['save'], offset)
            wait_for(lambda: f'WAYLAND-1 0 0 {left[2]} 900' in config.read_text())
            require(config.stat().st_mode & 0o777 == 0o600, 'Saved file permissions are not private')
            require(geometry(get(SENTINEL)) == unchanged, 'Saving moved another window')
            result['checks'].append({'name': 'save only definitions and preserve existing window', 'passed': True})
            subprocess.run(['grim', str(ARTIFACTS/'editor-native.png')], env=env, check=True)
            (theme/'colors.toml').write_text(original_colors.replace('#67D4E8', '#C792EA'))
            (theme/'shell.toml').write_text(original_shell.replace('normal-fill-alpha   = 0.04', 'normal-fill-alpha   = 0.16'))
            def changed():
                current = refresh(device, log)
                return current if current['theme']['accent'] == 'c792eaff' and current['theme']['controlFill'] == .16 else None
            state = wait_for(changed, timeout=5)
            require(state['fieldsDoNotOverlapHelp'], 'Theme refresh caused overlapping controls')
            require(geometry(get(SENTINEL)) == unchanged, 'Theme refresh moved another window')
            result['checks'].append({'name': 'event-driven palette and shell control refresh', 'state': state, 'passed': True})
            subprocess.run(['grim', str(ARTIFACTS/'editor-theme-event.png')], env=env, check=True)
            # Omarchy's no-gaps mode also removes borders. Zero must disable
            # canvas strokes instead of selecting Qt's one-pixel cosmetic pen.
            ctl('eval', 'hl.config({general={border_size=0},decoration={rounding=0}})')
            (theme/'colors.toml').write_text(original_colors)
            (theme/'shell.toml').write_text(original_shell)
            def no_borders():
                current = refresh(device, log)
                return current if current['theme']['borderWidth'] == 0 and current['theme']['rounding'] == 0 else None
            state = wait_for(no_borders, timeout=5)
            require(geometry(get(SENTINEL)) == unchanged, 'Border refresh moved another window')
            subprocess.run(['grim', str(ARTIFACTS/'editor-no-borders.png')], env=env, check=True)
            result['checks'].append({'name': 'live zero-width border and rounding', 'state': state, 'passed': True})
            ctl('eval', 'hl.config({general={border_size=3},decoration={rounding=12}})')
            (theme/'colors.toml').write_text(original_colors)
            wait_for(lambda: refresh(device, log)['theme']['borderWidth'] == 3)
        editor.terminate()
        editor.wait(timeout=4)
        # Also open the exact distributable, without the inspection shortcut.
        with (ARTIFACTS/'editor-distributable.log').open('w') as output:
            production = subprocess.Popen([str(ROOT/'build/omarchy-zones-editor')], env=env, stdout=output, stderr=output)
        processes.append(production)
        wait_for(lambda: get('Omarchy Zones'))
        place('Omarchy Zones', 40, 40, 1160, 740)
        require(not get('Omarchy Zones')['xwayland'], 'Distributable is not native Wayland')
        time.sleep(.5)
        subprocess.run(['grim', str(ARTIFACTS/'editor-distributable.png')], env=env, check=True)
        require(geometry(get(SENTINEL)) == unchanged, 'Opening distributable moved another window')
        result['checks'].append({'name': 'exact distributable opens natively', 'passed': True})
        if args.measure:
            idle = sample([production.pid, sentinel.pid, int((LAB/'pid').read_text())], 20, 'C++ distributable editor open idle')
            (ARTIFACTS/'editor-idle.json').write_text(json.dumps(idle, indent=2)+'\n')
            result['idle'] = idle
        result['passed'] = True
    finally:
        ctl('eval', 'hl.config({general={border_size=3},decoration={rounding=12}})')
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=4)
        for path, contents in previous.items():
            if contents is None: path.unlink(missing_ok=True)
            else: path.write_bytes(contents)
        (ARTIFACTS/'editor-native-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': result['passed'], 'checks': [row['name'] for row in result['checks']]}, indent=2))


if __name__ == '__main__': main()
