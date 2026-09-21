#!/usr/bin/env python3
"""Exercise installer transactions in temporary homes with a mocked desktop API."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/manage.py'


class InstallationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zones-install-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        spec = importlib.util.spec_from_file_location('zones_manage_test', SOURCE)
        self.manager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.manager)
        m = self.manager
        m.HOME = self.base / 'home'
        m.CONFIG = m.HOME / '.config'
        m.DATA = m.HOME / '.local/share'
        m.ROOT = self.base / 'source'
        m.PLUGIN = m.CONFIG / 'omarchy/plugins/omarchy-zones'
        m.MAIN = m.CONFIG / 'hypr/hyprland.lua'
        m.SHELL = m.CONFIG / 'omarchy/shell.json'
        m.LAUNCHER = m.HOME / '.local/bin/omarchy-zones'
        m.DESKTOP = m.DATA / 'applications/omarchy-zones.desktop'
        m.RECEIPT = m.DATA / 'omarchy-zones/installation.json'
        self.original_main = 'require("hypr.bindings")\n-- Unrelated settings\n'
        self.original_shell = {
            'version': 1, 'bar': {'layout': {'left': [{'id': 'marcho78.taskbar'}]}},
            'plugins': [{'id': 'expose.window-overview', 'hotCornerEnabled': False}],
            'idle': {'lock': 300},
        }
        self.write(m.MAIN, self.original_main)
        self.write(m.SHELL, json.dumps(self.original_shell, indent=2) + '\n')
        self.profile = m.CONFIG / 'omarchy-zones/zones.conf'
        self.write(self.profile, 'user profile definitions\n')
        for path in m.runtime_files(m.ROOT):
            self.write(path, 'source:' + str(path.relative_to(m.ROOT)) + '\n')
        self.calls = []
        self.binds = []
        self.backend_ready = True
        self.failure = None
        self.patch_run = patch.object(m, 'run', self.run_desktop)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)
        self.patch_sleep = patch.object(m.time, 'sleep', lambda _: None)
        self.patch_sleep.start()
        self.addCleanup(self.patch_sleep.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def shell(self):
        return json.loads(self.manager.SHELL.read_text())

    def run_desktop(self, *args, optional=False):
        self.calls.append(args)
        if self.failure is not None:
            result = self.failure(args)
            if result is not None:
                return result
        m = self.manager
        if args == ('hyprctl', 'configerrors'):
            return ''
        if args == ('hyprctl', '-j', 'binds'):
            return json.dumps(self.binds)
        if args[:2] == ('hyprctl', 'eval'):
            return 'ok' if self.backend_ready else 'Zones backend not ready'
        if args == ('hyprctl', 'reload'):
            return 'ok'
        if args[:3] == ('omarchy', 'plugin', 'validate'):
            return ''
        if args[:3] in (('omarchy', 'plugin', 'enable'), ('omarchy', 'plugin', 'disable')):
            shell = self.shell()
            entries = [p for p in shell['plugins'] if p['id'] != 'omarchy-zones']
            if args[2] == 'enable':
                entries.append({'id': 'omarchy-zones'})
            shell['plugins'] = entries
            self.write(m.SHELL, json.dumps(shell, indent=2) + '\n')
            return 'ok'
        if args == ('omarchy-shell', 'shell', 'listPlugins'):
            return json.dumps([{'id': 'omarchy-zones'}] if (m.PLUGIN / 'manifest.json').exists() else [])
        if args in (('omarchy-shell', 'shell', 'ping'), ('omarchy-shell', 'shell', 'rescanPlugins')):
            return 'ok'
        if args == ('omarchy-shell', 'omarchy-zones', 'status'):
            return json.dumps({'ready': True, 'enabled': True, 'editorOpen': False, 'active': False})
        self.fail(f'Unexpected desktop command: {args}')

    def assert_unrelated(self):
        value = self.shell()
        value['plugins'] = [p for p in value['plugins'] if p['id'] != 'omarchy-zones']
        self.assertEqual(value, self.original_shell)
        self.assertEqual(self.profile.read_text(), 'user profile definitions\n')

    def test_fresh_install_update_remove_preserves_unrelated_settings_and_profiles(self):
        m = self.manager
        m.setup()
        self.assertEqual(m.MAIN.read_text(), self.original_main + m.block())
        self.assertEqual(m.LAUNCHER.stat().st_mode & 0o777, 0o755)
        self.assertEqual(m.RECEIPT.stat().st_mode & 0o777, 0o600)
        self.assert_unrelated()
        source = m.ROOT / 'shell/Editor.qml'
        source.write_text('updated editor source\n')
        m.setup(update=True)
        self.assertEqual((m.PLUGIN / 'shell/Editor.qml').read_text(), source.read_text())
        self.assertEqual(m.MAIN.read_text().count(m.block()), 1)
        self.assert_unrelated()
        m.remove()
        self.assertEqual(m.MAIN.read_text(), self.original_main)
        self.assertFalse(m.RECEIPT.exists())
        self.assertFalse(m.LAUNCHER.exists())
        self.assertFalse(m.DESKTOP.exists())
        self.assertTrue((m.PLUGIN / 'shell/Service.qml').exists())
        self.assert_unrelated()

    def test_in_place_update_retains_complete_runtime_ownership(self):
        m = self.manager
        m.setup()
        m.ROOT = m.PLUGIN
        (m.PLUGIN / 'shell/Editor.qml').write_text('official source update\n')
        m.setup(update=True)
        receipt = m.read_receipt()
        self.assertEqual(set(receipt['copied']), {str(p) for p in m.runtime_files(m.PLUGIN)})
        m.verify(receipt['copied'])

    def test_remove_restores_original_file_without_final_newline(self):
        m = self.manager
        m.MAIN.write_text(self.original_main.rstrip('\n'))
        original = m.MAIN.read_bytes()
        m.setup()
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), original)

    def test_existing_hotkey_refuses_before_writes(self):
        m = self.manager
        self.binds = [{'modmask': 65, 'key': 'mouse:272'}]
        with self.assertRaisesRegex(RuntimeError, 'already bound'):
            m.setup()
        self.assertFalse(m.RECEIPT.exists())
        self.assertEqual(m.MAIN.read_text(), self.original_main)

    def test_edited_owned_launcher_refuses_update_and_remove(self):
        m = self.manager
        m.setup()
        m.LAUNCHER.write_text('user replacement\n')
        before = m.MAIN.read_bytes()
        for action in (lambda: m.setup(update=True), m.remove):
            with self.assertRaisesRegex(RuntimeError, 'Owned file was edited'):
                action()
        self.assertEqual(m.LAUNCHER.read_text(), 'user replacement\n')
        self.assertEqual(m.MAIN.read_bytes(), before)

    def test_edited_runtime_refuses_external_update(self):
        m = self.manager
        m.setup()
        path = m.PLUGIN / 'shell/Editor.qml'
        path.write_text('user changed installed editor\n')
        with self.assertRaisesRegex(RuntimeError, 'Owned file was edited'):
            m.setup(update=True)
        self.assertEqual(path.read_text(), 'user changed installed editor\n')

    def test_receipt_cannot_omit_runtime_ownership(self):
        m = self.manager
        m.setup()
        receipt = json.loads(m.RECEIPT.read_text())
        receipt['copied'].pop(str(m.PLUGIN / 'shell/Service.qml'))
        m.RECEIPT.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected owned plugin paths'):
            m.setup(update=True)

    def test_receipt_cannot_claim_unrelated_path(self):
        m = self.manager
        m.setup()
        receipt = json.loads(m.RECEIPT.read_text())
        receipt['copied'][str(self.profile)] = m.digest(self.profile.read_bytes())
        m.RECEIPT.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected owned plugin paths'):
            m.remove()
        self.assertEqual(self.profile.read_text(), 'user profile definitions\n')

    def test_linked_destination_parent_refuses_without_external_writes(self):
        m = self.manager
        outside = self.base / 'unrelated'
        outside.mkdir()
        m.PLUGIN.mkdir(parents=True)
        (m.PLUGIN / 'shell').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'linked parent'):
            m.setup()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(m.MAIN.read_text(), self.original_main)

    def test_failed_activation_restores_files_and_settings(self):
        m = self.manager
        shell_before = m.SHELL.read_bytes()
        self.backend_ready = False
        with self.assertRaisesRegex(RuntimeError, 'backend did not become ready'):
            m.setup()
        self.assertEqual(m.MAIN.read_text(), self.original_main)
        self.assertEqual(m.SHELL.read_bytes(), shell_before)
        self.assertFalse(m.LAUNCHER.exists())
        self.assertFalse(m.RECEIPT.exists())
        self.assert_unrelated()

    def test_failed_update_restores_previous_runtime_and_receipt(self):
        m = self.manager
        m.setup()
        before = {p: p.read_bytes() for p in m.runtime_files(m.PLUGIN) + [m.RECEIPT, m.MAIN, m.SHELL]}
        (m.ROOT / 'shell/Editor.qml').write_text('updated editor\n')
        self.backend_ready = False
        with self.assertRaisesRegex(RuntimeError, 'backend did not become ready'):
            m.setup(update=True)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_concurrent_hyprland_edit_is_not_overwritten(self):
        m = self.manager
        changed = self.original_main + '-- Concurrent desktop setting\n'
        def failure(args):
            if args[:3] == ('omarchy', 'plugin', 'validate'):
                m.MAIN.write_text(changed)
        self.failure = failure
        with self.assertRaisesRegex(RuntimeError, 'configuration changed during setup'):
            m.setup()
        self.assertEqual(m.MAIN.read_text(), changed)
        self.assertFalse(m.RECEIPT.exists())
        self.assert_unrelated()

    def test_recovery_finishes_after_owned_file_changed_concurrently(self):
        m = self.manager
        changed = False
        def failure(args):
            nonlocal changed
            if args[:2] == ('hyprctl', 'eval') and not changed:
                changed = True
                m.LAUNCHER.write_text('concurrent user launcher\n')
                settings = self.shell()
                settings['idle']['lock'] = 900
                self.write(m.SHELL, json.dumps(settings))
                raise RuntimeError('activation failed')
        self.failure = failure
        with self.assertRaisesRegex(RuntimeError, 'Concurrent edits retained'):
            m.setup()
        self.assertEqual(m.LAUNCHER.read_text(), 'concurrent user launcher\n')
        self.assertEqual(m.MAIN.read_text(), self.original_main)
        self.assertEqual(self.shell()['idle']['lock'], 900)
        self.assertFalse(any(p['id'] == 'omarchy-zones' for p in self.shell()['plugins']))
        self.assertGreaterEqual(self.calls.count(('hyprctl', 'reload')), 2)

    def test_failed_remove_restores_files_and_previous_disabled_state(self):
        m = self.manager
        m.setup()
        self.run_desktop('omarchy', 'plugin', 'disable', 'omarchy-zones')
        before = {p: p.read_bytes() for p in (m.MAIN, m.SHELL, m.LAUNCHER, m.DESKTOP, m.RECEIPT)}
        failed = False
        def failure(args):
            nonlocal failed
            if args == ('hyprctl', 'reload') and not failed:
                failed = True
                raise RuntimeError('reload failed')
        self.failure = failure
        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
            m.remove()
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
