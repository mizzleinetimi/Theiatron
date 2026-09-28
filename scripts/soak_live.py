#!/usr/bin/env python3
"""Bounded paced-file soak with process RSS, freshness and artifact verification.

Runs only a retained clip, never a camera. Results are same-host observations,
not a hard-realtime, accuracy, sensor-latency or target-hardware certification.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from theiatron.artifacts import fingerprint
from theiatron.io import atomic_json


def summarize(report, trace, samples):
    unsigned = {k: v for k, v in report.items() if k != 'artifact_id'}
    if fingerprint(unsigned) != report.get('artifact_id'):
        raise ValueError('session report checksum mismatch')
    if hashlib.sha256(trace).hexdigest() != report['files']['observations.jsonl']:
        raise ValueError('trace checksum mismatch')
    rows = [json.loads(line) for line in trace.splitlines()]
    ages = sorted(r['age_ms'] for r in rows)
    n = len(rows)
    b, m = report['buffer'], report['metrics']
    if not n or n != m['processed']:
        raise ValueError('processed count does not match the full trace')
    if b['offered'] != b['taken'] + b['overwritten'] + b['pending'] or b['taken'] != n + m['stale_rejected']:
        raise ValueError('input accounting mismatch')
    if any(a['sequence'] >= b['sequence'] for a, b in zip(rows, rows[1:])):
        raise ValueError('observation sequence did not advance')
    loops = [b for a, b in zip(rows, rows[1:]) if a['source_epoch'] != b['source_epoch']]
    if any(a['namespace'] == b['namespace'] for a, b in zip(rows, rows[1:]) if a['source_epoch'] != b['source_epoch']):
        raise ValueError('tracker identity crossed a loop boundary')
    rss = [r['worker_rss_kib'] for r in samples if r.get('worker_rss_kib') is not None]
    # Quartile medians reduce the influence of a single startup allocation.
    q = max(1, len(rss) // 4)
    return {'observations': n, 'trace_p50_ms': ages[math.ceil(n * .5) - 1],
            'trace_p95_ms': ages[math.ceil(n * .95) - 1], 'trace_max_ms': ages[-1],
            'observations_over_300_ms': sum(v > 300 for v in ages),
            'source_loops_observed': len(loops), 'namespaces': len({r['namespace'] for r in rows}),
            'rss_samples': len(rss), 'rss_max_mib': max(rss) / 1024 if rss else None,
            'rss_first_quartile_median_mib': statistics.median(rss[:q]) / 1024 if rss else None,
            'rss_last_quartile_median_mib': statistics.median(rss[-q:]) / 1024 if rss else None,
            'rss_scope': 'ps resident-set snapshots; allocations and OS reclamation are not a proof of absence of leaks'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=3600)
    p.add_argument('--fps', type=int, default=10)
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--context', default='Local laptop; other workloads not controlled')
    args = p.parse_args()
    if not 5 <= args.seconds <= 3600 or not 1 <= args.fps <= 30:
        p.error('seconds must be 5–3600 and FPS 1–30')
    args.out.mkdir(parents=True, exist_ok=False)
    base = f'http://127.0.0.1:{args.port}'
    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return json.load(response)
    token = get('/api/health')['token']
    def post(path, body):
        with urllib.request.urlopen(urllib.request.Request(base + path, data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'X-Theiatron-Token': token}, method='POST'), timeout=5) as response:
            return json.load(response)
    before = get('/api/live')
    if before['busy']:
        raise ValueError('another continuous session is active')
    ident = None
    samples = []
    result = {'state': 'starting', 'source_run': args.source, 'requested_seconds': args.seconds,
              'offered_fps': args.fps, 'context': args.context,
              'worker_state_before': before['worker']['state'], 'started_at': time.time(),
              'scope': 'Paced-file service soak; not an actual camera, detector accuracy or Pi test.'}
    atomic_json(args.out / 'soak.json', result)
    try:
        state = post('/api/live/start', {'source_run': args.source, 'duration': args.seconds, 'fps': args.fps, 'loop': True})
        ident = state['session']['id']
        result.update(state='running', session_id=ident)
        print(f'Soak started: {ident}, {args.seconds}s, {args.fps} FPS', flush=True)
        deadline = time.monotonic() + args.seconds + 90
        next_log = 0
        with (args.out / 'samples.jsonl').open('x') as log:
            while True:
                state = get('/api/live')
                s = state['session']
                if not s or s['id'] != ident:
                    raise ValueError('session ownership changed')
                if time.monotonic() > deadline:
                    raise ValueError('soak did not finish within its deadline')
                pid = state['worker'].get('pid')
                try:
                    output = subprocess.check_output(['ps', '-o', 'rss=', '-p', str(pid)], text=True, timeout=3).strip()
                    rss = int(output)
                except (ValueError, OSError, subprocess.SubprocessError):
                    rss = None
                sample = {'at': time.time(), 'worker_pid': pid, 'worker_rss_kib': rss,
                          'state': s['state'], 'elapsed_s': s.get('elapsed_s'),
                          'last_observation_age_s': s.get('last_observation_age_s'),
                          'processed': s.get('metrics', {}).get('processed', 0),
                          'deadline_misses': s.get('metrics', {}).get('observation_deadline_misses', 0)}
                samples.append(sample)
                log.write(json.dumps(sample) + '\n'); log.flush()
                result['latest'] = sample
                atomic_json(args.out / 'soak.json', result)
                if time.monotonic() >= next_log:
                    print(json.dumps(sample), flush=True)
                    next_log = time.monotonic() + 60
                if not state['busy']:
                    break
                time.sleep(5)
        report = get(f'/out/{ident}/stream-report.json')
        with urllib.request.urlopen(base + f'/out/{ident}/observations.jsonl', timeout=15) as response:
            trace = response.read()
        result.update(summary=summarize(report, trace, samples), report=report)
        if report['state'] != 'complete' or report['finished_reason'] != 'duration-limit':
            raise ValueError('session stopped before its requested duration')
        if len({s['worker_pid'] for s in samples}) != 1:
            raise ValueError('worker identity changed')
        result.update(state='complete', finished_at=time.time())
        result['artifact_id'] = fingerprint(result)
        atomic_json(args.out / 'soak.json', result)
        print(json.dumps(result['summary']), flush=True)
    except BaseException as exc:
        result.update(state='failed', error=str(exc), finished_at=time.time())
        atomic_json(args.out / 'soak.json', result)
        raise
    finally:
        if ident:
            try:
                state = get('/api/live')
                if state['busy'] and state['session']['id'] == ident:
                    post('/api/live/stop', {'id': ident})
            except Exception:
                pass  # Original failure remains recorded; service has its own duration limit.


if __name__ == '__main__':
    main()
