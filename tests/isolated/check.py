#!/usr/bin/env python3
"""Opt-in native checks. All input and product changes target lab.py's private desktop."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import time

import lab
from gestures import Input, META, SHIFT, clients, get, geometry, place, private_environment, snapshot, wait_for

ROOT, LAB = lab.ROOT, lab.LAB
OUT = ROOT / "evidence/lifecycle-0.5.0"
TARGET, SENTINEL, EDITOR = "Zones target", "Zones sentinel", "Omarchy Zones"


def ipc(method, *args):
    return lab.run(["omarchy-shell", "omarchy-zones", method, *map(str, args)], private_environment())


def status():
    return json.loads(ipc("status"))


def ready():
    def check():
        try:
            s = status()
            if s.get("runtimeError"):
                raise AssertionError(s["runtimeError"])
            return s if s.get("runtimeReady") and s["ready"] and not s["waiting"] and not s["storeBusy"] else None
        except RuntimeError:
            return None
    return wait_for(check, timeout=10)


def plugin(action, *args):
    return lab.run(["omarchy", "plugin", action, *map(str, args)], private_environment(), timeout=40)


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def monitor():
    return json.loads(lab.ctl("-j", "monitors"))[0]


def bounds():
    m = monitor()
    r = m["reserved"]
    return r[0], r[1], m["width"] - r[0] - r[2], m["height"] - r[1] - r[3]


def config_path():
    return Path(private_environment()["XDG_CONFIG_HOME"]) / "omarchy-zones/zones.conf"


def definitions():
    x, y, w, h = bounds()
    rows = ["omarchy-zones-v2"]
    for count in (2, 3):
        rows.append('profile "' + ("Split" if count == 2 else "Thirds") + '"')
        for i in range(count):
            left, right = w * i // count, w * (i + 1) // count
            rows.append(f'{monitor()["name"]} {x + left} {y} {right-left} {h}')
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n")
    return path


def install():
    private_environment()
    source = ROOT / "build/native-source"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir()
    shutil.copy2(ROOT / "manifest.json", source / "manifest.json")
    shutil.copytree(ROOT / "qml", source / "qml")
    lab.run(["git", "init", "-q", str(source)])
    lab.run(["git", "-C", str(source), "add", "."])
    lab.run(["git", "-C", str(source), "-c", "user.name=Native fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "Fixture snapshot"])
    definitions()
    before = hashlib.sha256((LAB / "hyprland.lua").read_bytes()).hexdigest()
    output = plugin("add", source, "--enable", "--yes")
    # The host also debounces filesystem notifications for 150 ms after add.
    time.sleep(.4)
    s = ready()
    assert before == hashlib.sha256((LAB / "hyprland.lua").read_bytes()).hexdigest()
    assert not (LAB / "home/.local/bin/omarchy-zones").exists()
    assert not (LAB / "home/.local/share/applications/omarchy-zones.desktop").exists()
    save("install.json", {"passed": True, "output": output, "status": s, "hyprland_sha256": before})


def windows():
    for title in (TARGET, SENTINEL):
        if not any(c["title"] == title for c in clients()):
            command = shlex.join([str(ROOT / "build/tests/native-window"), title])
            lab.ctl("eval", "hl.exec_cmd(" + json.dumps(command) + ")")
            wait_for(lambda: get(title))
    place(SENTINEL, 1700, 900, 500, 300)
    place(TARGET, 250, 400, 600, 400)


def press(device, key):
    device.key(key, True)
    device.key(key, False)


def begin(device):
    place(TARGET, 250, 400, 600, 400)
    device.move(500, 600)
    device.key(META, True)
    device.key(SHIFT, True)
    device.button(True)
    device.move(520, 610)
    return wait_for(lambda: status()["active"] and not status()["waiting"])


def release(device):
    device.button(False)
    device.key(SHIFT, False)
    device.key(META, False)
    wait_for(lambda: not status()["active"] and not status()["waiting"])


def snap(device, profile=0, zone=1):
    begin(device)
    picker = json.loads(ipc("pickerState"))
    rect = picker["picker"]["cards"][profile]["miniZones"][zone]
    device.move(picker["bounds"]["x"] + rect["x"] + rect["w"] / 2,
                picker["bounds"]["y"] + rect["y"] + rect["h"] / 2)
    wait_for(lambda: status()["profile"] == profile and status()["zone"] == zone)
    expected = picker["profiles"][profile]["zones"][zone]
    expected = [picker["bounds"]["x"] + expected["x"], picker["bounds"]["y"] + expected["y"], expected["w"], expected["h"]]
    release(device)
    wait_for(lambda: get(TARGET)["at"] + get(TARGET)["size"] == expected)
    return expected


def editor_state():
    return json.loads(ipc("editorState"))


def click(device, point):
    at = get(EDITOR)["at"]
    device.move(at[0] + point["x"], at[1] + point["y"])
    device.button(True)
    device.button(False)


def correctness():
    ready()
    windows()
    rows = []
    sentinel = geometry(get(SENTINEL))
    with Input() as device:
        for i in range(20):
            snap(device, i % 2, 1)
            assert geometry(get(SENTINEL)) == sentinel
        rows.append("20 native snaps selected the captured window and both profiles correctly")
        begin(device)
        device.key(SHIFT, False)
        wait_for(lambda: not status()["active"])
        device.button(False)
        device.key(META, False)
        q = status()["queries"]
        time.sleep(.3)
        assert status()["queries"] == q
        rows.append("modifier cancellation removes overlay and stops cursor queries")
        place(TARGET, 250, 400, 600, 400)
        device.move(500, 600)
        device.key(META, True)
        device.button(True)
        device.scheduled_path([(500, 600), (900, 700)], .3, monitor()["refreshRate"])
        device.button(False)
        device.key(META, False)
        wait_for(lambda: get(TARGET)["at"] == [650, 500])
        assert get(TARGET)["size"] == [600, 400] and not status()["active"]
        rows.append("ordinary Super+drag keeps its native geometry and never activates zones")

        unchanged = snapshot([TARGET, SENTINEL])
        device.key(META, True)
        device.key(SHIFT, True)
        press(device, 66)  # F8
        device.key(SHIFT, False)
        device.key(META, False)
        wait_for(lambda: get(EDITOR))
        assert get(EDITOR)["floating"] and not get(EDITOR)["xwayland"]
        place(EDITOR, 100, 80, 1160, 740)
        time.sleep(.2)
        state = editor_state()
        boundary = state["boundary"]
        old = state["rectangles"]
        at = get(EDITOR)["at"]
        device.move(at[0] + boundary["x"], at[1] + boundary["y"])
        device.button(True)
        device.scheduled_path([(at[0] + boundary["x"], at[1] + boundary["y"]),
                               (at[0] + boundary["x"] + 40, at[1] + boundary["y"])], .3, monitor()["refreshRate"])
        device.button(False)
        state = wait_for(lambda: (s if (s := editor_state())["rectangles"] != old else None))
        a, b = state["rectangles"][:2]
        assert a[2] > old[0][2] and b[2] < old[1][2] and a[0] + a[2] == b[0]
        rows.append("mouse shared-boundary edit grows one zone and shrinks its neighbor")
        click(device, {"x": state["canvas"]["originX"] + a[2] * state["canvas"]["scale"] / 2,
                       "y": state["canvas"]["originY"] + a[3] * state["canvas"]["scale"] / 2})
        wait_for(lambda: editor_state()["selectedZone"] == 0)
        click(device, state["controls"]["widthValue"])
        wait_for(lambda: editor_state()["inputs"][2]["focus"])
        device.key(29, True)
        press(device, 30)
        device.key(29, False)
        value = bounds()[2] // 2 + 100
        for digit in str(value):
            press(device, 11 if digit == "0" else int(digit) + 1)
        wait_for(lambda: editor_state()["inputs"][2]["text"] == str(value))
        press(device, 28)
        state = wait_for(lambda: (s if (s := editor_state())["rectangles"][0][2] == value else None))
        for _ in range(3):
            ipc("openEditor")
        assert len([c for c in clients() if c["title"] == EDITOR]) == 1
        assert editor_state()["rectangles"] == state["rectangles"]
        click(device, state["controls"]["saveZones"])
        wait_for(lambda: not status()["storeBusy"] and not editor_state()["dirty"])
        assert not status()["storeError"] and snapshot([TARGET, SENTINEL]) == unchanged
        rows.append("numeric edit, single editor instance and verified save leave existing windows unchanged")
        ipc("closeEditor")
        wait_for(lambda: editor_state() is None)
        assert snapshot([TARGET, SENTINEL]) == unchanged
        save("correctness.json", {"passed": True, "checks": rows, "monitor": monitor(), "status": status()})
    print(json.dumps(rows, indent=2), flush=True)


def lifecycle():
    ready()
    windows()
    checks = []
    config_hash = hashlib.sha256((LAB / "hyprland.lua").read_bytes()).hexdigest()
    saved = config_path().read_bytes()
    initial_binds = json.loads(lab.ctl("-j", "binds"))
    initial_slots = status().get("runtimeSlots")
    assert initial_slots and initial_slots["timers"] == 1
    # A foreign bind deliberately shares the editor chord. Exact disable must
    # preserve it, while the next enable should refuse the collision.
    lab.ctl("eval", 'zones_test_foreign = hl.bind("SUPER + SHIFT + F8", function() zones_test_hits = (zones_test_hits or 0) + 1 end, {description="zones-test-foreign"})')
    plugin("disable", "omarchy-zones")
    with Input() as device:
        device.key(META, True); device.key(SHIFT, True); press(device, 66)
        device.key(SHIFT, False); device.key(META, False)
    assert lab.ctl("eval", 'assert(zones_test_hits == 1, "Foreign binding did not fire exactly once")').strip() == "ok"
    checks.append("foreign same-chord binding survives plugin disable")
    plugin("enable", "omarchy-zones")
    wait_for(lambda: status().get("runtimeError"))
    assert not status()["runtimeReady"]
    checks.append("conflicting hotkey refuses activation without deleting foreign binding")
    # This Hyprland's binds IPC omits enabled state. A normal private config
    # reload drops the deliberately injected foreign binding and old registry.
    lab.ctl("reload")
    ready()
    for i in range(20):
        plugin("disable", "omarchy-zones")
        plugin("enable", "omarchy-zones")
        ready()
        assert status().get("runtimeSlots") == initial_slots
    checks.append("20 disable/enable cycles retain constant owned registration counts")
    with Input() as device:
        for i in range(100):
            if i % 2 == 0:
                snap(device, i % 2, 1)
            else:
                begin(device)
                device.key(SHIFT, False)
                device.button(False)
                device.key(META, False)
                wait_for(lambda: not status()["active"])
        assert status().get("runtimeSlots") == initial_slots
        begin(device)
        plugin("disable", "omarchy-zones")
        device.button(False); device.key(SHIFT, False); device.key(META, False)
        plugin("enable", "omarchy-zones")
        ready()
        assert not status()["active"] and not status()["visualsActive"]
    checks.append("100 release/cancellation cycles and disable during native drag leave no active gesture")
    lab.ctl("reload")
    ready()
    assert lab.ctl("configerrors") in ("", "ok")
    assert len(json.loads(lab.ctl("-j", "binds"))) == len(initial_binds)
    checks.append("compositor configuration reload recreates integration without duplicates")
    lab.restart_shell()
    ready()
    with Input() as device:
        snap(device)
    checks.append("shell restart recovers native snapping")
    with Input() as device:
        begin(device)
        before_crash = snapshot([TARGET, SENTINEL])
        os.kill(lab.status()["shell_pid"], signal.SIGKILL)
        device.button(False); device.key(SHIFT, False); device.key(META, False)
    lab.restart_shell()
    ready()
    assert not status()["active"] and snapshot([TARGET, SENTINEL]) == before_crash
    checks.append("abrupt private shell death cannot apply a stale snap after restart")
    before_update = status()
    shell_before_update = lab.status()["shell_pid"]
    source = ROOT / "build/native-source"
    manifest = json.loads((source / "manifest.json").read_text())
    old_runtime = source / Path(manifest["entryPoints"]["service"]).parent
    manifest["version"] = "0.5.1"
    manifest["entryPoints"]["service"] = "qml/0.5.1/Service.qml"
    next_runtime = source / "qml/0.5.1"
    old_runtime.rename(next_runtime)
    service = next_runtime / "Service.qml"
    service.write_text(service.read_text().replace("runtimeReady: root.runtimeReady,", 'runtimeReady: root.runtimeReady, fixtureRevision: "new-code",'))
    (source / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    lab.run(["git", "-C", str(source), "add", "-A"])
    lab.run(["git", "-C", str(source), "-c", "user.name=Native fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "Exercise official update"])
    plugin("update", "omarchy-zones", "--yes")
    # Wait for the host's additional filesystem-triggered reload to settle.
    time.sleep(.4)
    ready()
    wait_for(lambda: status().get("fixtureRevision") == "new-code")
    assert lab.status()["shell_pid"] == shell_before_update
    with Input() as device:
        snap(device)
    checks.append("standard update executes changed QML and snaps without a shell restart")
    plugin("remove", "omarchy-zones", "--yes")
    assert not (LAB / "home/.config/omarchy/plugins/omarchy-zones").exists()
    assert config_path().read_bytes() == saved
    assert hashlib.sha256((LAB / "hyprland.lua").read_bytes()).hexdigest() == config_hash
    checks.append("standard update/remove preserve profiles and Hyprland config bytes")
    save("lifecycle.json", {"passed": True, "checks": checks, "slots": initial_slots, "status_before_remove": before_update})
    print(json.dumps(checks, indent=2), flush=True)


def resources():
    ready()
    windows()
    group = Path("/sys/fs/cgroup") / lab.status()["control_group"].lstrip("/")

    def sample():
        cpu = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
        pss = private = rss = 0
        names = []
        for pid in lab.cgroup_pids(str(group.relative_to("/sys/fs/cgroup"))):
            try:
                stat = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()[1:])
                pss += int(stat["Pss"].split()[0]); rss += int(stat["Rss"].split()[0])
                private += sum(int(stat[k].split()[0]) for k in ("Private_Clean", "Private_Dirty"))
                names.append(Path(f"/proc/{pid}/comm").read_text().strip())
            except (FileNotFoundError, ProcessLookupError):
                pass
        return {"time": time.monotonic(), "cpu_us": int(cpu["usage_usec"]), "pss_kib": pss,
                "private_kib": private, "rss_kib": rss, "cgroup_bytes": int((group / "memory.current").read_text()),
                "cgroup_peak_bytes": int((group / "memory.peak").read_text()), "processes": names}

    rows = []

    def phase(name, duration=30, action=None):
        start = sample()
        if action:
            action()
        else:
            time.sleep(duration)
        end = sample()
        seconds = end["time"] - start["time"]
        row = {"phase": name, "seconds": seconds, "cpu_percent_one_core": (end["cpu_us"] - start["cpu_us"]) / seconds / 10000,
               "start": start, "end": end}
        rows.append(row)
        save("resources.json", rows)
        print(json.dumps({k:v for k,v in row.items() if k not in ("start", "end")}), flush=True)

    for round_number in range(2):
        modes = (False, True) if round_number == 0 else (True, False)
        for enabled in modes:
            plugin("enable" if enabled else "disable", "omarchy-zones")
            if enabled:
                ready()
                q = status()["queries"]
            phase(f'{round_number + 1}-{"enabled" if enabled else "disabled"}-idle')
            if enabled:
                assert status()["queries"] == q
    plugin("enable", "omarchy-zones"); ready()
    ipc("openEditor"); wait_for(lambda: get(EDITOR))
    phase("editor-visible")
    ipc("closeEditor"); wait_for(lambda: editor_state() is None)
    phase("after-editor-close", 5)
    with Input() as device:
        phase("20-native-gestures", action=lambda: [snap(device, i % 2, 1) for i in range(20)])
    phase("after-gestures", 30)
    with (OUT / "resources.csv").open("w") as stream:
        fields = ["phase", "seconds", "cpu_percent_one_core", "pss_kib", "private_kib", "rss_kib", "cgroup_bytes", "cgroup_peak_bytes"]
        writer = csv.DictWriter(stream, fields); writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, row["end"].get(key)) for key in fields})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "correctness", "resources", "lifecycle"))
    args = parser.parse_args()
    globals()[args.action]()
