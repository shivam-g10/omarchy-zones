#!/usr/bin/env python3
"""Endpoint resource samples for explicitly selected PoC processes."""
import argparse
import json
import os
from pathlib import Path
import time

def census(pids):
    """Capture current roots and their descendants without polling or spawning helpers.

    This is a point-in-time process census, not proof that no short-lived helper
    ran between samples. Threads belong to their process and are counted there.
    """
    roots={int(pid) for pid in pids}
    table={}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal(): continue
        try:
            fields=(directory/'stat').read_text().rsplit(')',1)[1].split()
            table[int(directory.name)]={'ppid':int(fields[1]),'start_ticks':int(fields[19])}
        except (OSError,ValueError,IndexError):
            continue
    selected=roots & table.keys()
    while True:
        descendants={pid for pid,row in table.items() if row['ppid'] in selected}
        expanded=selected | descendants
        if expanded==selected: break
        selected=expanded
    rows=[]
    vanished=[]
    for pid in sorted(selected):
        directory=Path('/proc')/str(pid)
        try:
            command=(directory/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()
            executable=os.readlink(directory/'exe')
            threads=len(list((directory/'task').iterdir()))
            # A PID can disappear and be reused while the census is assembled.
            current=(directory/'stat').read_text().rsplit(')',1)[1].split()
            if int(current[19])!=table[pid]['start_ticks']:
                vanished.append(pid);continue
            rows.append({'pid':pid,**table[pid],'command':command,'executable':executable,
                         'threads':threads,'role':'root' if pid in roots else 'descendant'})
        except (OSError,ValueError,IndexError):
            vanished.append(pid)
    return {'roots':sorted(roots),'processes':rows,'missing_roots':sorted(roots-table.keys()),
            'vanished_or_unreadable':vanished,
            'limits':'Point-in-time descendants only. Reparented or short-lived helpers may be absent; capture before and after each sample.'}

def snapshot(pid):
    root=Path('/proc')/str(pid)
    fields=(root/'stat').read_text().rsplit(')',1)[1].split()
    memory={}
    for line in (root/'smaps_rollup').read_text().splitlines():
        key,_,tail=line.partition(':')
        if key in ['Rss','Pss','Private_Clean','Private_Dirty']: memory[key]=int(tail.split()[0])
    return {'pid':pid,'command':(root/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace'),
        'cpu_ticks':int(fields[11])+int(fields[12]), 'start_ticks':int(fields[19]),
        'rss_kib':memory['Rss'],'pss_kib':memory['Pss'],
        'private_kib':memory['Private_Clean']+memory['Private_Dirty'],
        'threads':len(list((root/'task').iterdir()))}

def sample(pids,duration,label,work=None):
    census_before=census(pids)
    before={str(pid):snapshot(pid) for pid in pids}
    start=time.monotonic()
    if work is None: time.sleep(duration)
    else: work(duration)
    elapsed=time.monotonic()-start
    after={str(pid):snapshot(pid) for pid in pids}
    census_after=census(pids)
    hz=os.sysconf('SC_CLK_TCK')
    rows=[]
    for pid,first in before.items():
        last=after[pid]
        if first['start_ticks']!=last['start_ticks']:raise RuntimeError('PID was reused')
        rows.append({'pid':int(pid),'cpu_percent_one_core':100*(last['cpu_ticks']-first['cpu_ticks'])/hz/elapsed,
            'rss_kib':last['rss_kib'],'pss_kib':last['pss_kib'],'private_kib':last['private_kib'],'threads':last['threads']})
    return {'label':label,'duration_seconds':elapsed,'clock_ticks_per_second':hz,'processes':rows,
        'total':{key:sum(r[key] for r in rows) for key in ['cpu_percent_one_core','rss_kib','pss_kib','private_kib']},
        'before':before,'after':after,'census_before':census_before,'census_after':census_after,
        'limits':'Endpoint RSS/PSS; no peak/GPU memory. Native nested Hyprland, not a production-session benchmark. Includes only the explicit process list; helper census must accompany the sample.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,action='append',required=True);p.add_argument('--duration',type=float,default=20)
    p.add_argument('--label',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=sample(a.pid,a.duration,a.label);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r['total']))
