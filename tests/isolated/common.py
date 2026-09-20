#!/usr/bin/env python3
"""Exercise actual Wayland drag input in the isolated lab, never the user seat."""
import json
from pathlib import Path
import select
import subprocess
import time
from lab import ROOT, LAB, environment, ctl

ARTIFACTS = ROOT / 'evidence/cpp-hardening'
ARTIFACTS.mkdir(parents=True,exist_ok=True)

def info(): return json.loads(ctl('-j', 'clients'))
def status(): return dict(line.split(': ', 1) for line in ctl('zones').splitlines() if ': ' in line)
def geometry(client): return {key: client[key] for key in ['at', 'size', 'floating', 'workspace', 'monitor']}
def get(title): return next(c for c in info() if c['title'] == title)
def require(condition, details):
    if not condition: raise RuntimeError(str(details))
def wait_for(operation, timeout=4):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            value = operation()
            if value: return value
        except (StopIteration, subprocess.CalledProcessError): pass
        time.sleep(.04)
    raise RuntimeError('Timed out waiting for native state')

class Input:
    def __init__(self):
        self.p = subprocess.Popen([str(Path(__file__).parent/'generated/wayland-input')], env=environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        require(self.read()=='READY', 'No isolated virtual input')
    def read(self):
        require(select.select([self.p.stdout], [], [], 3)[0], 'Input timeout')
        return self.p.stdout.readline().strip()
    def send(self, line):
        self.p.stdin.write(line+'\n'); self.p.stdin.flush()
        require(self.read()=='OK', 'Input command failed: '+line)
        time.sleep(.04)
    def move(self,x,y): self.send(f'move {round(x)} {round(y)} 1280 900')
    def button(self, down): self.send(f'button 272 {int(down)}')
    def key(self, code, down): self.send(f'key {code} {int(down)}')
    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close(); self.p.wait(timeout=3)
    def __enter__(self): return self
    def __exit__(self,*_): self.close()

def place(title, x=250,y=230,w=600,h=400):
    selector = f'window="address:{get(title)["address"]}"'
    ctl('eval', f'hl.dispatch(hl.dsp.window.float({{action="enable",{selector}}}));'
        f'hl.dispatch(hl.dsp.window.resize({{x={w},y={h},{selector}}}));'
        f'hl.dispatch(hl.dsp.window.move({{x={x},y={y},{selector}}}));'
        f'hl.dispatch(hl.dsp.focus({{{selector}}}))')
    wait_for(lambda: get(title)['at']==[x,y] and get(title)['size']==[w,h])
