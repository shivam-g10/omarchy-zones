#!/usr/bin/env python3
"""Measure a warm native plugin with an unloaded/loaded/unloaded comparison.

Every input event and compositor command targets the private native lab. Each
idle sample excludes test clients and the virtual input helper. The production
plugin is exercised once before the first baseline to warm shared rendering and
loader paths, then exercised again for the loaded sample. Both surrounding
baselines are reported; neither is selected as the preferred comparison.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from common import ARTIFACTS, Input, get, info, place, require, status, wait_for
from check_plugin import PLUGIN, CLIENT, check_idle_state, fixture, save_json
from lab import LAB, ctl, environment
from measure import sample

TITLE = 'Zones idle measurement'


def mapped_plugin(pid):
    """Resident file mappings only; this excludes heap and graphics allocations."""
    sections = []
    current = None
    for line in Path(f'/proc/{pid}/smaps').read_text().splitlines():
        if re.match(r'^[0-9a-f]+-[0-9a-f]+ ', line):
            fields = line.split(maxsplit=5)
            path = fields[5] if len(fields) == 6 else ''
            current = None
            if path.removesuffix(' (deleted)') == str(PLUGIN.resolve()):
                current = {'address': fields[0], 'permissions': fields[1], 'path': path}
                sections.append(current)
        elif current is not None and ':' in line:
            key, tail = line.split(':', 1)
            if key in ['Size', 'Rss', 'Pss', 'Private_Clean', 'Private_Dirty', 'Shared_Clean', 'Shared_Dirty']:
                current[key] = int(tail.split()[0])
    totals = {key: sum(section.get(key, 0) for section in sections)
              for key in ['Size', 'Rss', 'Pss', 'Private_Clean', 'Private_Dirty', 'Shared_Clean', 'Shared_Dirty']}
    return {'sections': sections, 'totals_kib': totals,
            'limits': 'Only file mappings for omarchy-zones.so. Excludes heap allocations, '
                      'shared dependencies, compositor caches, and GPU memory.'}


def main():
    env = environment()
    require(env['XDG_RUNTIME_DIR'].startswith('/tmp/ozr-'), 'Refusing a non-isolated runtime')
    for variable in ['XDG_CONFIG_HOME', 'XDG_STATE_HOME']:
        require(Path(env[variable]).resolve().is_relative_to(LAB.resolve()), variable)
    require(not info(), 'Finish other native tests before measuring idle.')
    require(not json.loads(ctl('-j', 'plugin', 'list')), 'Unload other lab plugins before measuring idle.')
    monitors = json.loads(ctl('-j', 'monitors'))
    require(len(monitors) == 1 and monitors[0]['width'] == 1280 and monitors[0]['height'] == 900,
            monitors)
    require(monitors[0]['scale'] == 1 and monitors[0]['reserved'] == [0, 0, 0, 0], monitors)
    pid = int((LAB / 'pid').read_text())
    require(str(LAB / 'hyprland.lua').encode() in Path(f'/proc/{pid}/cmdline').read_bytes(), 'Wrong compositor PID')

    zone_path = Path(env['XDG_CONFIG_HOME']) / 'omarchy-zones/zones.conf'
    zone_path.parent.mkdir(parents=True, exist_ok=True)
    require(not zone_path.is_symlink(), 'Refusing a zone-file symlink')
    zone_backup = zone_path.read_bytes() if zone_path.exists() else None
    theme_path = Path(env['XDG_STATE_HOME']) / 'omarchy/current/theme'
    theme_path.mkdir(parents=True, exist_ok=True)
    source_theme = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy/current/theme'
    theme_backup = {}
    for name in ['colors.toml', 'shell.toml']:
        target = theme_path / name
        require(not target.is_symlink(), 'Refusing a theme-file symlink')
        theme_backup[name] = target.read_bytes() if target.exists() else None

    loaded = False
    child = None
    result = {'passed': False, 'duration_per_sample_seconds': 20, 'samples': [],
              'limits': 'A/B/A endpoint comparison in a single nested native compositor, '
                        'not a statistical confidence interval. Heap retention, loader and renderer '
                        'caches, changing shared-page accounting, and concurrent host activity can '
                        'change the differential. No peak or GPU memory measurement.'}
    log = (ARTIFACTS / 'plugin-idle-warmup.log').open('w')

    def load():
        nonlocal loaded
        require('ok' in ctl('plugin', 'load', str(PLUGIN)), 'Load failed')
        loaded = True

    def unload():
        nonlocal loaded
        require('ok' in ctl('plugin', 'unload', str(PLUGIN)), 'Unload failed')
        loaded = False
        require(not json.loads(ctl('-j', 'plugin', 'list')), 'Plugin remains loaded')

    def warm_gesture():
        nonlocal child
        child = subprocess.Popen([str(CLIENT), TITLE], env=env, stdout=log, stderr=log)
        wait_for(lambda: get(TITLE))
        require(not get(TITLE)['xwayland'], 'A native client is required')
        place(TITLE)
        with Input() as device:
            device.move(430, 450)
            device.key(125, True)
            device.key(42, True)
            device.button(True)
            device.move(600, 470)
            device.move(1000, 440)
            require(status()['overlay'] == 'visible', status())
            device.button(False)
            device.key(42, False)
            device.key(125, False)
        state = check_idle_state()
        require(state['snaps'] == '1', state)
        require(get(TITLE)['at'] + get(TITLE)['size'] == [640, 0, 640, 900], get(TITLE))
        child.terminate()
        child.wait(timeout=4)
        child = None
        wait_for(lambda: not info())
        return state

    def capture(label):
        require(not info(), 'A test window remains before an idle sample')
        mapping_before = mapped_plugin(pid)
        state = check_idle_state() if loaded else None
        print(f'Sampling {label} for 20 seconds.', flush=True)
        measurement = sample([pid], 20, label)
        mapping_after = mapped_plugin(pid)
        require(not info(), 'A test window appeared during idle sampling')
        require(mapping_after['totals_kib']['Rss'] > 0 if loaded else not mapping_after['sections'],
                mapping_after)
        for census in [measurement['census_before'], measurement['census_after']]:
            require(not census['missing_roots'] and not census['vanished_or_unreadable'], census)
            require(len(census['processes']) == 1 and census['processes'][0]['pid'] == pid,
                    'Unexpected helper process in compositor census')
        measurement['plugin_status'] = state
        measurement['plugin_mapping_before'] = mapping_before
        measurement['plugin_mapping_after'] = mapping_after
        result['samples'].append(measurement)
        return measurement

    try:
        zone_path.write_text(fixture(monitors[0]['name']))
        for name in theme_backup:
            if (source_theme / name).is_file():
                shutil.copyfile(source_theme / name, theme_path / name)
        load()
        result['prebaseline_warmup'] = warm_gesture()
        result['prebaseline_warm_mapping'] = mapped_plugin(pid)
        unload()
        baseline_before = capture('unloaded baseline before')
        load()
        result['loaded_warmup'] = warm_gesture()
        loaded_sample = capture('loaded plugin after native gesture')
        unload()
        baseline_after = capture('unloaded baseline after')
        keys = ['rss_kib', 'pss_kib', 'private_kib']
        differences = []
        for baseline in [baseline_before, baseline_after]:
            differences.append({'baseline': baseline['label'],
                                **{key: loaded_sample['total'][key] - baseline['total'][key] for key in keys}})
        result['loaded_minus_each_baseline'] = differences
        result['observed_difference_range'] = {
            key: {'minimum': min(row[key] for row in differences), 'maximum': max(row[key] for row in differences)}
            for key in keys}
        result['passed'] = True
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=4)
        if loaded:
            unload()
        if zone_backup is None:
            zone_path.unlink(missing_ok=True)
        else:
            zone_path.write_bytes(zone_backup)
        for name, contents in theme_backup.items():
            path = theme_path / name
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(contents)
        log.close()
        save_json('plugin-idle-aba.json', result)
    print(json.dumps({'passed': result['passed'],
                      'range': result['observed_difference_range'],
                      'cpu_percent_one_core': [row['total']['cpu_percent_one_core'] for row in result['samples']],
                      'plugin_mapping_kib': loaded_sample['plugin_mapping_after']['totals_kib']}, indent=2))


if __name__ == '__main__':
    main()
