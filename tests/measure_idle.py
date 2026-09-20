#!/usr/bin/env python3
"""Measure idle compositor/plugin cost from two /proc snapshots.

Run once with the plugin unloaded, then once loaded. Keep the same desktop and
close the editor in both states. This sampler is test tooling, not a service.
"""
import argparse
import json
import os
from pathlib import Path
import time


def process_names():
    found = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            found[int(path.name)] = (path / 'comm').read_text().strip()
        except (OSError, ValueError):
            pass
    return found


def snapshot(pids):
    result = {}
    for pid in pids:
        try:
            base = Path('/proc') / str(pid)
            stat = (base / 'stat').read_text().rsplit(')', 1)[1].split()
            memory = {}
            for line in (base / 'smaps_rollup').read_text().splitlines():
                key, _, tail = line.partition(':')
                if key in ('Rss', 'Pss', 'Private_Clean', 'Private_Dirty'):
                    memory[key] = int(tail.split()[0])
            result[str(pid)] = {
                'name': (base / 'comm').read_text().strip(),
                'command': (base / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip(),
                'starttime_ticks': int(stat[19]),
                'cpu_ticks': int(stat[11]) + int(stat[12]),
                'rss_kib': memory.get('Rss', 0),
                'pss_kib': memory.get('Pss', 0),
                'private_kib': memory.get('Private_Clean', 0) + memory.get('Private_Dirty', 0),
            }
        except (OSError, ValueError):
            continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--pid', action='append', type=int, default=[])
    parser.add_argument('--name', action='append', default=[], help='Additional exact /proc comm name to include')
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error('duration must be between 1 and 3600 seconds')
    # Linux /proc/comm truncates long executable names to 15 characters.
    names = {'Hyprland', 'omarchy-zones', 'zones-editor', 'omarchy-zones-e', 'omarchy-zones-editor', *args.name}
    selected = lambda: set(args.pid) | {pid for pid, name in process_names().items() if name in names}
    before = snapshot(selected())
    if not before:
        parser.error('No matching process found')
    started = time.monotonic()
    time.sleep(args.duration)
    after = snapshot(selected())
    elapsed = time.monotonic() - started
    ticks_per_second = os.sysconf('SC_CLK_TCK')
    rows = []
    for pid in sorted(before.keys() | after.keys(), key=int):
        first, last = before.get(pid), after.get(pid)
        comparable = first and last and first['starttime_ticks'] == last['starttime_ticks']
        rows.append({
            'pid': int(pid), 'name': (last or first)['name'],
            'present_start': bool(first), 'present_end': bool(last),
            'cpu_percent_one_core': round(100 * (last['cpu_ticks'] - first['cpu_ticks']) / ticks_per_second / elapsed, 4) if comparable else None,
            'rss_kib_start': first['rss_kib'] if first else None,
            'rss_kib_end': last['rss_kib'] if last else None,
            'pss_kib_start': first['pss_kib'] if first else None,
            'pss_kib_end': last['pss_kib'] if last else None,
        })
    result = {
        'label': args.label, 'duration_seconds': round(elapsed, 3),
        'clock_ticks_per_second': ticks_per_second,
        'cpu_percent_one_core': round(sum(row['cpu_percent_one_core'] or 0 for row in rows), 4),
        'rss_kib_end': sum(row['rss_kib_end'] or 0 for row in rows),
        'pss_kib_end': sum(row['pss_kib_end'] or 0 for row in rows),
        'processes': rows,
        'start': before, 'end': after,
        'limitations': 'Endpoint sampling; no peak measurement. CPU includes unrelated compositor work. Process names are explicit; pass --pid/--name for other helpers. Short-run differences include allocator and workload noise.',
    }
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        result['delta_vs_baseline'] = {
            'baseline_label': baseline['label'],
            'cpu_percentage_points': round(result['cpu_percent_one_core'] - baseline['cpu_percent_one_core'], 4),
            'rss_kib_end': result['rss_kib_end'] - baseline['rss_kib_end'],
            'pss_kib_end': result['pss_kib_end'] - baseline['pss_kib_end'],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('start', 'end')}, indent=2))


if __name__ == '__main__':
    main()
