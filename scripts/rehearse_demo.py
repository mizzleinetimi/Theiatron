#!/usr/bin/env python3
"""Exercise the local demo API without selecting only favourable outcomes.

Creates ten immutable experiments by default. No source observations are edited.
"""
import argparse
import io
import json
import time
import urllib.request
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True)
    p.add_argument('--port',type=int,default=8766)
    p.add_argument('--count',type=int,default=10)
    args=p.parse_args();base=f'http://127.0.0.1:{args.port}'
    def read(path):
        with urllib.request.urlopen(base+path,timeout=30) as response:return json.load(response)
    token=read('/api/health')['token']
    def post(path,payload):
        request=urllib.request.Request(base+path,json.dumps(payload).encode(),
            {'Content-Type':'application/json','X-Theiatron-Token':token},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    profile=post(f'/api/runs/{args.source}/demo-profile',{'acknowledge_estimates':True})
    for index in range(args.count):
        observed=index==0
        scenario={'site_revision':profile['revision'],'acknowledge_assumptions':True,
                  'generated_demand':not observed,'demand':'observed' if observed else ('balanced','tidal','heavy')[(index-1)%3],
                  'duration':max(int(profile['source']['duration']+1),int(max(e['t'] for e in profile['source']['events']))+1) if observed else 180,
                  'scale':1,'pace':0,'seed':42+(index-1)//3 if not observed else 42}
        started=time.monotonic();j=post('/api/compare',scenario)
        while j['state'] in {'queued','uploading','processing','cancelling'}:
            if time.monotonic()-started>180:raise RuntimeError('Rehearsal timeout: '+j['id'])
            time.sleep(.5);j=read('/api/runs/'+j['id'])
        if j['state']!='complete':raise RuntimeError(j['message'])
        r=j['results']
        if not r['valid']:raise RuntimeError('Simulator diagnostics failed: '+j['id'])
        with urllib.request.urlopen(base+'/api/runs/'+j['id']+'/evidence.zip',timeout=30) as response:
            archive=zipfile.ZipFile(io.BytesIO(response.read()))
        if json.loads(archive.read('report.json'))['artifact_id']!=r['artifact_id']:
            raise RuntimeError('Export differs from displayed report')
        print(json.dumps({'run':j['id'],'demand':scenario['demand'],'seed':scenario['seed'],
                          'vehicles':r['metrics']['fixed']['offered'],'valid':r['valid'],
                          'modelled_reduction_pct':r.get('simulation_reduction_pct'),
                          'wall_seconds':round(time.monotonic()-started,2),'export_files':len(archive.namelist())}),flush=True)


if __name__=='__main__':main()
