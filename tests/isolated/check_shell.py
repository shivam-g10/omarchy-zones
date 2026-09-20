#!/usr/bin/env python3
"""Validate official Omarchy shell installation on an isolated native desktop.

The installed shell QML is copied unchanged into a private fixture. Only its
built-in bar manifest is exposed to discovery; first-party services and widgets
are excluded before startup. Both D-Bus addresses and all writable user paths
are private. This exercises the real CLI and shell loader, not a mock loader.
The native editor is pre-staged as a separately installed dependency.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from lab import LAB, ROOT, environment, start, stop
from measure import census, sample

ARTIFACTS = ROOT / "evidence/publishing"
FIXTURE = ROOT / "build/shell-publication-check"
PLUGIN_ID = "omarchy-zones"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args, env=None, timeout=20):
    result = subprocess.run(args, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def wait_for(operation, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = operation()
            if value:
                return value
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
        time.sleep(.1)
    raise RuntimeError("Timed out waiting for isolated shell state")


def private_processes(env):
    """Include detached/reparented helpers, identified by the private runtime."""
    marker = ("XDG_RUNTIME_DIR=" + env["XDG_RUNTIME_DIR"]).encode()
    pids = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            if marker in (directory / "environ").read_bytes().split(b"\0"):
                pids.append(int(directory.name))
        except OSError:
            pass
    return census(pids)


def shell_fixture():
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    home = FIXTURE / "home"
    omarchy = FIXTURE / "omarchy"
    shell = omarchy / "shell"
    shutil.copytree("/usr/share/omarchy/shell", shell,
                    ignore=shutil.ignore_patterns("manifest.json", "*.manifest.json"))
    shutil.copyfile("/usr/share/omarchy/shell/plugins/bar/manifest.json", shell / "plugins/bar/manifest.json")
    config = {"version": 1, "idle": {"screensaver": 0, "lock": 0},
              "bar": {"id": "omarchy.bar", "position": "top", "transparent": False,
                      "layout": {"left": [], "center": [], "right": []}}, "plugins": []}
    for parent in [home / ".config/omarchy", omarchy / "config/omarchy"]:
        parent.mkdir(parents=True)
        (parent / "shell.json").write_text(json.dumps(config))
    for name in [".local/share", ".local/state/omarchy/toggles", ".cache", ".config/omarchy/plugins"]:
        (home / name).mkdir(parents=True, exist_ok=True)
    snapshot = FIXTURE / "source"
    snapshot.mkdir()
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        source = ROOT / relative
        require(not source.is_symlink(), f"Publication snapshot contains a symlink: {relative}")
        if source.is_file():
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    run(["git", "init", "-b", "main", str(snapshot)])
    run(["git", "-C", str(snapshot), "add", "."])
    run(["git", "-C", str(snapshot), "-c", "user.name=Isolated validation", "-c",
         "user.email=validation@localhost", "commit", "-m", "Private publication validation snapshot"])
    return home, omarchy, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-publish-native")
    parser.add_argument("--measure-seconds", type=float, default=15)
    args = parser.parse_args()
    binary = args.build_dir.resolve() / "omarchy-zones-editor"
    require(binary.is_file(), f"Build the native editor first: {binary}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    result = {"passed": False, "checks": [], "limits": [
        "The official shell host and CLI run on a nested native Hyprland desktop, with an empty bar and no first-party services.",
        "The native editor dependency is pre-staged; this check does not exercise the separate native installer.",
        "Resource samples are endpoint observations of a private shell, not production-session or peak-memory benchmarks."]}
    bus = shell = None
    started = False
    env = None
    editors = set()
    try:
        home, omarchy, snapshot = shell_fixture()
        start()
        started = True
        env = environment()
        require(env["XDG_RUNTIME_DIR"].startswith("/tmp/ozr-"), "Private compositor required")
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
                   XDG_CACHE_HOME=str(home / ".cache"), OMARCHY_PATH=str(omarchy),
                   XDG_DATA_DIRS="/usr/local/share:/usr/share", QT_QPA_PLATFORM="wayland")
        for key in ["DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS", "DISPLAY", "SESSION_MANAGER"]:
            env.pop(key, None)
        # No service directories: portal/system helpers must never autoactivate
        # merely because this fixture opens a Qt window.
        bus_config = FIXTURE / "dbus.conf"
        bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' + env["XDG_RUNTIME_DIR"] +
                              '</listen><auth>EXTERNAL</auth><policy context="default">'
                              '<allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/>'
                              '</policy></busconfig>')
        bus = subprocess.Popen(["dbus-daemon", "--config-file=" + str(bus_config), "--nofork", "--print-address=1"],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        address = bus.stdout.readline().strip()
        require(address.startswith("unix:"), "Private D-Bus startup failed")
        env["DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SYSTEM_BUS_ADDRESS"] = address
        # The lab's donation helper is unrelated to the plugin. Close only the
        # helper whose process environment proves it belongs to this lab.
        for client in json.loads(run(["hyprctl", "-j", "clients"], env)):
            pid = client["pid"]
            try:
                process_env = Path(f"/proc/{pid}/environ").read_bytes()
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
                signature = ("HYPRLAND_INSTANCE_SIGNATURE=" + env["HYPRLAND_INSTANCE_SIGNATURE"]).encode()
                if b"hyprland-donate-screen" in command and signature in process_env.split(b"\0"):
                    os.kill(pid, signal.SIGTERM)
            except FileNotFoundError:
                pass
        editor_path = Path(env["XDG_DATA_HOME"]) / "omarchy-zones/omarchy-zones-editor"
        editor_path.parent.mkdir(parents=True)
        shutil.copy2(binary, editor_path)
        profiles = Path(env["XDG_CONFIG_HOME"]) / "omarchy-zones/zones.conf"
        profiles.parent.mkdir(parents=True)
        profiles.write_text('omarchy-zones-v2\nprofile "Split"\nWAYLAND-1 0 0 640 900\nWAYLAND-1 640 0 640 900\n')
        profile_hash = hashlib.sha256(profiles.read_bytes()).hexdigest()
        with (ARTIFACTS / "shell.log").open("w") as log:
            shell = subprocess.Popen(["quickshell", "-n", "-p", str(omarchy / "shell")], env=env, stdout=log, stderr=log)
        def ipc(*args):
            return run(["omarchy-shell", "shell", *args], env)
        def plugins():
            return json.loads(run(["omarchy", "plugin", "list", "--json"], env))
        def plugin():
            return next((p for p in plugins() if p["id"] == PLUGIN_ID), None)
        def windows():
            return [c for c in json.loads(run(["hyprctl", "-j", "clients"], env))
                    if c["class"] == "omarchy-zones-editor"]
        wait_for(lambda: ipc("ping") == "ok")
        wait_for(lambda: len(plugins()) == 1 and plugins()[0]["id"] == "omarchy.bar")
        time.sleep(2)
        baseline_pids = [p["pid"] for p in census([shell.pid])["processes"]]
        result["baseline"] = sample(baseline_pids, args.measure_seconds, "Official empty shell before plugin installation")
        result["bus_census"] = census([bus.pid])
        result["private_runtime_baseline_census"] = private_processes(env)
        run(["omarchy", "plugin", "add", str(snapshot), "--yes"], env)
        wait_for(lambda: plugin() and not plugin()["enabled"])
        result["checks"].append("Official Git add validates exact ID and installs disabled")
        run(["omarchy", "plugin", "enable", PLUGIN_ID], env)
        wait_for(lambda: plugin() and plugin()["enabled"])
        require(not windows(), "Enabling launched an editor without a summon")
        require(ipc("summon", PLUGIN_ID, "{}") == "ok", "Summon failed")
        window = wait_for(lambda: windows()[0] if windows() else None)
        editors.add(window["pid"])
        require(not window["xwayland"], "Editor is not a native Wayland window")
        require(Path(f'/proc/{window["pid"]}/exe').resolve() == editor_path.resolve(), "Wrong native editor launched")
        result["checks"].append("Enable stays idle; summon opens the separately staged real native editor")
        for _ in range(3):
            require(ipc("summon", PLUGIN_ID, "{}") == "ok", "Repeated summon failed")
        time.sleep(.5)
        require(len(windows()) == 1 and windows()[0]["pid"] == window["pid"], "Relaunch duplicated the editor")
        result["checks"].append("Repeated shell summon preserves one native editor process/window")
        ipc("hide", PLUGIN_ID)
        require(len(windows()) == 1, "Hiding the launcher closed the native editor")
        run(["omarchy", "plugin", "disable", PLUGIN_ID], env)
        wait_for(lambda: plugin() and not plugin()["enabled"])
        require(len(windows()) == 1, "Disabling the launcher closed the native editor")
        require(ipc("summon", PLUGIN_ID, "{}") == "unknown", "Disabled plugin still summoned")
        run(["omarchy", "plugin", "enable", PLUGIN_ID], env)
        wait_for(lambda: plugin() and plugin()["enabled"])
        require(ipc("summon", PLUGIN_ID, "{}") == "ok", "Re-enabled plugin could not summon")
        time.sleep(.5)
        require(len(windows()) == 1 and windows()[0]["pid"] == window["pid"], "Re-enable lost existing editor")
        result["checks"].append("Hide, disable and re-enable preserve the native editor; disabled summon is rejected")
        run(["grim", str(ARTIFACTS / "shell-native-editor.png")], env)
        os.kill(window["pid"], signal.SIGTERM)
        wait_for(lambda: not windows())
        time.sleep(2)
        after_pids = [p["pid"] for p in census([shell.pid])["processes"]]
        result["enabled_idle_after_editor_closed"] = sample(after_pids, args.measure_seconds,
                                                           "Official shell with enabled launcher after native editor closes")
        result["private_runtime_after_census"] = private_processes(env)
        expected_idle = set(after_pids + [bus.pid, int((LAB / "pid").read_text())])
        unexpected = [row for row in result["private_runtime_after_census"]["processes"] if row["pid"] not in expected_idle]
        require(not unexpected, f"Unaccounted private idle processes: {unexpected}")
        result["incremental"] = {k: result["enabled_idle_after_editor_closed"]["total"][k] - result["baseline"]["total"][k]
                                 for k in ["rss_kib", "pss_kib", "private_kib", "cpu_percent_one_core"]}
        run(["omarchy", "plugin", "remove", PLUGIN_ID, "--yes"], env)
        wait_for(lambda: plugin() is None)
        require(not (home / ".config/omarchy/plugins" / PLUGIN_ID).exists(), "Plugin checkout remains after removal")
        require(editor_path.exists(), "Shell removal deleted the separate native dependency")
        require(hashlib.sha256(profiles.read_bytes()).hexdigest() == profile_hash, "Shell lifecycle changed saved profiles")
        result["checks"].append("Official removal deletes shell checkout and preserves separate native dependency and profiles")
        result["publication_snapshot_commit"] = run(["git", "-C", str(snapshot), "rev-parse", "HEAD"])
        result["editor_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        result["shell_qml_sha256"] = hashlib.sha256((omarchy / "shell/shell.qml").read_bytes()).hexdigest()
        result["passed"] = True
    finally:
        for pid in editors:
            try:
                if env and ("HYPRLAND_INSTANCE_SIGNATURE=" + env["HYPRLAND_INSTANCE_SIGNATURE"]).encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass
        for process in [shell, bus]:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if started:
            stop()
        if env:
            # Detached helpers can be reparented away from the shell. Cleanup
            # still requires proof of this run's private runtime environment.
            for row in private_processes(env)["processes"]:
                try:
                    os.kill(row["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            wait_for(lambda: not private_processes(env)["processes"])
            result["private_runtime_cleanup_census"] = private_processes(env)
        (ARTIFACTS / "shell-lifecycle.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"], "incremental": result.get("incremental")}, indent=2))


if __name__ == "__main__":
    main()
