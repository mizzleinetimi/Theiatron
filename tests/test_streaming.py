import json
import threading
import time

import numpy as np
import pytest

from theiatron.streaming import Frame,LatestFrame,Latency,needs_tracker_reset
from theiatron.live_worker import run_session,ResidentDetector


def frame(n=1,epoch=0,source_time=.1,age=0,frame_index=None):
    now=time.monotonic()
    return Frame(np.zeros((720,1280,3),dtype=np.uint8),n,epoch,source_time,now-age,now-age,frame_index)


def test_latest_slot_overwrites_old_frames_and_conserves_every_offer():
    slot=LatestFrame()
    for n in range(100):slot.offer(frame(n))
    assert slot.take().sequence==99
    assert slot.snapshot()=={'offered':100,'overwritten':99,'taken':1,'pending':0}
    slot.close()
    assert not slot.offer(frame(101)) and slot.take(.01) is None


def test_histogram_bounds_include_outliers_and_no_nan():
    h=Latency()
    assert h.snapshot()['p95_ms_upper'] is None
    for latency in [.0012]*19+[15.25]:h.add(latency)
    assert h.snapshot()['p50_ms_upper']==2
    assert h.snapshot()['p95_ms_upper']==2
    assert h.percentile(1)==15250
    assert h.snapshot()['samples']==20
    with pytest.raises(ValueError):h.add(float('inf'))
    with pytest.raises(ValueError):h.add(float('nan'))


def test_tracker_reset_on_epoch_gap_or_reversed_time_not_normal_frame_drop():
    a=frame(source_time=1)
    assert not needs_tracker_reset(None,a)
    assert not needs_tracker_reset(a,frame(source_time=1.2))
    assert needs_tracker_reset(a,frame(source_time=1.6))
    assert needs_tracker_reset(a,frame(epoch=1,source_time=.1))
    assert needs_tracker_reset(a,frame(source_time=.9))


class Detector:
    def __init__(self,slow=0):self.resets=0;self.calls=0;self.slow=slow
    def reset(self):self.resets+=1
    def track(self,image):
        from theiatron.detection import Detection
        self.calls+=1
        time.sleep(self.slow)
        return [Detection(1,100,100,(90,70,110,100),2,.9)]


def request(tmp_path,name='session'):
    source=tmp_path/'source.mov';source.write_bytes(b'test fixture, fake capture')
    return {'id':name,'source':str(source),'out':str(tmp_path/name),'fps':10,'duration':2,'source_name':'source.mov'}


def capture_factory(frames,interval=.01,error=None):
    class Capture:
        age_basis='Test timestamps';skipped=0
        def __init__(self,*args):pass
        def capture(self,slot,stop):
            for options in frames:
                if stop.wait(interval):break
                slot.offer(frame(**options))
            slot.close(error)
    return Capture


def test_slow_inference_drops_work_instead_of_growing_backlog(tmp_path):
    req=request(tmp_path)
    det=Detector(slow=.06)
    result=run_session(req,det,threading.Event(),{},0,
        capture_factory([{'n':n,'source_time':n*.1} for n in range(30)]))
    assert result['state']=='complete' and result['buffer']['overwritten']>0
    assert 0<result['metrics']['processed']<30
    b=result['buffer']
    assert b['offered']==b['overwritten']+b['taken']+b['pending']
    assert b['taken']==result['metrics']['processed']+result['metrics']['stale_rejected']
    assert result['files']['observations.jsonl']
    assert 'video.mp4' not in result['files']


def test_stale_frames_and_failed_source_do_not_claim_healthy_perception(tmp_path):
    req=request(tmp_path)
    result=run_session(req,Detector(),threading.Event(),{},0,
        capture_factory([{'n':1,'age':1}]))
    assert result['state']=='failed' and result['metrics']['stale_rejected']==1
    assert result['metrics']['processed']==0
    req=request(tmp_path,'broken')
    result=run_session(req,Detector(),threading.Event(),{},0,capture_factory([],error='decoder failed'))
    assert result['state']=='failed' and result['error']=='decoder failed'


def test_stop_before_start_never_becomes_complete_and_loop_ids_are_namespaced(tmp_path):
    req=request(tmp_path);stop=threading.Event();stop.set()
    result=run_session(req,Detector(),stop,{},0,capture_factory([{}]))
    assert result['state']=='stopped' and result['metrics']['processed']==0
    req=request(tmp_path,'loop');det=Detector()
    result=run_session(req,det,threading.Event(),{},0,
        capture_factory([{'epoch':0},{'epoch':1}],interval=.08))
    rows=[json.loads(l) for l in (tmp_path/'loop'/'observations.jsonl').read_text().splitlines()]
    assert len(rows)==2 and rows[0]['namespace']!=rows[1]['namespace']
    assert result['metrics']['tracker_resets']==1 and det.resets==2


def test_resident_reset_preserves_predictor_and_model_callbacks():
    from types import SimpleNamespace
    class Tracker:
        def __init__(self):self.resets=0
        def reset(self):self.resets+=1
    t=Tracker();predictor=SimpleNamespace(trackers=[t],vid_path=['old'])
    resident=object.__new__(ResidentDetector)
    resident.detector=SimpleNamespace(model=SimpleNamespace(predictor=predictor,callbacks={'test':[1]}))
    resident.reset();resident.reset()
    assert resident.detector.model.predictor is predictor
    assert resident.detector.model.callbacks=={'test':[1]} and t.resets==2
    assert predictor.vid_path==[None]


def test_native_frame_index_is_preserved_in_stream_trace(tmp_path):
    req=request(tmp_path)
    result=run_session(req,Detector(),threading.Event(),{},0,
        capture_factory([{'frame_index':5},{'n':2,'source_time':.2,'frame_index':11}],interval=.08))
    rows=[json.loads(l) for l in (tmp_path/'session'/'observations.jsonl').read_text().splitlines()]
    assert [r['frame_index'] for r in rows]==[5,11]
    assert result['last_observation']['frame_index']==11


def test_file_capture_native_indices_reset_with_real_loop(tmp_path):
    import cv2
    from theiatron.live_worker import FileCapture
    path=tmp_path/'small.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30,(64,48))
    for n in range(6): writer.write(np.full((48,64,3),n*25,dtype=np.uint8))
    writer.release()
    stop=threading.Event()
    frames=[]
    class Sink:
        error=None
        def offer(self,value):
            frames.append(value)
            if len(frames)==4: stop.set()
        def close(self,error=None):self.error=error
    sink=Sink()
    FileCapture(str(path),10,True).capture(sink,stop)
    assert sink.error is None
    assert [f.frame_index for f in frames]==[2,5,2,5]
    assert [f.epoch for f in frames]==[0,0,1,1]
