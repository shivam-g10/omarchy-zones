#!/usr/bin/env python3
"""Check the explicit setup/launcher boundary without touching the desktop."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zones-packaging-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.log = self.home / 'commands.jsonl'
        self.env = os.environ.copy()
        for key in ('OMARCHY_ZONES_BUILD_DIR', 'CMAKE_BUILD_PARALLEL_LEVEL'):
            self.env.pop(key, None)
        self.env.update(HOME=str(self.home), XDG_DATA_HOME=str(self.home / 'data space'),
                        XDG_CACHE_HOME=str(self.home / 'cache space'),
                        PATH=str(self.bin) + ':/usr/bin', ZONES_TEST_LOG=str(self.log))

    def recorder(self, name):
        target = self.bin / name
        target.write_text('#!/usr/bin/python3\nimport json, os, sys\n'
                          'with open(os.environ["ZONES_TEST_LOG"], "a") as f:\n'
                          '    f.write(json.dumps(sys.argv) + "\\n")\n')
        target.chmod(0o755)

    def run_script(self, name, *args):
        return subprocess.run(['/usr/bin/bash', str(ROOT / 'scripts' / name), *args],
                              env=self.env, text=True, capture_output=True, timeout=5)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_launcher_executes_only_installed_editor_and_preserves_exit(self):
        editor = Path(self.env['XDG_DATA_HOME']) / 'omarchy-zones/omarchy-zones-editor'
        editor.parent.mkdir(parents=True)
        editor.write_text('#!/usr/bin/bash\nprintf "editor started\\n"\nexit 7\n')
        editor.chmod(0o755)
        result = self.run_script('launch-editor.sh')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'editor started\n')
        self.assertFalse(self.log.exists())

    def test_missing_editor_notifies_without_building_or_installing(self):
        self.recorder('notify-send')
        result = self.run_script('launch-editor.sh')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Build and install the native component first', result.stderr)
        self.assertEqual(len(self.commands()), 1)
        self.assertIn('Native setup required', self.commands()[0])

    def test_install_builds_outside_checkout_then_invokes_manager(self):
        self.recorder('cmake')
        self.recorder('python3')
        result = self.run_script('setup.sh', 'install')
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        expected = str(Path(self.env['XDG_CACHE_HOME']) / 'omarchy-zones/build')
        self.assertEqual(len(commands), 3)
        self.assertIn(expected, commands[0])
        self.assertIn('-DOMARCHY_ZONES_BUILD_PLUGIN=ON', commands[0])
        self.assertIn('-DBUILD_TESTING=OFF', commands[0])
        self.assertEqual(commands[-1][1:], [str(ROOT / 'scripts/manage.py'), 'install', '--build-dir', expected])

    def test_update_uses_explicit_build_path_without_shell_evaluation(self):
        self.recorder('cmake')
        self.recorder('python3')
        build = str(self.home / 'custom space $(no-execution)')
        self.env['OMARCHY_ZONES_BUILD_DIR'] = build
        result = self.run_script('setup.sh', 'update')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands()[-1][1:], [str(ROOT / 'scripts/manage.py'), 'update', '--build-dir', build])

    def test_removal_does_not_require_compiler(self):
        self.recorder('python3')
        result = self.run_script('setup.sh', 'remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(self.commands()[0][1:], [str(ROOT / 'scripts/manage.py'), 'remove'])

    def test_build_does_not_install(self):
        self.recorder('cmake')
        result = self.run_script('setup.sh', 'build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commands()), 2)


if __name__ == '__main__':
    unittest.main()
