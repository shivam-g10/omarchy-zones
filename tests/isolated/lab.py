#!/usr/bin/env python3
"""Own an isolated native desktop and the real Omarchy shell in one cgroup.

Only ``start`` creates a nested window, on a silent parent workspace. All client
commands use the recorded private display. The supervisor blocks on its control
socket while idle; measurements should include its cgroup, not this CLI observer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "build/native-lab"
SOURCE = ROOT
SCRIPT = Path(__file__).resolve()
STATE = LAB / "lab-state.json"
PLUGIN_ID = "omarchy-zones"


def run(args, env=None, timeout=20):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{shlex.join(args)}: {result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def environment():
    """Return only the private environment, never a mixture with the caller's."""
    result = json.loads((LAB / "environment.json").read_text())
    if result.get("HOME") != str(LAB / "home"):
        raise RuntimeError("Refusing an environment outside this lab")
    if not result.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("The private compositor has not initialized")
    return result


def ctl(*args):
    return run(["hyprctl", *args], environment())


def config_hashes(home):
    hashes = {}
    for directory in ("hypr", "omarchy", "omarchy-zones"):
        for file in (home / ".config" / directory).rglob("*"):
            if file.is_file():
                hashes[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
    return hashes


def unit_info(state):
    unit = state["unit"]
    if not re.fullmatch(r"omarchy-zones-shell-lab-[0-9a-f]{12}\.service", unit):
        raise RuntimeError("Refusing an unexpected systemd unit name")
    output = run(["systemctl", "--user", "show", unit, "--no-pager",
                  "--property=LoadState,ActiveState,SubState,MainPID,ControlGroup,Description,ExecStart"])
    properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if properties.get("LoadState") != "not-found":
        if properties.get("Description") != state["description"] or str(SCRIPT) not in properties.get("ExecStart", ""):
            raise RuntimeError("Refusing a systemd unit not owned by this lab")
        pid = int(properties.get("MainPID", "0"))
        if pid and state.get("supervisor_pid") and pid != state["supervisor_pid"]:
            raise RuntimeError("Lab supervisor PID changed unexpectedly")
    return properties


def cgroup_pids(control_group):
    if not control_group:
        return []
    path = (Path("/sys/fs/cgroup") / control_group.lstrip("/")).resolve()
    if not path.is_relative_to(Path("/sys/fs/cgroup")):
        raise RuntimeError("Invalid cgroup path")
    pids = set()
    for file in path.rglob("cgroup.procs"):
        try:
            pids.update(int(value) for value in file.read_text().split())
        except FileNotFoundError:
            pass
    return sorted(pids)


def status():
    if not STATE.exists():
        return {"running": False, "fixture": str(LAB)}
    state = json.loads(STATE.read_text())
    properties = unit_info(state)
    return {**state, "systemd": properties,
            "running": properties.get("ActiveState") in ("active", "activating"),
            "pids": cgroup_pids(properties.get("ControlGroup", state.get("control_group", "")))}


def wait_for(operation, timeout=20):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = operation()
            if value:
                return value
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for lab startup: {last_error or 'no response'}")


def prepare(mode):
    if not re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}@[1-9][0-9]{0,2}(?:\.[0-9]+)?", mode):
        raise RuntimeError("Mode must look like 2560x1440@100")
    if not (SOURCE / "manifest.json").is_file():
        raise RuntimeError(f"The plugin manifest must exist at {SOURCE}")
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    if manifest.get("id") != PLUGIN_ID:
        raise RuntimeError("The plugin must retain the omarchy-zones ID")
    LAB.mkdir(parents=True, exist_ok=True)
    LAB.chmod(0o700)
    parent_home = Path.home()
    before = {"home": str(parent_home), "hashes": config_hashes(parent_home),
              "active_workspace": json.loads(run(["hyprctl", "-j", "activeworkspace"])),
              "active_window": json.loads(run(["hyprctl", "-j", "activewindow"])),
              "cursor": json.loads(run(["hyprctl", "-j", "cursorpos"]))}
    write_json(LAB / "desktop-before.json", before)
    home, omarchy = LAB / "home", LAB / "omarchy"
    for directory in (home, omarchy):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(mode=0o700)
    for relative in (".config/omarchy/plugins", ".local/state/omarchy/current/theme", ".local/share", ".cache"):
        (home / relative).mkdir(parents=True, exist_ok=True)
    shell = omarchy / "shell"
    shutil.copytree("/usr/share/omarchy/shell", shell,
                    ignore=shutil.ignore_patterns("manifest.json", "*.manifest.json"))
    shutil.copy2("/usr/share/omarchy/shell/plugins/bar/manifest.json", shell / "plugins/bar/manifest.json")
    config = {"version": 1, "idle": {"screensaver": 0, "lock": 0},
              "bar": {"id": "omarchy.bar", "position": "bottom", "transparent": False,
                      "layout": {"left": [], "center": [], "right": []}},
              "plugins": []}
    for directory in (home / ".config/omarchy", omarchy / "config/omarchy"):
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "shell.json", config)
    theme = parent_home / ".local/state/omarchy/current/theme"
    for name in ("colors.toml", "shell.toml", "hyprland.lua"):
        if (theme / name).is_file():
            shutil.copy2(theme / name, home / ".local/state/omarchy/current/theme" / name)
    override = parent_home / ".config/omarchy/shell.toml"
    if override.is_file():
        shutil.copy2(override, home / ".config/omarchy/shell.toml")
    fonts = parent_home / ".config/fontconfig"
    if fonts.is_dir():
        shutil.copytree(fonts, home / ".config/fontconfig")
    # Copy configuration only; never source the user's autostart or keybindings.
    for source, name in ((Path("/usr/share/omarchy/default/hypr/looknfeel.lua"), "looknfeel-default.lua"),
                         (parent_home / ".config/hypr/looknfeel.lua", "looknfeel-user.lua")):
        shutil.copy2(source, LAB / name)
    config_source = "\n".join("dofile(" + json.dumps(str(path)) + ")" for path in (
        LAB / "looknfeel-default.lua", home / ".local/state/omarchy/current/theme/hyprland.lua", LAB / "looknfeel-user.lua"))
    config_source += "\n" + '''hl.config({
  ecosystem = {no_donation_nag = true, no_update_news = true},
  cursor = {no_hardware_cursors = true},
  input = {follow_mouse = 1},
  xwayland = {enabled = false},
})
'''
    config_source += "hl.monitor({output = \"\", mode = " + json.dumps(mode) + ", position = \"0x0\", scale = 1})\n"
    config_source += '''hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), {mouse = true})
'''
    (LAB / "hyprland.lua").write_text(config_source)
    runtime = Path(tempfile.mkdtemp(prefix="ozr-shell-"))
    parent_display = os.environ["WAYLAND_DISPLAY"]
    if not parent_display.startswith("/"):
        parent_display = str(Path(os.environ["XDG_RUNTIME_DIR"]) / parent_display)
    keep = ("PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "XCURSOR_THEME", "XCURSOR_SIZE", "HYPRCURSOR_THEME", "HYPRCURSOR_SIZE", "OMARCHY_MENU_FONT")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(HOME=str(home), XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_STATE_HOME=str(home / ".local/state"), XDG_DATA_HOME=str(home / ".local/share"),
               XDG_CACHE_HOME=str(home / ".cache"), XDG_DATA_DIRS="/usr/local/share:/usr/share",
               OMARCHY_PATH=str(omarchy), WAYLAND_DISPLAY=parent_display, QT_QPA_PLATFORM="wayland",
               HYPRLAND_NO_SD_VARS="1", HYPRLAND_NO_SD_NOTIFY="1", AQ_BACKENDS="wayland",
               XDG_CURRENT_DESKTOP="Hyprland", XDG_SESSION_TYPE="wayland")
    font_match = re.search(r'hl\.env\("OMARCHY_MENU_FONT",\s*"([^"\n]+)"\)', (LAB / "looknfeel-user.lua").read_text())
    if font_match:
        env["OMARCHY_MENU_FONT"] = font_match.group(1)
    write_json(LAB / "launch-environment.json", env)
    for old in (LAB / "environment.json",):
        old.unlink(missing_ok=True)
    token = uuid.uuid4().hex[:12]
    state = {"unit": f"omarchy-zones-shell-lab-{token}.service", "description": f"Omarchy Zones private shell lab {token}",
             "runtime": str(runtime), "mode": mode, "fixture": str(LAB), "started_at": time.time()}
    write_json(STATE, state)
    return state


