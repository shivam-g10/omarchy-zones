#!/usr/bin/env python3
"""Exercise Store.qml through real offscreen Quickshell and private fixture files.

Python belongs to this test harness only. Product persistence uses installed
coreutils commands through Quickshell.Process.
"""

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "shell"
VALID = 'omarchy-zones-v2\nprofile "Default"\nDP-2 0 0 640 480\n'


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zones-store-test-")
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.path = self.base / "config" / "zones.conf"
        self.environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                                QT_QPA_PLATFORMTHEME="", QT_STYLE_OVERRIDE="Fusion",
                                HOME=str(self.base), XDG_RUNTIME_DIR=str(self.runtime),
                                XDG_CONFIG_HOME=str(self.base / "config"),
                                XDG_CACHE_HOME=str(self.base / "cache"),
                                XDG_DATA_HOME=str(self.base / "data"),
                                XDG_STATE_HOME=str(self.base / "state"))
        self.environment.pop("DISPLAY", None)
        self.environment.pop("WAYLAND_DISPLAY", None)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, contents):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(contents if isinstance(contents, bytes) else contents.encode())

    def run_store(self, action, condition):
        source = f'''import QtQuick
import Quickshell
import {json.dumps(PLUGIN.as_uri())} as Zones
ShellRoot {{
    property bool armed: false
    Zones.Store {{
        id: store
        path: {json.dumps(str(self.path))}
        onBusyChanged: if (!busy && armed) Qt.callLater(check)
    }}
    function check() {{
        if (store.busy) return
        if ({condition}) console.log("STORE_PASS")
        else console.error("STORE_FAIL", store.error, JSON.stringify(store.profiles))
        Qt.quit()
    }}
    Timer {{ interval: 8500; running: true; onTriggered: {{ console.error("STORE_TIMEOUT"); Qt.quit() }} }}
    Component.onCompleted: {{ armed = true; if (!({action})) Qt.callLater(check) }}
}}
'''
        qml = self.base / "shell.qml"
        qml.write_text(source)
        result = subprocess.run(["qs", "-p", str(qml)], env=self.environment,
                                text=True, capture_output=True, timeout=12)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("STORE_PASS", output, output)
        self.assertNotIn("STORE_FAIL", output, output)
        self.assertNotIn("STORE_TIMEOUT", output, output)
        self.assert_no_helpers()

    def assert_no_helpers(self):
        # A child killed during unload has at most the command's 4s deadline.
        # Successful operations should leave no matching helper immediately.
        marker = f"XDG_RUNTIME_DIR={self.runtime}".encode()
        remaining = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if marker in (entry / "environ").read_bytes().split(b"\0"):
                    remaining.append(entry.name)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        self.assertEqual(remaining, [], f"Fixture helpers remain: {remaining}")

    def test_missing_file_stays_missing(self):
        self.run_store("store.load()", "store.ready && store.fresh && !store.error && store.profiles.length === 0")
        self.assertFalse(self.path.exists())

    def test_unicode_read(self):
        self.fixture(VALID.replace("Default", "अध्ययन"))
        self.run_store("store.load()", 'store.ready && !store.error && store.profiles[0].name === "अध्ययन"')

    def test_private_atomic_write_and_literal_arguments(self):
        self.path = self.base / 'space $(touch SHOULD_NOT_EXIST)' / 'zones.conf'
        definitions = [{"name": 'Quotes " $() `literal` \\ अध्ययन', "layouts": [
            {"monitor": "DP-2", "zones": [{"x": 0, "y": 0, "w": 640, "h": 480}]}]}]
        self.run_store("store.save(" + json.dumps(definitions) + ")", "store.ready && !store.error && !store.fresh")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertIn('DP-2 0 0 640 480', self.path.read_text())
        self.assertEqual(list(self.path.parent.glob('.zones-save.*')), [])
        self.assertFalse((self.base / "SHOULD_NOT_EXIST").exists())

    def test_fifo_refused_without_waiting(self):
        self.path.parent.mkdir()
        os.mkfifo(self.path)
        start = time.monotonic()
        self.run_store("store.load()", "!store.ready && store.error.length > 0")
        self.assertLess(time.monotonic() - start, 3)

    def test_symlink_read_and_write_refused(self):
        self.path.parent.mkdir()
        target = self.base / "sentinel"
        target.write_text(VALID)
        self.path.symlink_to(target)
        self.run_store("store.load()", "!store.ready && store.error.length > 0")
        self.run_store('store.save([{name:"New",layouts:[]}])', "!store.ready && store.error.length > 0")
        self.assertEqual(target.read_text(), VALID)
        self.assertTrue(self.path.is_symlink())

    def test_oversize_and_invalid_utf8_refused(self):
        for contents in [VALID.encode() + b"# comment\n" * 14000,
                         b'omarchy-zones-v2\nprofile "\xff"\n']:
            self.fixture(contents)
            self.run_store("store.load()", "!store.ready && store.error.length > 0")
            self.assertEqual(self.path.read_bytes(), contents)

    def test_nonregular_save_target_preserved(self):
        self.path.mkdir(parents=True)
        sentinel = self.path / "sentinel"
        sentinel.write_text("unchanged")
        self.run_store('store.save([{name:"New",layouts:[]}])', "!store.ready && store.error.length > 0")
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_external_atomic_replacement_is_watched(self):
        self.fixture(VALID)
        qml = self.base / "shell.qml"
        qml.write_text(f'''import QtQuick
import Quickshell
import {json.dumps(PLUGIN.as_uri())} as Zones
ShellRoot {{
    property int stage: 0
    Zones.Store {{
        id: store
        path: {json.dumps(str(self.path))}
        onLoaded: {{
            if (stage === 0) {{ stage = 1; console.log("STORE_READY") }}
            else if (profiles[0].name === "External") {{ console.log("STORE_PASS"); Qt.quit() }}
        }}
        onBusyChanged: if (!busy && error) {{ console.error("STORE_FAIL", error); Qt.quit() }}
    }}
    Timer {{ interval: 8500; running: true; onTriggered: {{ console.error("STORE_TIMEOUT"); Qt.quit() }} }}
    Component.onCompleted: store.load()
}}
''')
        with subprocess.Popen(["qs", "-p", str(qml)], env=self.environment,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            output = []
            for line in process.stdout:
                output.append(line)
                if "STORE_READY" in line:
                    replacement = self.path.with_suffix(".replacement")
                    replacement.write_text(VALID.replace("Default", "External"))
                    os.replace(replacement, self.path)
            process.wait(timeout=2)
        self.assertIn("STORE_PASS", "".join(output), "".join(output))
        self.assert_no_helpers()

    def test_supervisor_cleans_children_after_qml_unload(self):
        # Exercise the production supervisor with an intentionally slow command.
        # QML destruction kills only the immediate Process child; timeout must
        # remain alive long enough to terminate the entire slow command group.
        qml = self.base / "shell.qml"
        qml.write_text(f'''import QtQuick
import Quickshell
import Quickshell.Io
import {json.dumps(PLUGIN.as_uri())} as Zones
ShellRoot {{
    Zones.Store {{ id: store; path: {json.dumps(str(self.path))} }}
    Process {{
        id: slow
        command: ["/usr/bin/bash", "-c", store.superviseScript, "zones-test-supervisor",
                  "/usr/bin/bash", "-c", "sleep 30 & wait"]
        running: true
        onStarted: stop.restart()
    }}
    Timer {{ id: stop; interval: 150; onTriggered: Qt.quit() }}
}}
''')
        result = subprocess.run(["qs", "-p", str(qml)], env=self.environment,
                                text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # This is a bounded test wait, never a product polling loop.
        time.sleep(5.1)
        self.assert_no_helpers()


if __name__ == "__main__":
    unittest.main()
