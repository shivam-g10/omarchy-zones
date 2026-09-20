#!/usr/bin/env python3
"""Native mouse/numeric editor checks using the isolated compositor socket."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from lab import ROOT,LAB,environment,ctl
from native_check import Input,ARTIFACTS,info,get,place,geometry,require,wait_for
from measure import sample

TITLES={'qtbridge':'Omarchy Zones · Qt Bridges PoC','cxxqt':'Omarchy Zones · CXX-Qt PoC'}
BINS={'qtbridge':'zones-qtbridge-poc','cxxqt':'zones-cxxqt-evaluation'}

def fixture():
    directory=LAB/'state/omarchy/current/theme';directory.mkdir(parents=True,exist_ok=True)
    source=Path.home()/'.local/state/omarchy/current/theme'
    for name in ['colors.toml','shell.toml']:
        if (source/name).exists(): shutil.copy2(source/name,directory/name)
    return directory

def automation(path):
    rows=[]
    for line in path.read_text(errors='replace').splitlines():
        if 'AUTOMATION ' in line:
            try: rows.append(json.loads(line.split('AUTOMATION ',1)[1]))
            except json.JSONDecodeError: pass
    return rows

def refresh(device,log):
    count=len(automation(log));device.key(88,True);device.key(88,False)
    return wait_for(lambda: automation(log)[-1] if len(automation(log))>count else None)

def click(device,point,offset):
    device.move(point['x']+offset[0],point['y']+offset[1]);device.button(True);device.button(False)

def numeric(device,point,offset,value):
    click(device,point,offset)
    device.key(29,True);device.key(30,True);device.key(30,False);device.key(29,False)
    for digit in str(value):
        code=11 if digit=='0' else int(digit)+1
        device.key(code,True);device.key(code,False)
    device.key(28,True);device.key(28,False)

def run(kind,measure=False):
    theme=fixture();original=(theme/'colors.toml').read_text()
    title=TITLES[kind];binary=ROOT/kind/'target/release'/BINS[kind]
    log=ARTIFACTS/(kind+'-native.log');output=ARTIFACTS/(kind+'-native-layout.conf')
    output.unlink(missing_ok=True)
    other_log=(ARTIFACTS/(kind+'-other.log')).open('w')
    other=subprocess.Popen([str(ROOT.parents[1]/'build/tests/native-window'),'Editor sentinel'],env=environment(),stdout=other_log,stderr=other_log)
    wait_for(lambda:get('Editor sentinel'));place('Editor sentinel',1000,650,250,180)
    before=geometry(get('Editor sentinel'))
    with log.open('w') as stream:
        app=subprocess.Popen([str(binary),'--output',str(output)],env=environment(),stdout=stream,stderr=stream)
    result={'kind':kind,'checks':[],'pid':app.pid}
    try:
        wait_for(lambda:get(title),timeout=10);place(title,40,130,900,620)
        require(not get(title)['xwayland'],'Editor is not native Wayland')
        with Input() as device:
            # Compositor geometry is acknowledged before Qt finishes its resize.
            # Wait for the rendered control layout, then use its reported positions.
            def ready_layout():
                state=refresh(device,log)
                return state if (state['width'],state['height'])==(900,620) else None
            state=wait_for(ready_layout);offset=get(title)['at']
            require(state['boundaryValue']==1280,state)
            numeric(device,state['input'],offset,1536)
            state=refresh(device,log);require(state['boundaryValue']==1536,state)
            require(geometry(get('Editor sentinel'))==before,'Numeric edit moved sentinel')
            result['checks'].append({'name':'numeric shared boundary','value':1536,'passed':True})
            point=state['boundary'];device.move(point['x']+offset[0],point['y']+offset[1]);device.button(True)
            for delta in range(5,56,5):device.move(point['x']+offset[0]+delta,point['y']+offset[1])
            device.button(False);state=refresh(device,log)
            require(1536<state['boundaryValue']<=2240,state)
            require(geometry(get('Editor sentinel'))==before,'Mouse edit moved sentinel')
            result['checks'].append({'name':'mouse shared boundary','value':state['boundaryValue'],'passed':True})
            click(device,state['save'],offset)
            wait_for(output.exists)
            lines=output.read_text().splitlines();a=lines[-2].split();b=lines[-1].split()
            require(int(a[3])==int(b[1]) and int(a[3])+int(b[3])==2560,lines)
            require(geometry(get('Editor sentinel'))==before,'Save moved sentinel')
            result['checks'].append({'name':'save definitions and preserve existing window','passed':True})
            result['theme_before']=state['theme']
            require(state['theme']['borderWidth']==3 and state['theme']['rounding']==12,state)
            subprocess.run(['grim',str(ARTIFACTS/(kind+'-native.png'))],env=environment(),check=True,timeout=5)
            # Modify only a private theme fixture; user theme never changes.
            (theme/'colors.toml').write_text(original.replace('#67D4E8','#C792EA'))
            until=time.monotonic()+4
            while time.monotonic()<until:
                time.sleep(.15);state=refresh(device,log)
                if state['theme']['accent'].lower()=='#c792ea':break
            require(state['theme']['accent'].lower()=='#c792ea',state)
            result['theme_after']=state['theme']
            result['checks'].append({'name':'event-driven theme update in live QML','passed':True})
            subprocess.run(['grim',str(ARTIFACTS/(kind+'-theme-event.png'))],env=environment(),check=True,timeout=5)
            (theme/'colors.toml').write_text(original)
        if measure:
            pids=[app.pid,other.pid,int((LAB/'pid').read_text())]
            # The input helper has exited; no test-input process runs during idle sampling.
            time.sleep(.4)
            idle=sample(pids,20,kind+' editor open idle')
            (ARTIFACTS/(kind+'-idle.json')).write_text(json.dumps(idle,indent=2)+'\n')
            with Input() as device:
                state=refresh(device,log);point=state['boundary'];offset=get(title)['at']
                device.move(point['x']+offset[0],point['y']+offset[1]);device.button(True)
                def work(duration):
                    start=time.monotonic();steps=0
                    while time.monotonic()-start<duration:
                        device.move(point['x']+offset[0]+(40 if steps%2 else -40),point['y']+offset[1]);steps+=1
                    result['active_input_moves']=steps
                active=sample(pids+[device.p.pid],10,kind+' boundary dragging',work)
                device.button(False)
                (ARTIFACTS/(kind+'-active.json')).write_text(json.dumps(active,indent=2)+'\n')
            result['resources']={'idle':idle['processes'],'active':active['processes']}
        result['passed']=True
    finally:
        (theme/'colors.toml').write_text(original)
        (ARTIFACTS/(kind+'-native-check.json')).write_text(json.dumps(result,indent=2)+'\n')
        for process in [app,other]:
            if process.poll() is None:process.terminate();process.wait(timeout=4)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('kind',choices=TITLES);parser.add_argument('--measure',action='store_true')
    args=parser.parse_args();print(json.dumps(run(args.kind,args.measure),indent=2))
