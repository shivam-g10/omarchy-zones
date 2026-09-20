#!/usr/bin/env python3
"""Validate the production plugin using native windows in the isolated compositor.

This script never addresses the parent compositor or changes production theme or
zone files. Run lab.py start first; the lab must have no other test clients.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from common import ARTIFACTS, Input, geometry, get, info, place, require, status, wait_for
from lab import LAB, ROOT, ctl, environment
from measure import sample

PLUGIN = ROOT / 'build/omarchy-zones.so'
CLIENT = ROOT / 'build/tests/native-window'
TITLE = 'Zones hardening target'
SENTINEL = 'Zones hardening sentinel'
META, SHIFT, ESC = 125, 42, 1


def check_idle_state():
    state = status()
    require(state['overlay'] == 'hidden' and state['picker'] == 'hidden', state)
    require(state['retained-target'] == 'no' and state['pending-snap'] == 'no', state)
    require(state['pending-refresh'] == 'no' and state['text-textures'] == '0', state)
    return state


def save_json(name, value):
    (ARTIFACTS / name).write_text(json.dumps(value, indent=2) + '\n')


def screenshot(name):
    subprocess.run(['grim', str(ARTIFACTS / name)], env=environment(), check=True, timeout=5)


def fixture(monitor):
    return (f'omarchy-zones-v2\nprofile "Split"\n'
            f'{monitor} 0 0 640 900\n{monitor} 640 0 640 900\n'
            f'profile "Main + side"\n{monitor} 0 0 853 900\n{monitor} 853 0 427 900\n'
            f'profile "Three columns"\n{monitor} 0 0 426 900\n'
            f'{monitor} 426 0 427 900\n{monitor} 853 0 427 900\n')


def miniature_right_target():
    """Middle profile, right zone, from the actual production picker geometry."""
    card_width, gap, panel_padding = 152, 12, 14
    panel_width = 2 * panel_padding + 3 * card_width + 2 * gap
    card_x = (1280 - panel_width) / 2 + panel_padding + card_width + gap
    card_y, thumbnail_height = 18 + 40, 112 - 10 - 23
    scale = min((card_width - 10) / 1280, (thumbnail_height - 10) / 900)
    origin_x = card_x + (card_width - 1280 * scale) / 2
    origin_y = card_y + (thumbnail_height - 900 * scale) / 2
    return origin_x + (853 + 427 / 2) * scale, origin_y + 450 * scale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true', help='Add paired 20-second warm idle samples.')
    args = parser.parse_args()
    env = environment()
    require(env['XDG_RUNTIME_DIR'].startswith('/tmp/ozr-'), 'Refusing a non-isolated runtime')
    for variable in ['XDG_CONFIG_HOME', 'XDG_STATE_HOME']:
        require(Path(env[variable]).resolve().is_relative_to(LAB.resolve()), variable)
    monitors = json.loads(ctl('-j', 'monitors'))
    require(len(monitors) == 1 and monitors[0]['width'] == 1280 and monitors[0]['height'] == 900,
            monitors)
    require(monitors[0]['scale'] == 1 and monitors[0]['reserved'] == [0, 0, 0, 0], monitors)
    require(not info(), 'The isolated compositor already has clients; finish other checks first.')
    require(PLUGIN.is_file() and CLIENT.is_file(), 'Build the production plugin and native client first.')
    require(not json.loads(ctl('-j', 'plugin', 'list')), 'The isolated compositor already has a loaded plugin.')

    zone_path = Path(env['XDG_CONFIG_HOME']) / 'omarchy-zones/zones.conf'
    zone_path.parent.mkdir(parents=True, exist_ok=True)
    require(not zone_path.is_symlink(), 'Refusing an existing zone-file symlink')
    original = zone_path.read_bytes() if zone_path.exists() else None
    theme_path = Path(env['XDG_STATE_HOME']) / 'omarchy/current/theme'
    theme_path.mkdir(parents=True, exist_ok=True)
    source_theme = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy/current/theme'
    theme_backup = {}
    for name in ['colors.toml', 'shell.toml']:
        target = theme_path / name
        require(not target.is_symlink(), 'Refusing an existing theme-file symlink')
        theme_backup[name] = target.read_bytes() if target.exists() else None
    content = fixture(monitors[0]['name'])
    clients, logs, rows = [], [], []
    result = {'passed': False, 'checks': rows, 'limits':
              'Native nested Wayland at 1280x900, scale 1. No physical monitor, fractional scaling, '
              'multi-monitor, session-lock or production desktop interaction in this run.'}
    loaded = False
    configured_override = False

    def write_fixture(text=content):
        if zone_path.exists():
            zone_path.unlink()
        zone_path.write_text(text)

    def close_clients():
        for client in clients:
            if client.poll() is None:
                client.terminate()
                client.wait(timeout=4)
        clients.clear()
        wait_for(lambda: not info())

    try:
        write_fixture()
        for name in theme_backup:
            if (source_theme / name).is_file():
                shutil.copyfile(source_theme / name, theme_path / name)
        require('ok' in ctl('plugin', 'load', str(PLUGIN)), 'Plugin load failed')
        loaded = True
        initial = status()
        require(initial['profiles'] == '3', initial)
        require(initial['theme-border-width'] == '3' and initial['theme-rounding'] == '12', initial)
        require(initial['theme-border'] == 'ff72f1ff ffffc857 45deg', initial)
        rows.append({'name': 'native theme tokens', 'passed': True, 'status': initial})

        for title in [TITLE, SENTINEL]:
            log = (ARTIFACTS / (title.replace(' ', '-') + '.log')).open('w')
            logs.append(log)
            clients.append(subprocess.Popen([str(CLIENT), title], env=env, stdout=log, stderr=log))
            wait_for(lambda title=title: get(title))
            require(not get(title)['xwayland'], 'The test window is not native Wayland')
            place(title)
        place(SENTINEL, 900, 600, 300, 180)
        unchanged = geometry(get(SENTINEL))

        with Input() as device:
            place(TITLE)
            device.key(META, True)
            device.key(SHIFT, True)
            device.move(700, 450)
            require(status()['overlay'] == 'hidden', 'Modifiers alone displayed the overlay')
            device.key(SHIFT, False)
            device.key(META, False)
            rows.append({'name': 'hotkey alone stays hidden', 'passed': True})

            def drag(name, destination, expected=None, *, shift=True, titlebar=False,
                     release_shift=False, press_escape=False, screenshot_name=None,
                     expected_overlay=None):
                place(TITLE)
                before = status()
                device.move(430, 258 if titlebar else 450)
                if not titlebar:
                    device.key(META, True)
                if shift:
                    device.key(SHIFT, True)
                device.button(True)
                device.move(600, 470)
                device.move(*destination)
                during = status()
                overlay = expected_overlay or ('visible' if shift else 'hidden')
                require(during['overlay'] == overlay, during)
                if screenshot_name:
                    screenshot(screenshot_name)
                escape_state = None
                if press_escape:
                    device.key(ESC, True)
                    device.key(ESC, False)
                    escape_state = status()
                    if escape_state['drag-active'] == 'yes':
                        require(escape_state['overlay'] == 'visible', escape_state)
                    else:
                        expected = None  # Native compositor behavior, recorded below.
                if release_shift:
                    device.key(SHIFT, False)
                    require(status()['overlay'] == 'hidden', status())
                device.button(False)
                if shift and not release_shift:
                    device.key(SHIFT, False)
                if not titlebar:
                    device.key(META, False)
                time.sleep(.15)
                after = check_idle_state()
                current = get(TITLE)
                require(int(after['snaps']) == int(before['snaps']) + int(expected is not None), after)
                if expected is not None:
                    require(current['at'] + current['size'] == expected, current)
                else:
                    require(current['size'] == [600, 400], current)
                require(geometry(get(SENTINEL)) == unchanged, 'An unrelated native window changed')
                row = {'name': name, 'passed': True, 'during': during, 'after': after,
                       'window': geometry(current), 'sentinel_unchanged': True}
                if escape_state is not None:
                    row['after_escape'] = escape_state
                    row['escape_behavior'] = ('Native drag remained active; plugin did not cancel.'
                        if escape_state['drag-active'] == 'yes' else 'Hyprland ended its native drag.')
                rows.append(row)

            drag('full desktop zone snap', (1000, 440), [640, 0, 640, 900],
                 screenshot_name='plugin-native-overlay.png')
            drag('native titlebar snap', (210, 440), [0, 0, 640, 900], titlebar=True)
            drag('profile miniature selection and drop', miniature_right_target(), [853, 0, 427, 900],
                 screenshot_name='plugin-profile-miniature.png')
            require(status()['profile'] == 'Main + side', status())
            drag('ordinary native dragging', (1000, 440), shift=False)
            drag('modifier release cancels snap', (1000, 440), release_shift=True)
            drag('Esc has no plugin cancellation handler', (1000, 440), [853, 0, 427, 900], press_escape=True)

            # A runtime-only change in this private compositor exercises the
            # complete native gradient rather than a palette approximation.
            configured_override = True
            ctl('eval', 'hl.config({general={col={active_border={colors={"rgba(ff000080)",'
                '"rgba(00ff0040)","rgba(0000ffff)"},angle=135}}}})')
            drag('three native gradient stops with alpha', (1000, 440), [853, 0, 427, 900],
                 screenshot_name='plugin-three-stop-alpha.png')
            require(rows[-1]['during']['theme-border'] == '80ff0000 4000ff00 ff0000ff 135deg', rows[-1])
            ctl('reload')
            require(not ctl('configerrors'), 'Private lab config failed to reload')
            configured_override = False
            require(status()['theme-border'] == 'ff72f1ff ffffc857 45deg', status())

            # A malicious special file must not block Hyprland's input thread.
            zone_path.unlink()
            os.mkfifo(zone_path, 0o600)
            start = time.monotonic()
            drag('FIFO profile rejected without blocking', (1000, 440), expected_overlay='hidden')
            rows[-1]['elapsed_seconds'] = time.monotonic() - start
            require('regular file' in status()['error'], status())
            write_fixture('omarchy-zones-v2\nprofile "Broken"\n' + monitors[0]['name'] + ' 0 0 640 900\n'
                          + monitors[0]['name'] + ' 200 0 640 900\n')
            drag('overlapping profile rejected without snapping', (1000, 440), expected_overlay='hidden')
            require('overlap' in status()['error'], status())
            write_fixture()
            drag('valid profile recovers after rejected input', (1000, 440), [853, 0, 427, 900])
            for iteration in range(5):
                drag(f'repeated drag cleanup {iteration + 1}', (1000, 440), [853, 0, 427, 900])

        close_clients()
        if args.measure:
            pid = int((LAB / 'pid').read_text())
            print('Sampling warm plugin idle for 20 seconds.', flush=True)
            loaded_sample = sample([pid], 20, 'C++ plugin loaded after native gestures; no test clients or input helper')
            save_json('plugin-idle-loaded.json', loaded_sample)
            result['idle_loaded'] = loaded_sample
            require('ok' in ctl('plugin', 'unload', str(PLUGIN)), 'Plugin unload failed')
            loaded = False
            print('Sampling unloaded baseline for 20 seconds.', flush=True)
            unloaded_sample = sample([pid], 20, 'Same compositor after plugin unload; no test clients or input helper')
            save_json('plugin-idle-unloaded.json', unloaded_sample)
            result['idle_unloaded'] = unloaded_sample
            result['idle_incremental'] = {key: loaded_sample['total'][key] - unloaded_sample['total'][key]
                                          for key in ['rss_kib', 'pss_kib', 'private_kib']}
        else:
            require('ok' in ctl('plugin', 'unload', str(PLUGIN)), 'Plugin unload failed')
            loaded = False
        require('ok' in ctl('plugin', 'load', str(PLUGIN)), 'Plugin reload failed')
        loaded = True
        reloaded = check_idle_state()
        require(reloaded['snaps'] == '0' and reloaded['profiles'] == '3', reloaded)
        rows.append({'name': 'unload and reload cleanup', 'passed': True, 'status': reloaded})
        result['passed'] = True
    finally:
        close_clients()
        for log in logs:
            log.close()
        if loaded:
            ctl('plugin', 'unload', str(PLUGIN))
        if configured_override:
            ctl('reload')
        if zone_path.exists():
            zone_path.unlink()
        if original is not None:
            zone_path.write_bytes(original)
        for name, value in theme_backup.items():
            path = theme_path / name
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
        save_json('plugin-native-check.json', result)
    print(json.dumps({'passed': result['passed'], 'checks': len(rows),
                      'names': [row['name'] for row in rows]}, indent=2))


if __name__ == '__main__':
    main()
