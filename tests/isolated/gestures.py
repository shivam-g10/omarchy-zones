#!/usr/bin/env python3
"""Timestamped, acknowledged input for the private native performance fixture.

The compiled input helper is test instrumentation, not part of the product. Its
``OK`` acknowledges a Wayland round trip; it does not establish presentation.
All deadlines use CLOCK_MONOTONIC. Input is never redirected to the parent seat.
"""
from __future__ import annotations

import bisect
import copy
import json
import math
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import time
from typing import Callable, Iterable, Sequence

from lab import LAB, ROOT, ctl, environment

META, SHIFT, ESC = 125, 42, 1
LEFT = 272
HELPER = ROOT / "tests/isolated/generated/wayland-input"
NATIVE_CLIENT = ROOT / "build/tests/native-window"


def private_environment() -> dict[str, str]:
    """Fail closed before starting an input helper or changing a test window."""
    env = environment()
    runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    if runtime.parent != Path("/tmp") or not runtime.name.startswith("ozr-") or runtime.is_symlink():
        raise RuntimeError("Input requires a private /tmp/ozr-* runtime")
    metadata = runtime.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError("The private runtime must be owned by this user and mode 0700")
    display = Path(env.get("WAYLAND_DISPLAY", ""))
    display = display if display.is_absolute() else runtime / display
    if display.parent != runtime or display.is_symlink() or not display.is_socket():
        raise RuntimeError("The Wayland display is not a private fixture socket")
    signature = env.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not signature or "/" in signature or signature in (".", ".."):
        raise RuntimeError("Missing or invalid private Hyprland instance")
    ipc = runtime / "hypr" / signature / ".socket.sock"
    if ipc.is_symlink() or not ipc.is_socket():
        raise RuntimeError("The private Hyprland IPC socket is unavailable")
    state_file = LAB / "lab-state.json"
    if not state_file.is_file():
        raise RuntimeError("Missing private fixture ownership record")
    state = json.loads(state_file.read_text())
    pid = int(state.get("compositor_pid", 0))
    if pid <= 1 or str(LAB / "hyprland.lua").encode() not in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0"):
        raise RuntimeError("The compositor PID is not owned by this fixture")
    if state.get("runtime") != str(runtime):
        raise RuntimeError("The runtime does not match the private fixture")
    return env


def clients() -> list[dict]:
    return json.loads(ctl("-j", "clients"))


# Aliases preserve the small interface used by earlier native checks.
info = clients


def get(title_or_address: str) -> dict:
    matches = [client for client in clients()
               if client.get("title") == title_or_address or client.get("address") == title_or_address]
    if len(matches) != 1:
        raise LookupError(f"Expected one native client for {title_or_address!r}, found {len(matches)}")
    return matches[0]


def geometry(client: dict) -> dict:
    return copy.deepcopy({key: client[key] for key in ("at", "size", "floating", "workspace", "monitor")})


def snapshot(titles: Iterable[str] | None = None) -> dict[str, dict]:
    """Capture sentinels by stable address; include identity, not active focus."""
    names = set(titles) if titles is not None else None
    return {client["address"]: {"title": client.get("title"), **geometry(client)}
            for client in clients() if names is None or client.get("title") in names or client.get("address") in names}


def wait_for(operation: Callable, timeout: float = 4, interval: float = 0.005):
    """Bounded active-test observation; never use this as an idle service."""
    if not 0 < timeout <= 60 or not 0 < interval <= 1:
        raise ValueError("Invalid native-state observation bounds")
    deadline = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            value = operation()
            if value:
                return value
        except (LookupError, subprocess.CalledProcessError) as error:
            last_error = error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Native state did not arrive within {timeout}s: {last_error or 'false condition'}")
        time.sleep(min(interval, remaining))


def wait_clients(titles: Iterable[str], timeout: float = 5) -> list[dict]:
    wanted = tuple(titles)
    if not wanted or len(set(wanted)) != len(wanted):
        raise ValueError("Expected distinct native client titles")

    def ready():
        available = clients()
        found = []
        for title in wanted:
            matching = [client for client in available if client.get("title") == title and client.get("mapped", True)]
            if not matching:
                return None
            if len(matching) != 1 or matching[0].get("xwayland"):
                raise RuntimeError("The fixture requires one real native Wayland window per title")
            found.append(matching[0])
        return found

    return wait_for(ready, timeout=timeout)


