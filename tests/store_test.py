#!/usr/bin/env python3
"""Exercise Store.qml through real offscreen Quickshell and private fixture files.

Python belongs to this test harness only. Product persistence uses asynchronous
Quickshell FileView operations, including a fresh read to verify each save.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = (ROOT / json.loads((ROOT / "manifest.json").read_text())["entryPoints"]["service"]).parent
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

    def run_qml(self, body):
        source = f'''import QtQuick
import Quickshell
import Quickshell.Io
import {json.dumps(PLUGIN.as_uri())} as Zones
ShellRoot {{
    {body}
    Timer {{ interval: 8500; running: true; onTriggered: {{ console.error("STORE_TIMEOUT"); Qt.quit() }} }}
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

    def run_store(self, action, condition):
        self.run_qml(f'''
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
    Component.onCompleted: {{ armed = true; if (!({action})) Qt.callLater(check) }}
''')

    def assert_no_helpers(self):
        # The fixture and its unique runtime must leave no process behind.
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
        self.fixture(VALID.replace("Default", "étude अध्ययन 🪟"))
        self.run_store("store.load()", 'store.ready && !store.error && store.profiles[0].name === "étude अध्ययन 🪟"')

    def test_atomic_write_to_missing_directory_and_literal_paths(self):
        self.path = self.base / 'space $(touch SHOULD_NOT_EXIST)' / 'zones.conf'
        definitions = [{"name": 'Quotes " $() `literal` \\ अध्ययन', "layouts": [
            {"monitor": "DP-2", "zones": [{"x": 0, "y": 0, "w": 640, "h": 480}]}]}]
        self.run_store("store.save(" + json.dumps(definitions) + ")", "store.ready && !store.error && !store.fresh")
        self.assertIn('DP-2 0 0 640 480', self.path.read_text())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertFalse((self.base / "SHOULD_NOT_EXIST").exists())

    def test_fifo_refused_without_waiting(self):
        self.path.parent.mkdir()
        os.mkfifo(self.path)
        start = time.monotonic()
        self.run_store("store.load()", "!store.ready && store.error.length > 0")
        self.assertLess(time.monotonic() - start, 3)

    def test_symlink_uses_fileview_target_semantics(self):
        self.path.parent.mkdir()
        target = self.base / "sentinel"
        target.write_text(VALID)
        self.path.symlink_to(target)
        self.run_store("store.load()", "store.ready && !store.error")
        self.run_store('store.save([{name:"New",layouts:[]}])', "store.ready && !store.error")
        self.assertEqual(target.read_text(), 'omarchy-zones-v2\nprofile "New"\n')
        self.assertTrue(self.path.is_symlink())

    def test_oversize_and_invalid_utf8_refused(self):
        invalid = [b"\xff", b"\x80", b"\xc0\xaf", b"\xe0\x80\x80", b"\xed\xa0\x80",
                   b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf0\x9f\xaa", b"\xc2A"]
        for contents in [VALID.encode() + b"# comment\n" * 14000] + [
                b'omarchy-zones-v2\nprofile "' + value + b'"\n' for value in invalid]:
            with self.subTest(contents=contents[:64]):
                self.fixture(contents)
                self.run_store("store.load()", "!store.ready && store.error.length > 0")
                self.assertEqual(self.path.read_bytes(), contents)

    def test_exact_size_limit(self):
        size = 131072
        contents = VALID.encode()
        full_lines, remainder = divmod(size - len(contents), 512)
        contents += (b"#" + b"x" * 510 + b"\n") * full_lines
        contents += (b"#" + b"x" * (remainder - 1)) if remainder else b""
        self.fixture(contents)
        self.assertEqual(len(contents), size)
        self.run_store("store.load()", "store.ready && !store.error")

    def test_invalid_save_preserves_existing_file(self):
        self.fixture(VALID)
        self.run_store('store.save([{name:"Bad",layouts:[{monitor:"DP-2",zones:['
                       '{x:0,y:0,w:100,h:100},{x:50,y:0,w:100,h:100}]}]}])',
                       '!store.busy && store.error.length > 0')
        self.assertEqual(self.path.read_text(), VALID)

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

    def test_readback_mismatch_does_not_acknowledge_save(self):
        # Replace the file exactly between the completed write and verification.
        # This exercises real FileView I/O, including rejection of a false success.
        self.fixture(VALID)
        self.run_qml(f'''
    property int stage: 0
    property int acknowledgments: 0
    FileView {{ id: replacement; path: {json.dumps(str(self.path))}; preload: false; blockWrites: true }}
    Zones.Store {{
        id: store
        path: {json.dumps(str(self.path))}
        onLoaded: if (stage === 0) {{ stage = 1; save([{{name:"Desired",layouts:[]}}]) }}
        onOperationChanged: if (operation === "verify") replacement.setText({json.dumps(VALID.replace('Default', 'External'))})
        onSaved: acknowledgments++
        onBusyChanged: if (!busy && stage === 1 && error) Qt.callLater(check)
    }}
    function check() {{
        if (acknowledgments === 0 && store.profiles[0].name === "Default" && store.error.indexOf("verified") >= 0)
            console.log("STORE_PASS")
        else console.error("STORE_FAIL", store.error, JSON.stringify(store.profiles))
        Qt.quit()
    }}
    Component.onCompleted: store.load()
''')
        self.assertIn('profile "External"', self.path.read_text())

    def test_repeated_identical_save_uses_disk_and_snapshot(self):
        self.run_qml(f'''
    property int acknowledgments: 0
    property var draft: [{{name:"Desired",layouts:[]}}]
    FileView {{ id: replacement; path: {json.dumps(str(self.path))}; preload: false; blockWrites: true }}
    Zones.Store {{
        id: store
        path: {json.dumps(str(self.path))}
        onSaved: {{
            acknowledgments++
            if (acknowledgments === 1) {{
                replacement.setText({json.dumps(VALID.replace('Default', 'External'))})
                Qt.callLater(repeatSave)
            }} else {{
                if (profiles[0].name === "Desired" && draft[0].name === "Newer") console.log("STORE_PASS")
                else console.error("STORE_FAIL", JSON.stringify(profiles))
                Qt.quit()
            }}
        }}
        onErrorChanged: if (error) {{ console.error("STORE_FAIL", error); Qt.quit() }}
    }}
    function repeatSave() {{
        draft[0].name = "Desired"
        store.save(draft)
        draft[0].name = "Newer"
    }}
    Component.onCompleted: repeatSave()
''')
        self.assertEqual(self.path.read_text(), 'omarchy-zones-v2\nprofile "Desired"\n')

    def test_save_watcher_settles_without_reload_loop(self):
        self.run_qml(f'''
    property int loads: 0
    property int settledLoads: -1
    property int acknowledgments: 0
    Zones.Store {{
        id: store
        path: {json.dumps(str(self.path))}
        onLoaded: loads++
        onSaved: {{ acknowledgments++; settle.restart(); check.restart() }}
    }}
    Timer {{ id: settle; interval: 200; onTriggered: settledLoads = loads }}
    Timer {{ id: check; interval: 450; onTriggered: {{
        if (!store.busy && !store.error && acknowledgments === 1 && settledLoads === loads) console.log("STORE_PASS")
        else console.error("STORE_FAIL", loads, settledLoads, acknowledgments, store.error)
        Qt.quit()
    }} }}
    Component.onCompleted: store.save([{{name:"Desired",layouts:[]}}])
''')


if __name__ == "__main__":
    unittest.main()
