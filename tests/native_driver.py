#!/usr/bin/env python3
"""Reusable controller for native-input. Running this file only prints help.

The helper sends real evdev input through /dev/uinput. move_to reads Hyprland's
actual cursor position and compensates for the active acceleration settings.
Only explicit test invocations inject input; nothing is installed or resident.
"""
import json
from pathlib import Path
import select
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def hyprctl_json(command):
    return json.loads(subprocess.check_output(['hyprctl', '-j', command], text=True))


class NativeInput:
    def __init__(self, workspace=None):
        self.workspace = workspace
        self.process = subprocess.Popen([str(ROOT / 'build/tests/native-input')], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self._read_until('READY', 5)

    def _read_until(self, prefix, timeout):
        ready, _, _ = select.select([self.process.stderr], [], [], timeout)
        if not ready:
            raise RuntimeError('Native input helper timed out')
        line = self.process.stderr.readline().strip()
        if not line.startswith(prefix):
            raise RuntimeError('Native input helper: ' + (line or 'closed'))
        return line

    def command(self, value, timeout=10):
        if self.workspace and hyprctl_json('activeworkspace')['name'] != self.workspace:
            self.close()
            raise RuntimeError('Workspace changed; native input stopped and held keys released.')
        self.process.stdin.write(value + '\n')
        self.process.stdin.flush()
        self._read_until('OK ', timeout)

    def key(self, name, down):
        self.command(f'key {name} {"down" if down else "up"}')
        time.sleep(.035)

    def button(self, name='BTN_LEFT', down=True):
        self.command(f'button {name} {"down" if down else "up"}')
        time.sleep(.06)

    def move(self, dx, dy, steps=1, interval_ms=16):
        self.command(f'move {int(dx)} {int(dy)} {steps} {interval_ms}')
        time.sleep(.025)

    def move_to(self, x, y, tolerance=2):
        for _ in range(70):
            position = hyprctl_json('cursorpos')
            dx, dy = x - position['x'], y - position['y']
            if abs(dx) <= tolerance and abs(dy) <= tolerance:
                return position
            # Conservative gain allows for libinput acceleration without changing it.
            step = lambda value: (1 if value > 0 else -1) * max(1, round(abs(value) * .28)) if value else 0
            self.move(step(dx), step(dy))
        raise RuntimeError(f'Cursor did not reach {(x, y)}; actual {hyprctl_json("cursorpos")}')

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=3)
        if not self.process.stderr.closed:
            self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


if __name__ == '__main__':
    print(__doc__)
    print('Import NativeInput from this module; see tests/README.md for examples.')