def place(title_or_address: str, x: int = 250, y: int = 230, w: int = 600, h: int = 400,
          focus: bool = True) -> dict:
    private_environment()
    coordinates = (x, y, w, h)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in coordinates) or w < 100 or h < 100:
        raise ValueError("Native test placement requires integer coordinates and at least 100x100 size")
    client = get(title_or_address)
    address = client["address"]
    if not re.fullmatch(r"0x[0-9a-fA-F]+", address) or client.get("xwayland"):
        raise RuntimeError("Placement target is not an identified native Wayland window")
    selector = 'window="address:' + address + '"'
    commands = [f'hl.dispatch(hl.dsp.window.float({{action="enable",{selector}}}))',
                f'hl.dispatch(hl.dsp.window.resize({{x={w},y={h},{selector}}}))',
                f'hl.dispatch(hl.dsp.window.move({{x={x},y={y},{selector}}}))']
    if focus:
        commands.append(f'hl.dispatch(hl.dsp.focus({{{selector}}}))')
    ctl("eval", ";".join(commands))

    def settled():
        current = get(address)
        return current if current["at"] == [x, y] and current["size"] == [w, h] and current["floating"] else None

    return wait_for(settled)


def _percentile(values: Sequence[int], quantile: float) -> int | None:
    if not values:
        return None
    return sorted(values)[max(0, min(len(values) - 1, math.ceil(quantile * len(values)) - 1))]


