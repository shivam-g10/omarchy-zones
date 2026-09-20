#!/usr/bin/env python3
"""Native profile-picker validation for this host; never installs or edits config.

Run only when the desktop is idle, on workspace zones-profiles-test, with a real
Wayland native-window titled 'Zones profiles A'. The caller prepares/restores the
fixture and cleans up the test window. Every injected input command checks the
workspace. --print-fixture prints the required fixture without injecting input.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

from native_driver import NativeInput, hyprctl_json

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = 'zones-profiles-test'
TITLE = 'Zones profiles A'
MONITOR = 'DP-2'
FIXTURE = '''omarchy-zones-v2
profile "Default"
DP-2 300 150 1920 1080
profile "Split"
DP-2 0 0 1280 1414
DP-2 1280 0 1280 1414
profile "Main + side"
DP-2 0 0 1706 1414
DP-2 1706 0 854 1414
profile "Three columns"
DP-2 0 0 853 1414
DP-2 853 0 853 1414
DP-2 1706 0 854 1414
'''


def profile_rows(text):
    lines = text.splitlines()
    if not lines or lines[0] != 'omarchy-zones-v2':
        raise RuntimeError('This check requires the v2 profile fixture; no input was started.')
    result = []
    for line in lines[1:]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = shlex.split(line)
        if len(fields) == 2 and fields[0] == 'profile':
            result.append({'name': fields[1], 'zones': []})
        elif len(fields) == 5 and fields[0] == MONITOR and result:
            result[-1]['zones'].append([int(value) for value in fields[1:]])
        else:
            raise RuntimeError('The saved file is not the expected DP-2 profile fixture.')
    return result


def status():
    output = subprocess.check_output(['hyprctl', 'zones'], text=True)
    result = dict(line.split(': ', 1) for line in output.splitlines() if ': ' in line)
    required = {'profiles', 'profile', 'picker', 'text-textures', 'overlay', 'target-zone', 'snaps'}
    if not required <= result.keys():
        raise RuntimeError('The profile-picker plugin status is unavailable.')
    return result


def lua(code):
    output = subprocess.check_output(['hyprctl', 'repl', code], text=True)
    if 'error:' in output.lower():
        raise RuntimeError(output)


def geometry(client):
    return {key: client[key] for key in ('at', 'size', 'floating', 'xwayland', 'workspace', 'monitor')}


def other_geometries(address):
    return {client['address']: geometry(client) for client in hyprctl_json('clients') if client['address'] != address}


def picker_geometry(profiles):
    """Mirror the inspected four-card layout in global logical coordinates."""
    width, height = 2560, 1440
    card_width, row_height, gap, padding = 152, 112, 12, 14
    tray_width = 2 * padding + len(profiles) * card_width + (len(profiles) - 1) * gap
    tray = [(width - tray_width) / 2, 18, tray_width, 68 + row_height]
    cards = []
    for index, profile in enumerate(profiles):
        card = [tray[0] + padding + index * (card_width + gap), tray[1] + 40, card_width, row_height - 10]
        thumbnail = [card[0], card[1], card[2], card[3] - 23]
        scale = min((thumbnail[2] - 10) / width, (thumbnail[3] - 10) / height)
        origin = [thumbnail[0] + (thumbnail[2] - width * scale) / 2,
                  thumbnail[1] + (thumbnail[3] - height * scale) / 2]
        miniatures = []
        for x, y, w, h in profile['zones']:
            inset = min(1.5, w * scale / 8, h * scale / 8)
            box = [origin[0] + x * scale + inset, origin[1] + y * scale + inset,
                   w * scale - 2 * inset, h * scale - 2 * inset]
            miniatures.append(box)
        cards.append({'name': profile['name'], 'card': card, 'thumbnail': thumbnail, 'zones': miniatures})
    return {'tray': tray, 'cards': cards}


def center(box):
    return round(box[0] + box[2] / 2), round(box[1] + box[3] / 2)


class NativeProfileCheck:
    def __init__(self, output):
        self.output = output
        self.rows = []
        self.profiles = profile_rows(FIXTURE)
        self.picker = picker_geometry(self.profiles)
        self.address = None
        self.baseline = None
        self.input = None

    def guard(self):
        if hyprctl_json('activeworkspace')['name'] != WORKSPACE:
            raise RuntimeError('Workspace changed; native profile input stopped.')
        clients = hyprctl_json('clients')
        matches = [client for client in clients if client['title'] == TITLE]
        if len(matches) != 1:
            raise RuntimeError('Exactly one Zones profiles A native test window is required.')
        client = matches[0]
        if client['xwayland'] or client['workspace']['name'] != WORKSPACE:
            raise RuntimeError('The test client must be native Wayland on zones-profiles-test.')
        if self.address is not None and client['address'] != self.address:
            raise RuntimeError('The original test client disappeared or was replaced.')
        if client.get('fullscreen', 0) or client.get('fullscreenClient', 0):
            raise RuntimeError('Exit fullscreen on the test window before this check.')
        return client

    def preserve_others(self):
        if other_geometries(self.address) != self.baseline:
            raise RuntimeError('Another window appeared, disappeared, or changed geometry; input stopped.')

    def preflight(self):
        config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'omarchy-zones/zones.conf'
        if config.stat().st_size > 131072 or profile_rows(config.read_text()) != self.profiles:
            raise RuntimeError('Prepare the exact --print-fixture layout before running; no input was started.')
        monitors = hyprctl_json('monitors')
        if len(monitors) != 1:
            raise RuntimeError('This fixture is for one DP-2 monitor only; no input was started.')
        monitor = monitors[0]
        expected = {'name': MONITOR, 'width': 2560, 'height': 1440, 'x': 0, 'y': 0,
                    'scale': 1, 'transform': 0, 'reserved': [0, 0, 0, 26]}
        if any(monitor.get(key) != value for key, value in expected.items()):
            raise RuntimeError('Monitor geometry differs from the inspected picker fixture; no input was started.')
        client = self.guard()
        if not re.fullmatch(r'0x[0-9a-fA-F]+', client['address']):
            raise RuntimeError('Unexpected client address.')
        self.address = client['address']
        self.baseline = other_geometries(self.address)
        current = status()
        if current['overlay'] != 'hidden' or current['drag-active'] != 'no':
            raise RuntimeError('Finish the current drag before running; no input was started.')
        self.output.mkdir(parents=True, exist_ok=True)

    def reset_test_window(self):
        self.guard()
        self.preserve_others()
        selector = f'window="address:{self.address}"'
        lua(f'hl.dispatch(hl.dsp.window.float({{action="enable",{selector}}}));'
            f'hl.dispatch(hl.dsp.window.resize({{x=600,y=400,{selector}}}));'
            f'hl.dispatch(hl.dsp.window.move({{x=300,y=250,{selector}}}));'
            f'hl.dispatch(hl.dsp.focus({{{selector}}}))')
        for _ in range(30):
            client = self.guard()
            if client['at'] == [300, 250] and client['size'] == [600, 400] and client['floating']:
                break
            time.sleep(.05)
        else:
            raise RuntimeError('Test window did not reach its starting rectangle.')
        time.sleep(.12)
        self.preserve_others()
        return geometry(self.guard()), status()

    def begin_drag(self, *, shift=True, titlebar=False):
        self.guard()
        self.input.move_to(520, 282 if titlebar else 440)
        if not titlebar:
            self.input.key('KEY_LEFTMETA', True)
        if shift:
            self.input.key('KEY_LEFTSHIFT', True)
        self.input.button(down=True)
        self.input.move_to(730, 500)
        time.sleep(.08)

    def hover_miniature(self, profile_index, zone_index):
        self.guard()
        self.input.move_to(*center(self.picker['cards'][profile_index]['zones'][zone_index]))
        time.sleep(.12)
        current = status()
        assert current['profiles'] == '4', current
        assert current['profile'] == self.profiles[profile_index]['name'], current
        assert current['target-zone'] == str(zone_index + 1), current
        assert current['overlay'] == 'visible' and current['picker'] == 'visible', current
        self.preserve_others()
        return current

    def end_drag(self, *, shift=True, titlebar=False):
        self.input.button(down=False)
        if shift:
            self.input.key('KEY_LEFTSHIFT', False)
        if not titlebar:
            self.input.key('KEY_LEFTMETA', False)
        time.sleep(.35)

    def record(self, name, before, initial, during, expected=None, extra=None):
        self.guard()
        self.preserve_others()
        final = status()
        after = geometry(self.guard())
        checks = {
            'single_snap_or_no_snap': int(final['snaps']) == int(initial['snaps']) + int(expected is not None),
            'overlay_hidden': final['overlay'] == 'hidden',
            'picker_hidden': final['picker'] == 'hidden',
            'text_textures_released': final['text-textures'] == '0',
            'other_windows_unchanged': other_geometries(self.address) == self.baseline,
        }
        if expected is not None:
            checks['exact_rectangle'] = after['at'] == expected[:2] and after['size'] == expected[2:]
            checks['floating'] = after['floating']
        else:
            checks['size_unchanged'] = after['size'] == before['size']
        if name == 'ordinary-drag':
            checks['normal_movement'] = after['at'] != before['at']
            checks['no_overlay_during_drag'] = during['overlay'] == 'hidden' and during['picker'] == 'hidden'
        if name == 'hotkey-alone':
            checks['window_unchanged'] = after == before
            checks['no_overlay_without_drag'] = during['overlay'] == 'hidden' and during['picker'] == 'hidden'
        row = {'scenario': name, 'passed': all(checks.values()), 'checks': checks, 'before': before,
               'during': during, 'after': after, 'initial': initial, 'final': final}
        if extra:
            row['extra'] = extra
        self.rows.append(row)
        print(name, 'PASS' if row['passed'] else 'FAIL', after['at'], after['size'], flush=True)
        if not row['passed']:
            raise RuntimeError(f'{name} failed: {checks}')

    def run_scenarios(self):
        # A modifier alone must not create a picker, change geometry, or allocate labels.
        before, initial = self.reset_test_window()
        self.input.key('KEY_LEFTMETA', True)
        self.input.key('KEY_LEFTSHIFT', True)
        time.sleep(.15)
        during = status()
        self.input.key('KEY_LEFTSHIFT', False)
        self.input.key('KEY_LEFTMETA', False)
        self.record('hotkey-alone', before, initial, during)

        # Hovering the right miniature in Split must select that profile and zone.
        before, initial = self.reset_test_window()
        self.begin_drag()
        during = self.hover_miniature(1, 1)
        self.guard()
        subprocess.run(['grim', str(self.output / 'profiles-picker.png')], check=True)
        self.end_drag()
        self.record('miniature-snap', before, initial, during, self.profiles[1]['zones'][1])

        # Profile labels preview only. Leaving the tray keeps the previewed profile.
        before, initial = self.reset_test_window()
        self.begin_drag()
        miniature = self.hover_miniature(2, 0)
        card = self.picker['cards'][2]
        label_position = (round(card['card'][0] + card['card'][2] / 2), round(card['thumbnail'][1] + card['thumbnail'][3] + 12))
        self.input.move_to(*label_position)
        label = status()
        assert label['profile'] == 'Main + side' and label['target-zone'] == 'none', label
        self.input.move_to(*center(self.profiles[2]['zones'][1]))
        time.sleep(.12)
        during = status()
        assert during['profile'] == 'Main + side' and during['target-zone'] == '2', during
        assert during['picker'] == 'visible', during
        self.end_drag()
        self.record('leave-tray-fullsize-snap', before, initial, during, self.profiles[2]['zones'][1],
                    {'miniature': miniature, 'label_preview': label})

        # The native client title bar uses startSystemMove, without the Super binding.
        before, initial = self.reset_test_window()
        self.begin_drag(titlebar=True)
        during = self.hover_miniature(3, 1)
        self.end_drag(titlebar=True)
        self.record('shift-titlebar-snap', before, initial, during, self.profiles[3]['zones'][1])

        # The pre-existing Super drag must behave normally without Shift.
        before, initial = self.reset_test_window()
        self.begin_drag(shift=False)
        self.input.move_to(1750, 650)
        during = status()
        self.end_drag(shift=False)
        self.record('ordinary-drag', before, initial, during)

        # Releasing Shift cancels the preview before releasing the mouse button.
        before, initial = self.reset_test_window()
        self.begin_drag()
        hovered = self.hover_miniature(1, 1)
        self.input.key('KEY_LEFTSHIFT', False)
        time.sleep(.12)
        during = status()
        assert during['overlay'] == 'hidden' and during['picker'] == 'hidden', during
        self.end_drag(shift=False)
        self.record('shift-release-cancels', before, initial, during, extra={'hovered': hovered})

        # This gutter lies over a full-size Split zone. It must never fall through.
        before, initial = self.reset_test_window()
        self.begin_drag()
        hovered = self.hover_miniature(1, 1)
        left, right = self.picker['cards'][1]['card'], self.picker['cards'][2]['card']
        gutter = (round((left[0] + left[2] + right[0]) / 2), 100)
        self.input.move_to(*gutter)
        time.sleep(.12)
        during = status()
        assert during['profile'] == 'Split' and during['target-zone'] == 'none', during
        assert during['overlay'] == 'visible' and during['picker'] == 'visible', during
        self.end_drag()
        self.record('empty-gutter-no-snap', before, initial, during, extra={'hovered': hovered, 'gutter': gutter})

    def run(self):
        self.preflight()
        failure = None
        try:
            with NativeInput(workspace=WORKSPACE) as self.input:
                self.run_scenarios()
        except BaseException as error:
            failure = f'{type(error).__name__}: {error}'
            raise
        finally:
            # This file is test evidence only. The saved zone configuration is never written.
            report = {'workspace': WORKSPACE, 'title': TITLE, 'fixture': self.profiles,
                      'picker_geometry': self.picker, 'other_windows_before': self.baseline,
                      'scenarios': self.rows, 'failure': failure,
                      'scope': 'Real native Wayland input and geometry on one DP-2 monitor at scale 1.'}
            (self.output / 'native-profiles.json').write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-fixture', action='store_true', help='Print the required fixture and exit without desktop input')
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence')
    args = parser.parse_args()
    if args.print_fixture:
        print(FIXTURE, end='')
        return
    NativeProfileCheck(args.output).run()


if __name__ == '__main__':
    main()
