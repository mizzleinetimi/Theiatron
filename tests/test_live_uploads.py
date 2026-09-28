import json
import socket
import time

import pytest

import launcher_server as server
from test_launcher_http import http, isolated, request


@pytest.fixture
def detector(monkeypatch):
    class Live:
        active=False
        calls=[]
        source_run=None
        def __init__(self,*args):pass
        def busy(self):return self.active
        def snapshot(self):return {'busy':self.active,'session':{'id':'fresh','source_run':self.source_run},'worker':{'state':'ready'}}
        def start(self,*args):self.calls.append(args);self.source_run=args[1];self.active=True;return self.snapshot()
        def stop(self,ident):self.active=False;return self.snapshot()
    monkeypatch.setattr('theiatron.live_service.LiveService',Live)
    return Live


def reserve(port,**extra):
    return request(port,'/api/live/uploads','POST',json.dumps({'filename':'new.mov','size_bytes':4,**extra}),
                   {'X-Theiatron-Token':server.SESSION_TOKEN})


def test_new_upload_starts_detector_without_running_full_analysis(http,isolated,detector,monkeypatch):
    pipeline=[]
    monkeypatch.setattr(server,'_run_pipeline',lambda *args:pipeline.append(args))
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    status,_,raw=reserve(http,duration=30,fps=5)
    job=json.loads(raw)
    assert status==201 and job['kind']=='live-source' and job['state']=='uploading'
    assert json.loads(request(http,'/api/live')[2])['other_job_busy']
    status,_,raw=request(http,f'/api/live/uploads/{job["id"]}/content','POST',b'DATA',headers)
    result=json.loads(raw)
    assert status==202 and result['source']['state']=='complete' and result['live']['busy']
    assert len(detector.calls)==1
    path,source_run,duration,fps,loop=detector.calls[0]
    assert path.read_bytes()==b'DATA' and source_run==job['id'] and duration==30 and fps==5
    assert not (isolated/'out'/job['id']/'simulation.json').exists()
    assert not pipeline
    sources=json.loads(request(http,'/api/live/sources')[2])
    assert sources[0]['kind']=='live-source' and 'upload_path' not in sources[0]
    assert request(http,f'/api/runs/{job["id"]}/live-geometry')[0]==400
    # Uploaded bytes cannot be fetched via the public asset server or used as a
    # reviewed/counting profile simply because their transfer completed.
    assert request(http,f'/out/uploads/{job["id"]}/new.mov')[0]==404
    with pytest.raises(ValueError):server._retained_source(job['id'])


def test_upload_security_sizes_and_admission(http,detector):
    assert request(http,'/api/live/uploads','POST','{}')[0]==403
    for extra in [{'size_bytes':0},{'size_bytes':True},{'size_bytes':5*1024**3},
                  {'filename':'bad.exe'},{'fps':100},{'loop':'true'},{'source':'/tmp/private'}]:
        assert reserve(http,**extra)[0]==400
    job=json.loads(reserve(http)[2]);headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    assert reserve(http)[0]==409
    assert request(http,'/api/compare','POST','{}',headers)[0]==409
    path=f'/api/live/uploads/{job["id"]}/content'
    assert request(http,path,'POST',b'123',headers)[0]==400
    assert server.JOBS[job['id']]['stage']=='awaiting-upload'
    assert not detector.calls
    assert request(http,path,'POST',b'1234',headers)[0]==202
    assert request(http,path,'POST',b'5678',headers)[0]==400
    assert detector.calls[0][0].read_bytes()==b'1234'


def test_cancel_reservation_and_stalled_upload_never_start_detection(http,detector):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    job=json.loads(reserve(http,size_bytes=100)[2]);ident=job['id']
    sock=socket.create_connection(('127.0.0.1',http),timeout=3)
    sock.sendall((f'POST /api/live/uploads/{ident}/content HTTP/1.1\r\nHost: 127.0.0.1:{http}\r\n'
        f'Content-Length: 100\r\nX-Theiatron-Token: {server.SESSION_TOKEN}\r\n\r\npartial').encode())
    deadline=time.monotonic()+2
    while server.JOBS[ident]['stage']!='receiving-upload' and time.monotonic()<deadline:time.sleep(.01)
    assert request(http,f'/api/runs/{ident}/cancel','POST','{}',headers)[0]==200
    sock.shutdown(socket.SHUT_WR)
    sock.recv(4096);sock.close()
    assert server.JOBS[ident]['state']=='cancelled' and not detector.calls
    assert not (server.UPLOAD_ROOT/ident/'new.mov').exists()
    assert not (server.UPLOAD_ROOT/ident/'.uploading').exists()


