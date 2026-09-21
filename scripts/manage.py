#!/usr/bin/env python3
"""Manage QML-only Omarchy Zones integration without compiling or installing packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME') or HOME / '.config')
DATA = Path(os.environ.get('XDG_DATA_HOME') or HOME / '.local/share')
PLUGIN = CONFIG / 'omarchy/plugins/omarchy-zones'
MAIN = CONFIG / 'hypr/hyprland.lua'
SHELL = CONFIG / 'omarchy/shell.json'
LAUNCHER = HOME / '.local/bin/omarchy-zones'
DESKTOP = DATA / 'applications/omarchy-zones.desktop'
RECEIPT = DATA / 'omarchy-zones/installation.json'
BEGIN = '-- BEGIN omarchy-zones (managed)\n'
END = '-- END omarchy-zones (managed)\n'


def run(*args, optional=False):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=15, check=True)
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        if not optional:
            raise
        return ''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.zones-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data if isinstance(data, bytes) else data.encode())
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def regular(path, required=False):
    for parent in path.parents:
        if parent.is_symlink():
            raise RuntimeError(f'Refusing a linked parent directory: {parent}')
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f'Expected a regular file: {path}')
    if required and not path.is_file():
        raise RuntimeError(f'Missing file: {path}')


class Transaction:
    """Restore our writes on handled failures, without overwriting concurrent edits."""
    def __init__(self):
        self.original = {}
        self.written = {}

    def remember(self, path):
        regular(path)
        if path not in self.original:
            self.original[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None

    def write(self, path, data, mode=0o644):
        self.remember(path)
        data = data if isinstance(data, bytes) else data.encode()
        atomic(path, data, mode)
        self.written[path] = data

    def delete(self, path):
        self.remember(path)
        path.unlink(missing_ok=True)
        self.written[path] = None

    def rollback(self):
        conflicts = []
        for path, expected in reversed(list(self.written.items())):
            current = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            if path.is_symlink() or current != expected:
                conflicts.append(str(path))
                continue
            original = self.original[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, *original)
        if conflicts:
            raise RuntimeError('Concurrent edits retained during recovery: ' + ', '.join(conflicts))


def block():
    # ensure_ascii=False preserves UTF-8 paths; Lua does not accept JSON \u escapes.
    return BEGIN + 'dofile(' + json.dumps(str(PLUGIN / 'shell/bindings.lua'), ensure_ascii=False) + ')\n' + END


def validate_environment():
    for path in (HOME, CONFIG, DATA, PLUGIN, MAIN, RECEIPT):
        if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
            raise RuntimeError('Installation paths must be absolute without control characters.')
    for path in (PLUGIN, RECEIPT.parent):
        if path.is_symlink():
            raise RuntimeError(f'Refusing linked installation directory: {path}')
    regular(MAIN, required=True)
    regular(SHELL, required=True)
    if run('hyprctl', 'configerrors'):
        raise RuntimeError('Resolve existing Hyprland configuration errors first.')
    run('omarchy-shell', 'shell', 'ping')
    value = run('omarchy-shell', 'omarchy-zones', 'status', optional=True)
    try:
        if value and (json.loads(value).get('editorOpen') or json.loads(value).get('active')):
            raise RuntimeError('Save and close the Zones editor and finish dragging before setup.')
    except ValueError:
        pass


def read_receipt():
    regular(RECEIPT, required=True)
    if RECEIPT.stat().st_size > 131072:
        raise RuntimeError('Oversized installation receipt.')
    value = json.loads(RECEIPT.read_text())
    if value.get('kind') != 'qml' or value.get('block') != block():
        raise RuntimeError('Unrecognized installation receipt.')
    if set(value.get('owned', {})) != {str(LAUNCHER), str(DESKTOP)}:
        raise RuntimeError('Unexpected owned integration paths.')
    if set(value.get('copied', {})) != {str(path) for path in runtime_files(PLUGIN)}:
        raise RuntimeError('Unexpected owned plugin paths.')
    return value


def verify(files):
    for name, expected in files.items():
        path = Path(name)
        regular(path, required=True)
        if digest(path.read_bytes()) != expected:
            raise RuntimeError(f'Owned file was edited; refusing to overwrite it: {path}')


def runtime_files(root):
    names = ['manifest.json', 'README.md', 'CONTRIBUTING.md', 'scripts/manage.py',
             'scripts/setup.sh', 'scripts/launch-editor.sh']
    names += ['shell/' + name for name in ('Service.qml', 'Editor.qml', 'Overlay.qml',
              'Store.qml', 'Geometry.js', 'Layouts.js', 'Profiles.js', 'bindings.lua')]
    return [root / name for name in names]


def reload_hyprland():
    run('hyprctl', 'reload')
    errors = run('hyprctl', 'configerrors')
    if errors:
        raise RuntimeError(errors)


def discover():
    run('omarchy-shell', 'shell', 'rescanPlugins')
    for _ in range(30):
        values = json.loads(run('omarchy-shell', 'shell', 'listPlugins'))
        if any(item['id'] == 'omarchy-zones' for item in values):
            return
        time.sleep(.2)
    raise RuntimeError('The shell did not discover Omarchy Zones.')


def activate():
    discover()
    run('omarchy', 'plugin', 'enable', 'omarchy-zones')
    for _ in range(30):
        value = run('omarchy-shell', 'omarchy-zones', 'status', optional=True)
        try:
            state = json.loads(value)
            if state.get('ready') and state.get('enabled'):
                result = run('hyprctl', 'eval', 'assert(zones_shell and zones_shell.enabled and zones_shell.owner, "Zones backend not ready")')
                if result == 'ok':
                    return
        except ValueError:
            pass
        time.sleep(.2)
    raise RuntimeError('The QML service or Lua backend did not become ready.')


def restore_shell_entry(before, mode):
    """Restore only our entry, retaining unrelated settings changed during setup."""
    prior = json.loads(before)
    current = json.loads(SHELL.read_text())
    entries = [p for p in current.get('plugins', []) if p.get('id') != 'omarchy-zones']
    for index, entry in enumerate(prior.get('plugins', [])):
        if entry.get('id') == 'omarchy-zones':
            entries.insert(min(index, len(entries)), entry)
    if 'plugins' in prior or entries:
        current['plugins'] = entries
    else:
        current.pop('plugins', None)
    atomic(SHELL, before if current == prior else json.dumps(current, indent=2) + '\n', mode)


def recover(transaction, shell_before, shell_mode):
    """Attempt every recovery step even when one owned file was edited meanwhile."""
    failures = []
    run('omarchy', 'plugin', 'disable', 'omarchy-zones', optional=True)
    for action in (transaction.rollback,
                   lambda: restore_shell_entry(shell_before, shell_mode),
                   reload_hyprland):
        try:
            action()
        except Exception as error:
            failures.append(str(error))
    run('omarchy-shell', 'shell', 'rescanPlugins', optional=True)
    if failures:
        raise RuntimeError('Recovery needs attention: ' + '; '.join(failures))


def setup(update=False):
    validate_environment()
    old = read_receipt() if update else None
    if not update and (RECEIPT.exists() or (RECEIPT.parent / 'manifest.json').exists()):
        raise RuntimeError('An existing installation needs update or removal before setup.')
    if old:
        verify(old['owned'])
        if ROOT != PLUGIN:
            verify(old['copied'])
    else:
        for path in (LAUNCHER, DESKTOP):
            if path.exists() or path.is_symlink():
                raise RuntimeError(f'An integration path already exists: {path}')
    original = MAIN.read_text()
    if old:
        if original.count(old['block']) != 1:
            raise RuntimeError('The managed block was edited; refusing to overwrite it.')
    else:
        if 'BEGIN omarchy-zones' in original:
            raise RuntimeError('An existing Zones integration must be removed before setup.')
        binds = json.loads(run('hyprctl', '-j', 'binds'))
        if any(b['modmask'] == 65 and b['key'].upper() in ('MOUSE:272', 'F8') for b in binds):
            raise RuntimeError('Super+Shift+drag or Super+Shift+F8 is already bound.')
    sources = runtime_files(ROOT)
    for source in sources:
        regular(source, required=True)
    # Validate the shipped package rather than unrelated checkout files.
    with tempfile.TemporaryDirectory(prefix='omarchy-zones-validate-') as temporary:
        stage = Path(temporary)
        for source in sources:
            destination = stage / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        run('omarchy', 'plugin', 'validate', str(stage))
    if ROOT != PLUGIN and not old:
        for source in sources:
            destination = PLUGIN / source.relative_to(ROOT)
            regular(destination)
            if destination.exists() or destination.is_symlink():
                raise RuntimeError(f'Refusing to replace an unowned plugin file: {destination}')
    transaction = Transaction()
    shell_before = SHELL.read_bytes()
    shell_mode = SHELL.stat().st_mode & 0o777
    try:
        if old:
            run('omarchy', 'plugin', 'disable', 'omarchy-zones')
        if ROOT != PLUGIN:
            for source in sources:
                destination = PLUGIN / source.relative_to(ROOT)
                transaction.write(destination, source.read_bytes(), source.stat().st_mode & 0o777)
        launcher = '#!/bin/sh\nexec omarchy-shell omarchy-zones openEditor\n'
        desktop_path = str(LAUNCHER).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
        desktop = '[Desktop Entry]\nType=Application\nName=Omarchy Zones\nComment=Define window zones\nExec="' + desktop_path + '"\nIcon=preferences-desktop-display\nCategories=Utility;\nTerminal=false\n'
        transaction.write(LAUNCHER, launcher, 0o755)
        transaction.write(DESKTOP, desktop)
        if not old:
            if MAIN.read_text() != original:
                raise RuntimeError('Hyprland configuration changed during setup; retry with the new configuration.')
            separator = '' if original.endswith('\n') else '\n'
            transaction.write(MAIN, original + separator + block(), MAIN.stat().st_mode & 0o777)
        reload_hyprland()
        activate()
        receipt = {'kind': 'qml', 'version': 1, 'block': block(),
                   'owned': {str(p): digest(p.read_bytes()) for p in (LAUNCHER, DESKTOP)},
                   'copied': {str(p): digest(p.read_bytes()) for p in runtime_files(PLUGIN)},
                   'added_separator': old.get('added_separator', False) if old else not original.endswith('\n')}
        transaction.write(RECEIPT, json.dumps(receipt, indent=2) + '\n', 0o600)
    except Exception:
        recover(transaction, shell_before, shell_mode)
        raise
    print('QML Omarchy Zones installed. Profiles retained. No build or additional packages.')


def remove():
    validate_environment()
    receipt = read_receipt()
    verify(receipt['owned'])
    current = MAIN.read_text()
    if current.count(receipt['block']) != 1:
        raise RuntimeError('The managed block was edited; refusing removal.')
    transaction = Transaction()
    shell_before = SHELL.read_bytes()
    shell_mode = SHELL.stat().st_mode & 0o777
    try:
        run('omarchy', 'plugin', 'disable', 'omarchy-zones')
        owned_block = ('\n' if receipt.get('added_separator') else '') + receipt['block']
        if current.count(owned_block) != 1:
            raise RuntimeError('The managed block separator was edited; refusing removal.')
        transaction.write(MAIN, current.replace(owned_block, '', 1), MAIN.stat().st_mode & 0o777)
        reload_hyprland()
        for path in (LAUNCHER, DESKTOP, RECEIPT):
            transaction.delete(path)
    except Exception:
        recover(transaction, shell_before, shell_mode)
        raise
    print('Zones integration removed. Profiles and plugin source retained.')
    print('To remove the source directory: omarchy plugin remove omarchy-zones')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'update', 'remove', 'status'))
    args = parser.parse_args()
    if args.action == 'status':
        print(run('omarchy-shell', 'omarchy-zones', 'status'))
    elif args.action == 'remove':
        remove()
    else:
        setup(update=args.action == 'update')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'omarchy-zones: {error}', file=sys.stderr)
        sys.exit(1)