class Input:
    """One synchronous in-flight command; deadline pacing replaces fixed pauses."""

    def __init__(self, width: int | None = None, height: int | None = None, timeout: float = 3):
        env = private_environment()
        monitors = json.loads(ctl("-j", "monitors"))
        if len(monitors) != 1 or monitors[0].get("x", 0) != 0 or monitors[0].get("y", 0) != 0:
            raise RuntimeError("Benchmark input requires one private monitor at origin")
        monitor = monitors[0]
        if monitor.get("scale") != 1 or monitor.get("transform", 0) != 0:
            raise RuntimeError("This input benchmark currently supports scale 1 without rotation")
        self.width = int(width or monitor["width"])
        self.height = int(height or monitor["height"])
        if self.width != monitor["width"] or self.height != monitor["height"]:
            raise RuntimeError("Input coordinate extent must match the actual private monitor")
        if not HELPER.is_file() or not os.access(HELPER, os.X_OK):
            raise RuntimeError("Build the existing isolated input test helper before native checks")
        self.timeout = timeout
        self.events: list[dict] = []
        self._buffer = b""
        self._keys: set[int] = set()
        self._buttons: set[int] = set()
        self.closed = False
        self.start_ns = time.monotonic_ns()
        self.p = subprocess.Popen([str(HELPER)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, bufsize=0)
        self.pid = self.p.pid
        try:
            if self._readline() != b"READY":
                raise RuntimeError("The isolated input helper did not acknowledge startup")
            self.ready_ns = time.monotonic_ns()
        except BaseException:
            self.p.kill()
            self.p.wait(timeout=2)
            raise

    def _readline(self) -> bytes:
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.p.stdout], [], [], max(0, remaining))[0]:
                raise TimeoutError("The private Wayland input helper did not acknowledge its command")
            chunk = os.read(self.p.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError(f"The private Wayland input helper exited (status {self.p.poll()})")
            self._buffer += chunk
            if len(self._buffer) > 16384:
                raise RuntimeError("Unexpected oversized input-helper response")
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.strip()

    def send(self, command: str, *, deadline_ns: int | None = None, metadata: dict | None = None) -> dict:
        if self.closed or self.p.poll() is not None:
            raise RuntimeError("The private input helper is not running")
        if not re.fullmatch(r"(?:move [0-9]+ [0-9]+ [0-9]+ [0-9]+|(?:key|button) [0-9]+ [01])", command):
            raise ValueError("Invalid input-helper command")
        if deadline_ns is not None:
            while (remaining := deadline_ns - time.monotonic_ns()) > 0:
                time.sleep(remaining / 1_000_000_000)
        sent = time.monotonic_ns()
        self.p.stdin.write((command + "\n").encode("ascii"))
        self.p.stdin.flush()
        flushed = time.monotonic_ns()
        acknowledgement = self._readline()
        acknowledged = time.monotonic_ns()
        row = {"command": command, "deadline_ns": deadline_ns if deadline_ns is not None else sent,
               "send_ns": sent, "flush_ns": flushed, "ack_ns": acknowledged,
               "roundtrip_ns": acknowledged - sent,
               "slip_ns": max(0, sent - deadline_ns) if deadline_ns is not None else 0,
               "acknowledged": acknowledgement == b"OK", **(metadata or {})}
        self.events.append(row)
        if acknowledgement != b"OK":
            raise RuntimeError(f"The private input helper rejected {command!r}: {acknowledgement!r}")
        return row

    def move(self, x: float, y: float, *, deadline_ns: int | None = None, metadata: dict | None = None) -> dict:
        if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x < self.width or not 0 <= y < self.height:
            raise ValueError("The requested pointer position is outside the private monitor")
        x, y = min(self.width - 1, round(x)), min(self.height - 1, round(y))
        return self.send(f"move {x} {y} {self.width} {self.height}", deadline_ns=deadline_ns,
                         metadata={"x": x, "y": y, **(metadata or {})})

    def button(self, down: bool, code: int = LEFT, *, deadline_ns: int | None = None) -> dict:
        if isinstance(code, bool) or not isinstance(code, int) or not 272 <= code <= 279:
            raise ValueError("Unsupported pointer button code")
        row = self.send(f"button {code} {int(bool(down))}", deadline_ns=deadline_ns)
        (self._buttons.add if down else self._buttons.discard)(code)
        return row

    def key(self, code: int, down: bool, *, deadline_ns: int | None = None) -> dict:
        if isinstance(code, bool) or not isinstance(code, int) or not 1 <= code <= 255:
            raise ValueError("Unsupported Linux input key code")
        row = self.send(f"key {code} {int(bool(down))}", deadline_ns=deadline_ns)
        (self._keys.add if down else self._keys.discard)(code)
        return row

    def scheduled_path(self, points: Sequence[Sequence[float]], duration_s: float, hz: float = 100) -> dict:
        """Move at constant polyline speed, against absolute monotonic deadlines.

        When a round trip overruns one or more samples, those samples are counted
        and skipped rather than sent as an artificial catch-up burst. The final
        coordinate is always delivered and acknowledged. No observed timestamp
        is replaced with its intended deadline.
        """
        if not math.isfinite(duration_s) or not 0 < duration_s <= 60 or not math.isfinite(hz) or not 1 <= hz <= 240:
            raise ValueError("Path duration must be (0,60] seconds and cadence [1,240] Hz")
        points = [(float(point[0]), float(point[1])) for point in points]
        if not 2 <= len(points) <= 4096:
            raise ValueError("A path requires between 2 and 4096 points")
        if any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x < self.width or not 0 <= y < self.height
               for x, y in points):
            raise ValueError(f"Path coordinates must remain on the private monitor: extent={self.width}x{self.height}, points={points}")
        lengths = [0.0]
        for first, second in zip(points, points[1:]):
            lengths.append(lengths[-1] + math.hypot(second[0] - first[0], second[1] - first[1]))
        duration_ns = round(duration_s * 1_000_000_000)
        period_ns = 1_000_000_000 / hz
        steps = max(1, math.ceil(duration_s * hz))
        start = time.monotonic_ns()
        rows, skipped, step = [], 0, 0
        while step <= steps:
            deadline = start + min(duration_ns, round(step * period_ns))
            distance = lengths[-1] * min(1, (deadline - start) / duration_ns)
            segment = min(len(points) - 2, max(0, bisect.bisect_right(lengths, distance) - 1))
            span = lengths[segment + 1] - lengths[segment]
            fraction = (distance - lengths[segment]) / span if span else 1
            first, second = points[segment], points[segment + 1]
            x = first[0] + fraction * (second[0] - first[0])
            y = first[1] + fraction * (second[1] - first[1])
            rows.append(self.move(x, y, deadline_ns=deadline, metadata={"sample": step, "path_start_ns": start}))
            step += 1
            next_due = min(steps, math.floor((time.monotonic_ns() - start) / period_ns))
            if next_due > step:
                skipped += next_due - step
                step = next_due
        intervals = [second["send_ns"] - first["send_ns"] for first, second in zip(rows, rows[1:])]
        return {"events": rows, "requested_hz": hz, "requested_duration_ns": duration_ns,
                "start_ns": start, "end_ns": rows[-1]["ack_ns"], "elapsed_ns": rows[-1]["ack_ns"] - start,
                "scheduled_samples": steps + 1, "sent_samples": len(rows), "skipped_samples": skipped,
                "pacing": {"interval_p50_ns": _percentile(intervals, .5), "interval_p95_ns": _percentile(intervals, .95),
                           "interval_max_ns": max(intervals, default=0),
                           "slip_p95_ns": _percentile([row["slip_ns"] for row in rows], .95),
                           "slip_max_ns": max(row["slip_ns"] for row in rows),
                           "roundtrip_p95_ns": _percentile([row["roundtrip_ns"] for row in rows], .95)}}

    def close(self):
        if self.closed:
            return
        failure = None
        try:
            if self.p.poll() is None:
                for button in sorted(self._buttons):
                    self.button(False, button)
                for key in sorted(self._keys, reverse=True):
                    self.key(key, False)
        except (OSError, RuntimeError, TimeoutError) as error:
            failure = error
        finally:
            self.closed = True
            if self.p.stdin:
                self.p.stdin.close()
            try:
                self.p.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(timeout=2)
            for stream in (self.p.stdout, self.p.stderr):
                if stream:
                    stream.close()
        if failure:
            raise RuntimeError("Failed to acknowledge release of private input") from failure

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        try:
            self.close()
        except RuntimeError:
            if exc_type is None:
                raise