def test_reservation_expiry_and_restart_recovery(http):
    first=json.loads(reserve(http)[2])['id']
    server._expire_live_upload(first)
    assert server.JOBS[first]['state']=='cancelled'
    second=json.loads(reserve(http)[2])['id']
    server.JOBS.clear();server._load_jobs()
    assert server.JOBS[second]['state']=='interrupted'
    assert reserve(http)[0]==201


def test_late_upload_cancel_stops_only_its_source_and_keeps_completed_bytes(http,detector):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    ident=json.loads(reserve(http)[2])['id']
    request(http,f'/api/live/uploads/{ident}/content','POST',b'DATA',headers)
    cancel=f'/api/live/uploads/{ident}/cancel'
    assert request(http,cancel,'POST','{}',headers)[0]==200
    assert not server.LIVE_SERVICE.active and server.JOBS[ident]['state']=='complete'
    assert detector.calls[0][0].read_bytes()==b'DATA'
    server.LIVE_SERVICE.active=True;server.LIVE_SERVICE.source_run='another-source'
    assert request(http,cancel,'POST','{}',headers)[0]==200
    assert server.LIVE_SERVICE.active


@pytest.mark.parametrize('endpoint,kind',[('analyse','video'),('reconstruct','reconstruction')])
def test_prepare_road_reuses_upload_and_requires_stop_and_acknowledgement(http,detector,endpoint,kind):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    ident=json.loads(reserve(http)[2])['id']
    request(http,f'/api/live/uploads/{ident}/content','POST',b'DATA',headers)
    path=f'/api/live/sources/{ident}/{endpoint}'
    assert request(http,path,'POST','{}',headers)[0]==400
    ack='{"acknowledge_estimates":true}'
    assert request(http,path,'POST',ack,headers)[0]==409
    server.LIVE_SERVICE.active=False
    status,_,raw=request(http,path,'POST',ack,headers)
    analysis=json.loads(raw)
    assert status==202 and analysis['kind']==kind and analysis['state']=='queued'
    assert analysis['parent_source_run']==ident
    assert server.JOBS[analysis['id']]['upload_path']==server.JOBS[ident]['upload_path']
    if kind=='reconstruction':
        assert json.loads(request(http,'/api/live')[2])['reconstruction_jobs'][0]['id']==analysis['id']
        server._update_job(analysis['id'],state='complete')
        assert server._retained_source(analysis['id'],allow_reconstruction=True).is_file()
        assert server._retained_source(analysis['id'],allow_live_source=True).is_file()
        with pytest.raises(ValueError): server._retained_source(analysis['id'])
        assert request(http,f'/api/runs/{analysis["id"]}/counting')[0]==400
        assert any(j['id']==analysis['id'] for j in json.loads(request(http,'/api/live/sources')[2]))


def test_preexisting_upload_directory_is_not_modified_on_failure(http,detector):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    ident=json.loads(reserve(http)[2])['id']
    directory=server.UPLOAD_ROOT/ident;directory.mkdir()
    sentinel=directory/'.uploading';sentinel.write_bytes(b'existing material')
    assert request(http,f'/api/live/uploads/{ident}/content','POST',b'DATA',headers)[0]==400
    assert sentinel.read_bytes()==b'existing material' and not detector.calls


def test_upload_decode_failure_does_not_destroy_retained_bytes(http,monkeypatch):
    def fail(*args,**kwargs):raise OSError('worker launch failed')
    monkeypatch.setattr('theiatron.live_service.LiveService.start',fail)
    ident=json.loads(reserve(http)[2])['id']
    status,_,raw=request(http,f'/api/live/uploads/{ident}/content','POST',b'DATA',{'X-Theiatron-Token':server.SESSION_TOKEN})
    result=json.loads(raw)
    assert status==202 and result['start_error']=='worker launch failed'
    assert result['source']['state']=='complete' and not result['live']['busy']
    assert server._retained_source(ident,allow_live_source=True).read_bytes()==b'DATA'
