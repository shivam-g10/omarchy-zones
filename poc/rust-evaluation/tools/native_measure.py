#!/usr/bin/env python3
"""Measure the native Rust experiment in the existing isolated compositor only."""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from native_check import Input, get, info, place, require, status, wait_for
from lab import ROOT, LAB, environment, ctl
from measure import sample

PLUGIN = ROOT / "native/target/release/zones-rust-poc.so"
CLIENT = ROOT.parents[1] / "build/tests/native-window"
TITLE = "Rust native measurement"


def plugin_loaded():
    plugins = json.loads(ctl("-j", "plugin", "list"))
    require(all(plugin["name"] == "zones-rust-poc" for plugin in plugins),
            "Unexpected plugin in isolated compositor; refusing a mixed measurement")
    return any(plugin["name"] == "zones-rust-poc" for plugin in plugins)


def load():
    if not plugin_loaded():
        require("ok" in ctl("plugin", "load", str(PLUGIN)), "Experiment plugin load failed")


def unload():
    if plugin_loaded():
        require("ok" in ctl("plugin", "unload", str(PLUGIN)), "Experiment plugin unload failed")


def census(roots):
    """Take an endpoint descendant census without retaining unrelated commands."""
    parents = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            parents[int(path.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    selected = set(roots)
    while True:
        expanded = selected | {pid for pid, parent in parents.items() if parent in selected}
        if expanded == selected:
            break
        selected = expanded
    rows = []
    for pid in sorted(selected):
        try:
            command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            rows.append({"pid": pid, "ppid": parents.get(pid), "command": command})
        except OSError:
            continue
    return rows


def terminate(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def close_input(device):
    if device is None:
        return
    if device.p.poll() is None:
        for operation in (lambda: device.button(False), lambda: device.key(42, False),
                          lambda: device.key(125, False)):
            with contextlib.suppress(Exception):
                operation()
    try:
        device.close()
    except (OSError, subprocess.TimeoutExpired):
        terminate(device.p)


def launch_client(log):
    process = subprocess.Popen([str(CLIENT), TITLE], env=environment(), stdout=log, stderr=log)
    try:
        wait_for(lambda: get(TITLE))
        place(TITLE)
    except BaseException:
        terminate(process)
        raise
    return process


def begin_drag(device, shift):
    place(TITLE)
    device.move(430, 450)
    device.key(125, True)
    if shift:
        device.key(42, True)
    device.button(True)
    device.move(600, 450)
    require(status()["overlay"] == ("visible" if shift else "hidden"), status())


def end_drag(device, shift):
    device.move(1000, 450)
    device.button(False)
    if shift:
        device.key(42, False)
    device.key(125, False)
    wait_for(lambda: status()["overlay"] == "hidden" and status()["retained-target"] == "no"
             and status()["pending-snap"] == "0")
    require(status()["callback-failure"] == "no", status())


def idle_sample(pid, duration, label):
    require(info() == [], "Idle measurement still has a mapped lab client")
    compositor_before = census([pid])
    controller_before = census([os.getpid()])
    require(len(controller_before) == 1, "Test helpers remain alive before idle measurement")
    result = sample([row["pid"] for row in compositor_before], duration, label)
    result["compositor_census_before"] = compositor_before
    result["compositor_census_after"] = census([pid])
    result["controller_census_before"] = controller_before
    result["controller_census_after"] = census([os.getpid()])
    result["product_helper_count_before"] = len(compositor_before) - 1
    result["product_helper_count_after"] = len(result["compositor_census_after"]) - 1
    require({row["pid"] for row in compositor_before} ==
            {row["pid"] for row in result["compositor_census_after"]},
            "Compositor helper census changed during idle sample")
    require(len(result["controller_census_after"]) == 1, "Unexpected persistent test helper")
    return result


def active_sample(pid, client, device, duration, shift):
    before = status()
    begin_drag(device, shift)
    compositor_tree = census([pid])
    controller_tree = census([os.getpid()])
    roles = {row["pid"]: "compositor-helper" for row in compositor_tree}
    roles.update({pid: "compositor", os.getpid(): "measurement-controller",
                  client.pid: "native-window", device.p.pid: "input-helper"})
    for row in controller_tree:
        roles.setdefault(row["pid"], "test-helper")
    movement = {"count": 0}

    def move_for(seconds):
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            index = movement["count"]
            # Both cases use the same path and Input.move's 40 ms pacing. This is
            # active test stimulus, not a background loop in the plugin.
            phase = index * math.tau / 100
            device.move(640 + 260 * math.sin(phase), 450 + 100 * math.sin(phase * 2))
            movement["count"] += 1

    result = sample(sorted(roles), duration, "zones-drag" if shift else "ordinary-drag", work=move_for)
    result["movements"] = movement["count"]
    result["movements_per_second"] = movement["count"] / result["duration_seconds"]
    result["roles"] = {str(process): role for process, role in roles.items()}
    result["metrics_by_role"] = {
        role: {key: sum(row[key] for row in result["processes"] if roles[row["pid"]] == role)
               for key in ("cpu_percent_one_core", "rss_kib", "pss_kib", "private_kib")}
        for role in set(roles.values())
    }
    result["census_before"] = {"compositor": compositor_tree, "controller": controller_tree}
    result["census_after"] = {"compositor": census([pid]), "controller": census([os.getpid()])}
    result["during"] = status()
    end_drag(device, shift)
    after = status()
    require(int(after["snaps"]) == int(before["snaps"]) + int(shift), after)
    if shift:
        require(get(TITLE)["at"] + get(TITLE)["size"] == [640, 0, 640, 900], get(TITLE))
    else:
        require(get(TITLE)["size"] == [600, 400], get(TITLE))
    result["after"] = after
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/native-resources.json")
    parser.add_argument("--idle-seconds", type=float, default=20)
    parser.add_argument("--active-seconds", type=float, default=10)
    args = parser.parse_args()
    require(args.idle_seconds > 0 and args.active_seconds > 0, "Sample durations must be positive")
    pid = int((LAB / "pid").read_text())
    command = Path(f"/proc/{pid}/cmdline").read_bytes()
    require(str(LAB / "hyprland.lua").encode() in command, "PID is not the isolated compositor")
    require(info() == [], "Close existing lab clients before running native measurement")
    monitors = json.loads(ctl("-j", "monitors"))
    require(len(monitors) == 1 and monitors[0]["width"] == 1280 and monitors[0]["height"] == 900,
            "Measurement requires the existing 1280x900 isolated lab")
    initially_loaded = plugin_loaded()
    client = None
    device = None
    result = {
        "passed": False, "compositor_pid": pid, "started_at_unix": time.time(),
        "idle": {}, "active": {},
        "limits": [
            "This measures an isolated nested Hyprland instance, not the production desktop.",
            "Idle samples use the same warmed compositor; order is loaded then unloaded. Allocator retention and unrelated compositor work can affect the difference.",
            "Active samples include native window rendering and nested compositor work. Their difference is not an attribution of all cost to Rust or the plugin.",
            "Active client, input helper, and measurement controller CPU are reported separately from compositor CPU.",
            "Endpoint descendant censuses include persistent helpers; very short-lived between-endpoint processes are not continuously traced.",
            "CPU has kernel accounting granularity; memory is endpoint RSS/PSS, not peak or GPU memory.",
            "The controller generates input around 25 movements per second only during the ten-second active tests. No stimulus helper remains during idle measurements.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (args.output.parent / "native-measure-window.log").open("w") as log:
        try:
            load()
            client = launch_client(log)
            device = Input()
            before = int(status()["snaps"])
            begin_drag(device, True)
            end_drag(device, True)
            require(int(status()["snaps"]) == before + 1, "Warmup did not snap")
            require(get(TITLE)["at"] + get(TITLE)["size"] == [640, 0, 640, 900], get(TITLE))
            result["warmup"] = status()
            close_input(device)
            device = None
            terminate(client)
            client = None
            wait_for(lambda: info() == [])
            time.sleep(.25)
            result["idle"]["loaded"] = idle_sample(pid, args.idle_seconds, "warm-plugin-loaded")
            unload()
            time.sleep(.25)
            result["idle"]["unloaded"] = idle_sample(pid, args.idle_seconds, "warm-plugin-unloaded")
            loaded = result["idle"]["loaded"]["total"]
            unloaded = result["idle"]["unloaded"]["total"]
            result["idle"]["loaded_minus_unloaded"] = {key: loaded[key] - unloaded[key] for key in loaded}

            load()
            client = launch_client(log)
            device = Input()
            result["active"]["ordinary"] = active_sample(pid, client, device, args.active_seconds, False)
            result["active"]["zones"] = active_sample(pid, client, device, args.active_seconds, True)
            result["passed"] = True
        except BaseException as error:
            result["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            cleanup_errors = []
            for operation in (lambda: close_input(device), lambda: terminate(client),
                              lambda: wait_for(lambda: info() == []),
                              load if initially_loaded else unload):
                try:
                    operation()
                except Exception as error:
                    cleanup_errors.append(f"{type(error).__name__}: {error}")
            if cleanup_errors:
                result["passed"] = False
            result["finished_at_unix"] = time.time()
            result["cleanup"] = {"errors": cleanup_errors, "compositor_census": census([pid]),
                                 "controller_census": census([os.getpid()])}
            for name, operation in (("lab_clients", info), ("plugin_loaded", plugin_loaded)):
                try:
                    result["cleanup"][name] = operation()
                except Exception as error:
                    result["cleanup"][name] = {"error": str(error)}
                    result["passed"] = False
            args.output.write_text(json.dumps(result, indent=2) + "\n")
    require(result["passed"], result.get("cleanup"))
    print(json.dumps({"passed": result["passed"], "idle_delta": result["idle"]["loaded_minus_unloaded"],
                      "active": {name: data["metrics_by_role"] for name, data in result["active"].items()},
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
