#!/usr/bin/env python3
"""Exercise actual Wayland drag input in the isolated lab, never the user seat."""
import json
from pathlib import Path
import select
import subprocess
import time
from lab import ROOT, LAB, environment, ctl

ARTIFACTS = ROOT / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)

def info(): return json.loads(ctl('-j', 'clients'))
def status(): return dict(line.split(': ', 1) for line in ctl('zones-rust-poc').splitlines() if ': ' in line)
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
        self.p = subprocess.Popen([str(ROOT/'tools/generated/wayland-input')], env=environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
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

def main():
    monitor = json.loads(ctl('-j','monitors'))
    require(len(monitor)==1 and monitor[0]['width']==1280 and monitor[0]['height']==900, monitor)
    plugin = ROOT/'native/target/release/zones-rust-poc.so'
    require('ok' in ctl('plugin','load',str(plugin)), 'Plugin load failed')
    binary = ROOT.parents[1]/'build/tests/native-window'
    clients=[]
    rows=[]
    try:
        for title in ['Rust native A','Rust native B']:
            log=(ARTIFACTS/(title.replace(' ','-')+'.log')).open('w')
            clients.append(subprocess.Popen([str(binary),title],env=environment(),stdout=log,stderr=log))
            wait_for(lambda: get(title)); place(title)
        place('Rust native B',900,600,300,180)
        other=geometry(get('Rust native B'))
        with Input() as device:
            place('Rust native A')
            initial=status()
            device.key(125,True); device.key(42,True); device.move(700,450)
            require(status()['overlay']=='hidden','Hotkey alone displayed overlay')
            device.key(42,False); device.key(125,False)
            rows.append({'name':'hotkey alone','passed':True})
            for name,shift,titlebar,target,expected,cancel in [
                ('right snap',True,False,(1000,440),[640,0,640,900],False),
                ('left titlebar snap',True,True,(210,440),[0,0,640,900],False),
                ('ordinary drag',False,False,(1000,440),None,False),
                ('release modifier',True,False,(1000,440),None,True),
            ]:
                place('Rust native A'); before=status()
                device.move(430,258 if titlebar else 450)
                if not titlebar: device.key(125,True)
                if shift: device.key(42,True)
                device.button(True); device.move(600,470); device.move(*target)
                during=status()
                require(during['overlay']==('visible' if shift else 'hidden'),during)
                if name=='right snap':
                    subprocess.run(['grim',str(ARTIFACTS/'rust-native-overlay.png')],env=environment(),check=True,timeout=5)
                if cancel: device.key(42,False)
                device.button(False)
                if shift and not cancel: device.key(42,False)
                if not titlebar: device.key(125,False)
                time.sleep(.2)
                after=status(); current=get('Rust native A')
                require(int(after['snaps'])==int(before['snaps'])+(expected is not None),after)
                require(after['overlay']=='hidden' and after['retained-target']=='no' and after['pending-snap']=='0',after)
                require(after['callback-failure']=='no',after)
                if expected: require(current['at']+current['size']==expected,current)
                else: require(current['size']==[600,400],current)
                require(geometry(get('Rust native B'))==other,'Other client changed')
                rows.append({'name':name,'passed':True,'during':during,'after':after,'window':geometry(current)})
        # Retaining no snapped-window links is visible in the status after each drop.
        require('ok' in ctl('plugin','unload',str(plugin)), 'Unload failed')
        require('ok' in ctl('plugin','load',str(plugin)), 'Reload failed')
        require(status()['snaps']=='0' and status()['callback-failure']=='no',status())
        rows.append({'name':'unload and reload','passed':True})
    finally:
        for p in clients:
            if p.poll() is None: p.terminate(); p.wait(timeout=3)
        ctl('plugin','unload',str(plugin))
        (ARTIFACTS/'native-check.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({'passed':len(rows),'checks':[r['name'] for r in rows]},indent=2))

if __name__=='__main__': main()