def start(mode="2560x1440@100"):
    if STATE.exists() and (status()["running"] or status()["pids"]):
        raise RuntimeError("Lab already running; stop it before creating another fixture")
    state = prepare(mode)
    # The wrapper forwards the compositor's exec-rule token into the transient
    # service, preserving silent-workspace/no-focus rules across systemd launch.
    command = shlex.join([sys.executable, str(SCRIPT), "_launch"])
    code = "hl.exec_cmd(" + json.dumps(command) + ', {workspace="name:zones-shell-lab silent", float=true, no_focus=true, render_unfocused=true})'
    run(["hyprctl", "eval", code])
    try:
        wait_for(lambda: (LAB / "environment.json").exists(), timeout=30)
        wait_for(lambda: run(["omarchy-shell", "shell", "ping"], environment()) == "ok", timeout=30)
        errors = ctl("configerrors")
        if errors not in ("", "ok"):
            raise RuntimeError("Private compositor configuration errors: " + errors)
        return status()
    except Exception:
        stop()
        raise


def launch():
    state = json.loads(STATE.read_text())
    command = ["systemd-run", "--user", "--no-ask-password", "--quiet", "--service-type=exec",
               "--unit=" + state["unit"], "--description=" + state["description"],
               "--property=KillMode=control-group", "--property=TimeoutStopSec=6s",
               "--property=SendSIGKILL=yes", "--property=StandardOutput=append:" + str(LAB / "supervisor.log"),
               "--property=StandardError=append:" + str(LAB / "supervisor.log"),
               "--working-directory=" + str(ROOT)]
    if os.environ.get("HL_EXEC_RULE_TOKEN"):
        command.append("--setenv=HL_EXEC_RULE_TOKEN")
    command += [sys.executable, str(SCRIPT), "_serve"]
    run(command)


