#!/usr/bin/env python3
"""Exercise installer rollback against temporary files; never touches the desktop."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/manage.py'


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('zones_manage', SCRIPT)
        self.manage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.manage)
        m = self.manage
        m.ROOT = root / 'repo'
        m.HOME = root / 'home'
        m.CONFIG = m.HOME / '.config'
        m.DATA = m.HOME / '.local/share'
        m.DEST = m.DATA / 'omarchy-zones'
        m.MAIN = m.CONFIG / 'hypr/hyprland.lua'
        m.LAUNCHER = m.HOME / '.local/bin/omarchy-zones'
        m.DESKTOP = m.DATA / 'applications/omarchy-zones.desktop'
        m.MAIN.parent.mkdir(parents=True)
        self.original = b'-- existing configuration\no.user_settings()\n'
        m.MAIN.write_bytes(self.original)
        (m.ROOT / 'build').mkdir(parents=True)
        for name, contents in [('hyprland-hash.txt', 'abc123'), ('omarchy-zones.so', 'plugin'), ('omarchy-zones-editor', 'editor')]:
            (m.ROOT / 'build' / name).write_text(contents)
        self.loaded = False
        self.calls = []
        self.fail_reload_once = False
        self.concurrent_edit = b''
        self.fail_unload = False
        self.fail_load_once = False
        self.fail_load_after_start_once = False
        m.run = self.run_hyprctl
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def run_hyprctl(self, *args):
        self.calls.append(args)
        if args == ('hyprctl', '-j', 'plugin', 'list'):
            return json.dumps([{'name': 'omarchy-zones'}] if self.loaded else [])
        if args == ('hyprctl', 'configerrors'):
            return ''
        if args == ('hyprctl', '-j', 'version'):
            return '{"commit":"abc123"}'
        if args == ('hyprctl', '-j', 'binds'):
            return '[]'
        if args == ('hyprctl', 'reload'):
            if self.manage.BEGIN.encode() in self.manage.MAIN.read_bytes():
                self.loaded = True
            if self.concurrent_edit:
                with self.manage.MAIN.open('ab') as file:
                    file.write(self.concurrent_edit)
                self.concurrent_edit = b''
            if self.fail_reload_once:
                self.fail_reload_once = False
                raise RuntimeError('simulated reload failure')
            return 'ok'
        if args[:3] == ('hyprctl', 'plugin', 'unload'):
            if self.fail_unload:
                raise subprocess.CalledProcessError(1, args, 'simulated unload failure')
            self.loaded = False
            return 'ok'
        if args[:3] == ('hyprctl', 'plugin', 'load'):
            if self.fail_load_once:
                self.fail_load_once = False
                raise RuntimeError('simulated updated plugin failure')
            self.loaded = True
            if self.fail_load_after_start_once:
                self.fail_load_after_start_once = False
                raise RuntimeError('simulated load reply failure')
            return 'ok'
        raise AssertionError(args)

    def test_install_remove_restores_exact_bytes_and_retains_zones(self):
        m = self.manage
        self.original = b'-- no trailing newline'
        m.MAIN.write_bytes(self.original)
        zones = m.CONFIG / 'omarchy-zones/zones.json'
        zones.parent.mkdir()
        zones.write_text('{"zones":[]}')
        m.install()
        self.assertTrue(self.loaded)
        self.assertIn('float = true, center = true', (m.DEST / 'zones.lua').read_text())
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)
        self.assertFalse(self.loaded)
        self.assertFalse(m.DEST.exists())
        self.assertFalse(m.LAUNCHER.exists())
        self.assertFalse(m.DESKTOP.exists())
        self.assertEqual(zones.read_text(), '{"zones":[]}')

    def alternate_build(self):
        # Spaces and shell metacharacters must remain ordinary path characters.
        directory = Path(self.temp.name) / 'cache/build $literal; artifacts'
        directory.mkdir(parents=True)
        (directory / 'hyprland-hash.txt').write_text('abc123')
        for name, mode in zip(self.manage.BINARIES, (0o640, 0o750)):
            artifact = directory / name
            artifact.write_text('external ' + name)
            artifact.chmod(mode)
        return directory

    def assert_external_binaries(self, directory):
        m = self.manage
        manifest = json.loads((m.DEST / 'manifest.json').read_text())
        for name in m.BINARIES:
            source, installed = directory / name, m.DEST / name
            self.assertEqual(installed.read_bytes(), source.read_bytes())
            self.assertEqual(installed.stat().st_mode & 0o777, source.stat().st_mode & 0o777)
            self.assertEqual(manifest['owned'][str(installed)], m.digest(source))

    def test_cli_install_defaults_to_checkout_build(self):
        m = self.manage
        self.assertEqual(m.main(['install']), 0)
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')
        self.assertEqual((m.DEST / 'omarchy-zones-editor').read_text(), 'editor')
        self.assertEqual(m.main(['remove']), 0)
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_cli_install_uses_alternate_artifacts_and_hash(self):
        m = self.manage
        directory = self.alternate_build()
        (m.ROOT / 'build/hyprland-hash.txt').write_text('wrong-default-hash')
        self.assertEqual(m.main(['install', '--build-dir', str(directory)]), 0)
        self.assert_external_binaries(directory)
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_relative_build_directory_uses_callers_working_directory(self):
        m = self.manage
        directory = self.alternate_build()
        working_directory = Path(self.temp.name)
        with contextlib.chdir(working_directory):
            m.install(directory.relative_to(working_directory))
        self.assert_external_binaries(directory)

    def test_invalid_build_directory_does_not_change_configuration(self):
        m = self.manage
        for path in (Path(self.temp.name) / 'missing', Path(self.temp.name) / 'bad\npath'):
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, '[Bb]uild directory'):
                m.install(path)
            self.assertFalse(m.DEST.exists())
            self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_remove_preserves_unrelated_later_config_edit(self):
        m = self.manage
        m.install()
        with m.MAIN.open('ab') as file:
            file.write(b'-- later user edit\n')
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original + b'-- later user edit\n')

    def test_install_failure_rolls_back_and_preserves_concurrent_edit(self):
        m = self.manage
        self.fail_reload_once = True
        self.concurrent_edit = b'-- concurrent user edit\n'
        with self.assertRaisesRegex(RuntimeError, 'simulated reload failure'):
            m.install()
        self.assertEqual(m.MAIN.read_bytes(), self.original + b'-- concurrent user edit\n')
        self.assertFalse(m.DEST.exists())
        self.assertFalse(m.LAUNCHER.exists())
        self.assertFalse(self.loaded)

    def test_remove_already_unloaded_plugin(self):
        m = self.manage
        m.install()
        self.loaded = False
        before = len(self.calls)
        m.remove()
        self.assertFalse(any(call[:3] == ('hyprctl', 'plugin', 'unload') for call in self.calls[before:]))
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_preloaded_plugin_is_not_adopted(self):
        self.loaded = True
        with self.assertRaisesRegex(RuntimeError, 'already loaded outside'):
            self.manage.install()
        self.assertFalse(self.manage.DEST.exists())
        self.assertEqual(self.manage.MAIN.read_bytes(), self.original)

    def test_dangling_desktop_symlink_is_not_overwritten(self):
        m = self.manage
        m.DESKTOP.parent.mkdir(parents=True)
        m.DESKTOP.symlink_to('/nonexistent-zones-test')
        with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
            m.install()
        self.assertTrue(m.DESKTOP.is_symlink())
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_modified_owned_file_blocks_removal_without_changing_config(self):
        m = self.manage
        m.install()
        before = m.MAIN.read_bytes()
        m.LAUNCHER.write_text('user replacement')
        with self.assertRaisesRegex(RuntimeError, 'Owned file was edited'):
            m.remove()
        self.assertEqual(m.MAIN.read_bytes(), before)
        self.assertEqual(m.LAUNCHER.read_text(), 'user replacement')
        self.assertTrue(self.loaded)

    def test_unrecognized_install_directory_file_is_preserved(self):
        m = self.manage
        m.install()
        extra = m.DEST / 'user-notes.txt'
        extra.write_text('keep me')
        m.remove()
        self.assertEqual(extra.read_text(), 'keep me')
        self.assertFalse((m.DEST / 'omarchy-zones.so').exists())
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_failed_unload_restores_integration_and_keeps_files(self):
        m = self.manage
        m.install()
        before = m.MAIN.read_bytes()
        self.fail_unload = True
        with self.assertRaisesRegex(RuntimeError, 'still has Omarchy Zones loaded'):
            m.remove()
        self.assertEqual(m.MAIN.read_bytes(), before)
        self.assertTrue((m.DEST / 'omarchy-zones.so').exists())
        self.assertTrue(self.loaded)

    def test_edited_managed_block_blocks_removal(self):
        m = self.manage
        m.install()
        m.MAIN.write_bytes(m.MAIN.read_bytes().replace(b'dofile(', b'custom_dofile('))
        before = m.MAIN.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'managed block was edited'):
            m.remove()
        self.assertEqual(m.MAIN.read_bytes(), before)
        self.assertTrue(m.DEST.exists())

    def prepare_update(self):
        m = self.manage
        m.install()
        original_files = {path: path.read_bytes() for path in
                          (m.MAIN, m.LAUNCHER, m.DESKTOP, m.DEST / 'zones.lua',
                           m.DEST / 'hyprland.lua.before-install')}
        for name in m.BINARIES:
            (m.ROOT / 'build' / name).write_text('new ' + name)
        zones = m.CONFIG / 'omarchy-zones/zones.conf'
        zones.parent.mkdir()
        zones.write_text('omarchy-zones-v2\nprofile "Mine"\n')
        original_files[zones] = zones.read_bytes()
        return original_files

    def test_update_preserves_configuration_and_remains_removable(self):
        m = self.manage
        originals = self.prepare_update()
        calls_before = len(self.calls)
        m.update()
        self.assertTrue(self.loaded)
        self.assertNotIn(('hyprctl', 'reload'), self.calls[calls_before:])
        for path, contents in originals.items():
            self.assertEqual(path.read_bytes(), contents)
        manifest = json.loads((m.DEST / 'manifest.json').read_text())
        for name in m.BINARIES:
            self.assertEqual((m.DEST / name).read_text(), 'new ' + name)
            self.assertEqual(manifest['owned'][str(m.DEST / name)], m.digest(m.DEST / name))
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)
        self.assertTrue((m.CONFIG / 'omarchy-zones/zones.conf').exists())

    def test_cli_update_uses_alternate_build_and_preserves_configuration(self):
        m = self.manage
        originals = self.prepare_update()
        directory = self.alternate_build()
        (m.ROOT / 'build/hyprland-hash.txt').write_text('wrong-default-hash')
        self.assertEqual(m.main(['update', '--build-dir', str(directory)]), 0)
        self.assert_external_binaries(directory)
        for path, contents in originals.items():
            self.assertEqual(path.read_bytes(), contents)
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_alternate_build_abi_mismatch_is_rejected_before_unloading(self):
        m = self.manage
        originals = self.prepare_update()
        directory = self.alternate_build()
        (directory / 'hyprland-hash.txt').write_text('wrong-external-hash')
        calls_before = len(self.calls)
        with self.assertRaisesRegex(RuntimeError, 'running compositor and build headers differ'):
            m.update(directory)
        self.assertTrue(self.loaded)
        self.assertFalse(any(call[:2] == ('hyprctl', 'plugin') for call in self.calls[calls_before:]))
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')
        for path, contents in originals.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_alternate_build_rejects_symlink_artifacts_and_hash(self):
        m = self.manage
        directory = self.alternate_build()
        for name in (*m.BINARIES, 'hyprland-hash.txt'):
            path = directory / name
            contents = path.read_bytes()
            path.unlink()
            path.symlink_to(m.ROOT / 'build' / name)
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'must be regular|must be a regular'):
                m.install(directory)
            self.assertFalse(m.DEST.exists())
            self.assertEqual(m.MAIN.read_bytes(), self.original)
            path.unlink()
            path.write_bytes(contents)

    def test_update_preserves_unloaded_state(self):
        m = self.manage
        self.prepare_update()
        self.loaded = False
        calls_before = len(self.calls)
        m.update()
        self.assertFalse(self.loaded)
        self.assertFalse(any(call[:2] == ('hyprctl', 'plugin') for call in self.calls[calls_before:]))

    def test_failed_update_restores_binaries_manifest_and_loaded_state(self):
        m = self.manage
        originals = self.prepare_update()
        for path in (m.DEST / 'manifest.json', *(m.DEST / name for name in m.BINARIES)):
            originals[path] = path.read_bytes()
        self.fail_load_once = True
        with self.assertRaisesRegex(RuntimeError, 'simulated updated plugin failure'):
            m.update()
        self.assertTrue(self.loaded)
        for path, contents in originals.items():
            self.assertEqual(path.read_bytes(), contents)
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_update_second_binary_write_failure_rolls_back_first(self):
        m = self.manage
        self.prepare_update()
        original_manifest = (m.DEST / 'manifest.json').read_bytes()
        original_atomic = m.atomic

        def fail_editor(path, data, *args, **kwargs):
            if path == m.DEST / 'omarchy-zones-editor':
                raise OSError('simulated disk write failure')
            return original_atomic(path, data, *args, **kwargs)

        with patch.object(m, 'atomic', side_effect=fail_editor):
            with self.assertRaisesRegex(OSError, 'simulated disk write failure'):
                m.update()
        self.assertTrue(self.loaded)
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')
        self.assertEqual((m.DEST / 'omarchy-zones-editor').read_text(), 'editor')
        self.assertEqual((m.DEST / 'manifest.json').read_bytes(), original_manifest)

    def test_update_recovers_when_load_reply_fails_after_plugin_started(self):
        m = self.manage
        self.prepare_update()
        manifest = (m.DEST / 'manifest.json').read_bytes()
        self.fail_load_after_start_once = True
        with self.assertRaisesRegex(RuntimeError, 'simulated load reply failure'):
            m.update()
        self.assertTrue(self.loaded)
        self.assertEqual((m.DEST / 'manifest.json').read_bytes(), manifest)
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')

    def test_update_rejects_wrong_abi_before_unloading(self):
        m = self.manage
        self.prepare_update()
        (m.ROOT / 'build/hyprland-hash.txt').write_text('different')
        calls_before = len(self.calls)
        with self.assertRaisesRegex(RuntimeError, 'running compositor and build headers differ'):
            m.update()
        self.assertTrue(self.loaded)
        self.assertFalse(any(call[:2] == ('hyprctl', 'plugin') for call in self.calls[calls_before:]))
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')

    def test_update_rejects_modified_and_missing_owned_files(self):
        m = self.manage
        self.prepare_update()
        m.LAUNCHER.write_text('user changed launcher')
        with self.assertRaisesRegex(RuntimeError, 'Owned file was edited'):
            m.update()
        m.LAUNCHER.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Owned file is missing'):
            m.update()
        self.assertTrue(self.loaded)
        self.assertEqual((m.DEST / 'omarchy-zones.so').read_text(), 'plugin')

    def test_untrusted_manifest_cannot_redirect_removal(self):
        m = self.manage
        m.install()
        manifest_path = m.DEST / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        unrelated = m.HOME / 'important.txt'
        unrelated.write_text('keep me')
        manifest['owned'][str(unrelated)] = m.digest(unrelated)
        manifest_path.write_text(json.dumps(manifest))
        before = m.MAIN.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'unexpected paths'):
            m.remove()
        self.assertEqual(unrelated.read_text(), 'keep me')
        self.assertEqual(m.MAIN.read_bytes(), before)

    def test_relative_xdg_path_is_rejected(self):
        m = self.manage
        m.DATA = Path('relative-data')
        with self.assertRaisesRegex(RuntimeError, 'must be absolute'):
            m.install()
        self.assertEqual(m.MAIN.read_bytes(), self.original)

    def test_unicode_and_percent_paths_are_escaped_for_each_format(self):
        m = self.manage
        m.DATA = m.HOME / 'data-हिंदी-%'
        m.DEST = m.DATA / 'omarchy-zones'
        m.DESKTOP = m.DATA / 'applications/omarchy-zones.desktop'
        m.LAUNCHER = m.HOME / '.local/bin/editor-%'
        m.install()
        self.assertIn('data-हिंदी-%', m.MAIN.read_text())
        self.assertNotIn('\\u', m.MAIN.read_text())
        self.assertIn('editor-%%"', m.DESKTOP.read_text())
        m.remove()
        self.assertEqual(m.MAIN.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
