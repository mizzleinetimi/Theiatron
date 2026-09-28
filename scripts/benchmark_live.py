#!/usr/bin/env python3
"""Three fresh paced-file sessions: first start, warm restart, higher offered FPS.

No camera is accessed. Every sample/drop is retained; this is a local throughput
check, not detector accuracy or Raspberry Pi validation. Start the workbench first.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from theiatron.artifacts import fingerprint
from theiatron.io import atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,help='completed source run ID')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=30)
    p.add_argument('--port',type=int,default=8766)
    args=p.parse_args()
    if not 5<=args.seconds<=300:p.error('use 5–300 seconds per session')
    args.out.mkdir(parents=True,exist_ok=False)
    base=f'http://127.0.0.1:{args.port}'
    def get(path):return json.load(urllib.request.urlopen(base+path,timeout=5))
    token=get('/api/health')['token']
    def post(path,body):
        return json.load(urllib.request.urlopen(urllib.request.Request(base+path,
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Theiatron-Token':token},method='POST'),timeout=5))
    before=get('/api/live')
    if before['busy']:raise ValueError('a continuous session is already active')
    rows=[];current=None
    try:
        for name,fps in [('first-start',10),('warm-restart',10),('higher-offered-cadence',30)]:
            state=post('/api/live/start',{'source_run':args.source,'duration':args.seconds,'fps':fps,'loop':False})
            current=state['session']['id']
            print(f'{name}: {current}',flush=True)
            deadline=time.monotonic()+args.seconds+90
            while state['busy'] and time.monotonic()<deadline:
                time.sleep(.25);state=get('/api/live')
                if state['session']['id']!=current:raise ValueError('session ownership changed')
            if state['busy'] or state['session']['state']!='complete':raise ValueError('session did not finish cleanly: '+str(state))
            report=get(f'/out/{current}/stream-report.json')
            ident=report.pop('artifact_id')
            if fingerprint(report)!=ident:raise ValueError('session checksum mismatch')
            report['artifact_id']=ident
            raw=urllib.request.urlopen(base+f'/out/{current}/observations.jsonl',timeout=5).read()
            import hashlib
            if hashlib.sha256(raw).hexdigest()!=report['files']['observations.jsonl']:raise ValueError('trace checksum mismatch')
            observations=[json.loads(l) for l in raw.splitlines()]
            ages=sorted(r['age_ms'] for r in observations)
            n=len(ages)
            assert n==report['metrics']['processed'] and n>0
            b=report['buffer']
            assert b['offered']==b['taken']+b['overwritten']+b['pending']
            assert b['taken']==n+report['metrics']['stale_rejected']
            row={'case':name,'id':current,'worker_pid':state['worker']['pid'],
                 'request_to_first_observation_s':state['session']['request_to_first_observation_s'],
                 'exact_trace_p50_ms':ages[math.ceil(n*.5)-1],'exact_trace_p95_ms':ages[math.ceil(n*.95)-1],
                 'report':report}
            rows.append(row);atomic_json(args.out/(name+'.json'),row)
            print(json.dumps({k:row[k] for k in ('case','worker_pid','request_to_first_observation_s','exact_trace_p95_ms')}),flush=True)
        assert len({r['worker_pid'] for r in rows})==1,'model worker was not retained'
        assert len({r['report']['last_observation']['namespace'] for r in rows})==len(rows),'identity namespaces were reused'
        result={'source_run':args.source,'seconds_per_case':args.seconds,
            'worker_state_before':before['worker']['state'],'rows':rows,
            'scope':'Same-host paced-file spot check; not sensor/network capture latency, field accuracy or Pi performance.'}
        result['artifact_id']=fingerprint(result)
        atomic_json(args.out/'benchmark.json',result)
    finally:
        if current:
            state=get('/api/live')
            if state['busy'] and state['session']['id']==current:post('/api/live/stop',{'id':current})


if __name__=='__main__':main()
