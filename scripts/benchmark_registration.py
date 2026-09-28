#!/usr/bin/env python3
"""Paired exact-frame registration benchmark; fit agreement is not ground truth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import cv2
import numpy as np

from theiatron.artifacts import fingerprint,load_artifact
from theiatron.camera_registration import BackgroundRegistrar,transform_point
from scripts.registration_candidate import AdaptiveBackgroundRegistrar
from theiatron.io import atomic_json
from theiatron.provenance import file_hash
from theiatron.reconstruction import source,_safe
from theiatron.visual_capture import load_source


def benchmark(run_id,samples):
    current=source(ROOT,run_id)
    directory=_safe(ROOT,run_id,'recorded-tracks.json').parent
    artifact=load_source(directory) if (directory/'reconstruction-source.json').exists() else load_artifact(directory/'simulation.json')['source_meta']
    video=Path(artifact['source'])
    if file_hash(video)!=current['binding']['source_sha256']:raise ValueError('source bytes changed')
    dense=json.loads((directory/'recorded-tracks.json').read_text())
    cap=cv2.VideoCapture(str(video));native=cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or not 1<=native<=240:raise ValueError('unsupported source video')
    skip=max(1,round(native*current['video_offset_s']));dt=skip/native
    boxes={}
    for track in dense['tracks']:
        for sample in track['samples']:boxes.setdefault(round(sample['t']/dt),[]).append(sample['box'])
    ticks=np.unique(np.linspace(2,max(boxes),samples,dtype=int))
    def frame(tick):
        cap.set(cv2.CAP_PROP_POS_FRAMES,int(tick*skip-1))
        ok,image=cap.read()
        if not ok:raise ValueError('sample frame could not be decoded')
        return cv2.resize(image,(1280,720),interpolation=cv2.INTER_AREA)
    try:
        reference=frame(1)
        old=BackgroundRegistrar(reference,boxes.get(1,[]));fast=AdaptiveBackgroundRegistrar(reference,boxes.get(1,[]))
        rows=[]
        probes=[[x,y] for x in (128,384,640,896,1152) for y in (144,360,576)]
        for i,tick in enumerate(ticks):
            image=frame(tick);row={'frame_index':int(tick*skip-1),'t':round(tick*dt,6)}
            results={}
            methods=[('full',old),('adaptive',fast)]
            if i%2:methods.reverse()
            for name,registrar in methods:
                start=time.perf_counter();result=registrar.register(image,boxes.get(tick,[]))
                results[name]=result
                row[name]={'elapsed_s':time.perf_counter()-start,**result}
            if all(r['status']=='accepted' for r in results.values()):
                errors=[float(np.linalg.norm(np.array(transform_point(results['full']['H'],p))-
                           transform_point(results['adaptive']['H'],p))) for p in probes]
                row['projection_disagreement_px']={'median':float(np.median(errors)),'max':max(errors)}
            rows.append(row)
            print(f'{run_id} {i+1}/{len(ticks)} paired frames',flush=True)
    finally:cap.release()
    summary={}
    for name in ('full','adaptive'):
        residuals=[r[name]['residual_px']['median'] for r in rows if r[name]['status']=='accepted']
        summary[name]={'total_s':sum(r[name]['elapsed_s'] for r in rows),'accepted':len(residuals),
                       'median_fit_residual_px':float(np.median(residuals)) if residuals else None}
    summary['speedup']=summary['full']['total_s']/summary['adaptive']['total_s']
    summary['full_fallbacks']=sum(r['adaptive'].get('search_mode')=='full-fallback' for r in rows)
    summary['lost_acceptances']=sum(r['full']['status']=='accepted' and r['adaptive']['status']!='accepted' for r in rows)
    differences=[r['projection_disagreement_px']['max'] for r in rows if 'projection_disagreement_px' in r]
    summary['max_projection_disagreement_px']=max(differences,default=None)
    return {'binding':current['binding'],'samples':len(rows),'summary':summary,'frames':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='append',required=True)
    parser.add_argument('--samples',type=int,default=24)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not 2<=args.samples<=60:parser.error('use 2–60 paired samples')
    if args.out.exists():parser.error('choose a new report path; existing evidence is not overwritten')
    code=file_hash(ROOT/'theiatron/camera_registration.py')
    candidate_code=file_hash(ROOT/'scripts/registration_candidate.py')
    result={'schema_version':1,'scope':'Same decoded frames and masks; alternating execution order. Timings exclude decode/reference setup. Agreement with the full matcher is not measured accuracy.',
            'camera_code_sha256':code,'candidate_code_sha256':candidate_code,'script_sha256':file_hash(Path(__file__)),
            'production_enabled':False,
            'opencv':cv2.__version__,'opencv_threads':cv2.getNumThreads(),
            'runs':[benchmark(run,args.samples) for run in args.run]}
    if file_hash(ROOT/'theiatron/camera_registration.py')!=code:raise ValueError('registration code changed during benchmark')
    if file_hash(ROOT/'scripts/registration_candidate.py')!=candidate_code:raise ValueError('candidate code changed during benchmark')
    result['revision']=fingerprint(result);atomic_json(args.out,result)
    for run in result['runs']:print(run['binding']['source_run'],json.dumps(run['summary']))


if __name__=='__main__':main()