def serve():
    state = json.loads(STATE.read_text())
    env = json.loads((LAB / "launch-environment.json").read_text())
    if os.environ.get("HL_EXEC_RULE_TOKEN"):
        env["HL_EXEC_RULE_TOKEN"] = os.environ["HL_EXEC_RULE_TOKEN"]
    state["supervisor_pid"] = os.getpid()
    state["control_group"] = next(line.split("::", 1)[1] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
    write_json(STATE, state)
    runtime = Path(env["XDG_RUNTIME_DIR"])
    # No service directories: neither desktop portals nor other user services
    # can autoactivate on this bus. Even system-bus clients see the private bus.
    bus_config = LAB / "dbus.conf"
    bus_config.write_text('<busconfig><type>session</type><listen>unix:path=' + str(runtime / "bus") +
                          '</listen><auth>EXTERNAL</auth><policy context="default">'
                          '<allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/>'
                          '</policy></busconfig>')
    children = []
    shell_process = None

    def terminate(_signum, _frame):
        raise SystemExit(0)

    def launch_shell():
        nonlocal shell_process
        if shell_process and shell_process.poll() is None:
            os.killpg(shell_process.pid, signal.SIGTERM)
            try:
                shell_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(shell_process.pid, signal.SIGKILL)
                shell_process.wait(timeout=2)
        with (LAB / "shell.log").open("a") as log:
            shell_process = subprocess.Popen(["quickshell", "-n", "-p", str(LAB / "omarchy/shell")],
                                             env=private_env, stdout=log, stderr=log, start_new_session=True)
        children.append(shell_process)
        state["shell_pid"] = shell_process.pid
        write_json(STATE, state)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        with (LAB / "dbus.log").open("w") as log:
            bus = subprocess.Popen(["dbus-daemon", "--config-file=" + str(bus_config), "--nofork", "--print-address=1"],
                                   env=env, stdout=subprocess.PIPE, stderr=log, text=True)
        children.append(bus)
        address = bus.stdout.readline().strip()
        if not address.startswith("unix:"):
            raise RuntimeError("Private D-Bus failed to start")
        bus.stdout.close()
        env["DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SYSTEM_BUS_ADDRESS"] = address
        with (LAB / "hyprland.log").open("w") as log:
            compositor = subprocess.Popen(["Hyprland", "--config", str(LAB / "hyprland.lua")], env=env, stdout=log, stderr=log)
        children.append(compositor)
        state.update(compositor_pid=compositor.pid, bus_pid=bus.pid)
        write_json(STATE, state)

        def ready():
            if compositor.poll() is not None:
                raise RuntimeError("Private Hyprland exited; inspect hyprland.log")
            instances = list((runtime / "hypr").glob("*/.socket.sock"))
            displays = [path for path in runtime.glob("wayland-*") if path.is_socket()]
            return (instances[0], displays[0]) if instances and displays else None

        instance, display = wait_for(ready)
        private_env = {**env, "WAYLAND_DISPLAY": display.name, "HYPRLAND_INSTANCE_SIGNATURE": instance.parent.name}
        private_env.pop("HL_EXEC_RULE_TOKEN", None)
        write_json(LAB / "environment.json", private_env)
        wait_for(lambda: json.loads(ctl("-j", "monitors")))
        launch_shell()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(runtime / "control.sock"))
            server.listen(1)
            while True:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(2)
                    request = connection.recv(128).decode().strip()
                    if request == "restart-shell":
                        launch_shell()
                        connection.sendall(b"ok\n")
                    else:
                        connection.sendall(b"unknown\n")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
        # The service manager also kills every reparented helper in the cgroup.


