#!/usr/bin/env python3
"""Exercise a binary update inside the isolated compositor, preserving all config.

Run directly after lab.py start with an empty lab. This copies the currently
installed release into a private fixture, loads that copy in the lab, runs the
real manager against the new build, and unloads it. It never installs integration
into either compositor's actual configuration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from common import require
from lab import LAB, ROOT, ctl, environment

ARTIFACTS = ROOT / 'evidence/editor-fixes'
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plugins():
    return json.loads(ctl('-j', 'plugin', 'list'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build')
    build_dir = parser.parse_args().build_dir.resolve()
    env = environment()
    runtime = Path(env['XDG_RUNTIME_DIR'])
    require(str(runtime).startswith('/tmp/ozr-'), 'Only the isolated lab runtime is allowed')
    socket = runtime / 'hypr' / env['HYPRLAND_INSTANCE_SIGNATURE'] / '.socket.sock'
    require(socket.exists() and stat.S_ISSOCK(socket.stat().st_mode), 'No isolated compositor socket')
    pid = int((LAB / 'pid').read_text())
    require(str(LAB / 'hyprland.lua').encode() in Path(f'/proc/{pid}/cmdline').read_bytes(),
            'Compositor PID is not this lab')
    require(not plugins() and not json.loads(ctl('-j', 'clients')), 'The lab must be empty')

    installed_data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    installed = installed_data / 'omarchy-zones'
    require(all((installed / name).is_file() for name in ('omarchy-zones.so', 'omarchy-zones-editor')),
            'An existing installed release is required as the update source')
    fixture = Path(tempfile.mkdtemp(prefix='update-', dir=LAB))
    dest = fixture / 'data/omarchy-zones'
    config = fixture / 'config'
    home = fixture / 'home'
    main_config = config / 'hypr/hyprland.lua'
    launcher = home / '.local/bin/omarchy-zones'
    desktop = fixture / 'data/applications/omarchy-zones.desktop'
    manifest = dest / 'manifest.json'
    target = dest / 'omarchy-zones.so'
    loaded = False
    result = {'passed': False}
    try:
        for directory in (dest, main_config.parent, launcher.parent, desktop.parent, config / 'omarchy-zones'):
            directory.mkdir(parents=True, exist_ok=True)
        before_config = b'-- unrelated private configuration, never loaded by the lab\n'
        block = ('-- BEGIN omarchy-zones (managed)\n'
                 + 'dofile(' + json.dumps(str(dest / 'zones.lua'), ensure_ascii=False) + ')\n'
                 + '-- END omarchy-zones (managed)\n')
        main_config.write_bytes(before_config + block.encode())
        (dest / 'hyprland.lua.before-install').write_bytes(before_config)
        (dest / 'zones.lua').write_text('-- private integration fixture; not sourced\n')
        launcher.write_text('#!/bin/sh\n# private launcher fixture\n')
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Private Zones fixture\n')
        definitions = config / 'omarchy-zones/zones.conf'
        definitions.write_text('omarchy-zones-v2\nprofile "Keep me"\nWAYLAND-1 0 0 640 900\n')
        for name in ('omarchy-zones.so', 'omarchy-zones-editor'):
            shutil.copy2(installed / name, dest / name)
        owned = [dest / name for name in ('omarchy-zones.so', 'omarchy-zones-editor', 'zones.lua', 'hyprland.lua.before-install')]
        owned += [launcher, desktop]
        manifest.write_text(json.dumps({'block': block, 'owned': {str(path): checksum(path) for path in owned}}, indent=2))
        preserved = [main_config, dest / 'zones.lua', dest / 'hyprland.lua.before-install', launcher, desktop, definitions,
                     LAB / 'hyprland.lua']
        original_hashes = {str(path): checksum(path) for path in preserved}
        source_hashes = {str(installed / name): checksum(installed / name) for name in ('omarchy-zones.so', 'omarchy-zones-editor')}
        ctl('plugin', 'load', str(target))
        loaded = True
        previous_version = plugins()[0]['version']
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_DATA_HOME=str(fixture / 'data'))
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/manage.py'), 'update', '--build-dir', str(build_dir)],
                                   env=env, text=True, capture_output=True, check=True, timeout=30)
        current = plugins()
        require(len(current) == 1 and current[0]['name'] == 'omarchy-zones', current)
        require(current[0]['version'] == '0.3.1', current)
        after_hashes = {str(path): checksum(path) for path in preserved}
        require(after_hashes == original_hashes, 'Update modified private configuration or definitions')
        require(all(checksum(Path(path)) == digest for path, digest in source_hashes.items()), 'Installed binaries changed')
        updated = json.loads(manifest.read_text())
        require(set(updated['owned']) == {str(path) for path in owned}, 'Manifest ownership changed')
        require(all(checksum(Path(path)) == digest for path, digest in updated['owned'].items()), 'Manifest hash mismatch')
        for name in ('omarchy-zones.so', 'omarchy-zones-editor'):
            require(checksum(dest / name) == checksum(build_dir / name), 'New binary was not copied')
        result.update(passed=True, old_version=previous_version, new_version=current[0]['version'],
                      preserved_files=len(preserved), installed_source_files_unchanged=len(source_hashes),
                      manifest_hashes_verified=len(owned), output=completed.stdout.strip(),
                      status=ctl('zones'))
    finally:
        if loaded:
            ctl('plugin', 'unload', str(target))
        require(not plugins(), 'The test left a plugin loaded')
        shutil.rmtree(fixture)
        (ARTIFACTS / 'native-update.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