def restart_shell():
    current = status()
    if not current["running"]:
        raise RuntimeError("Lab is not running")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(str(Path(current["runtime"]) / "control.sock"))
        client.sendall(b"restart-shell\n")
        if client.recv(128).strip() != b"ok":
            raise RuntimeError("Private shell restart failed")
    wait_for(lambda: run(["omarchy-shell", "shell", "ping"], environment()) == "ok")
    return status()


def stop():
    state = json.loads(STATE.read_text())
    properties = unit_info(state)
    control_group = properties.get("ControlGroup") or state.get("control_group", "")
    if properties.get("LoadState") != "not-found":
        run(["systemctl", "--user", "stop", state["unit"]], timeout=15)
    remaining = cgroup_pids(control_group)
    if remaining:
        raise RuntimeError(f"Lab cgroup still contains processes: {remaining}")
    before = json.loads((LAB / "desktop-before.json").read_text())
    after = config_hashes(Path(before["home"]))
    changed = sorted(path for path in before["hashes"].keys() | after.keys() if before["hashes"].get(path) != after.get(path))
    result = {"configuration_files_checked": len(before["hashes"]), "changed": changed,
              "remaining_pids": remaining, "unit": state["unit"], "control_group": control_group}
    write_json(LAB / "cleanup.json", result)
    state["stopped_at"] = time.time()
    write_json(STATE, state)
    if changed:
        raise RuntimeError("Parent desktop configuration changed during validation: " + ", ".join(changed))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "restart-shell", "ctl", "_launch", "_serve"))
    parser.add_argument("--mode", default="2560x1440@100")
    args, remaining = parser.parse_known_args()
    if remaining and args.action != "ctl":
        parser.error("unrecognized arguments: " + " ".join(remaining))
    if args.action == "_launch":
        launch()
    elif args.action == "_serve":
        serve()
    elif args.action == "ctl":
        print(ctl(*remaining))
    else:
        result = {"start": lambda: start(args.mode), "stop": stop, "status": status, "restart-shell": restart_shell}[args.action]()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
