"""Local service boundaries and job lifecycle, using real HTTP requests."""
import concurrent.futures
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import socket
import subprocess
import sys
import threading
import time

import pytest
import launcher_server as server


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    monkeypatch.setattr(server, 'UPLOAD_ROOT', tmp_path/'out'/'uploads')
    monkeypatch.setattr(server, 'JOB_STORE', tmp_path/'out'/'.launcher'/'jobs.json')
    monkeypatch.setattr(server, 'JOBS', {})
    monkeypatch.setattr(server, 'PROCESSES', {})
    monkeypatch.setattr(server, 'REFINEMENTS', {})
    monkeypatch.setattr(server, 'SUMO_STATUS', {'ready': True})
    monkeypatch.setattr(server, 'LIVE_SERVICE', None)
    monkeypatch.setattr(server, '_run_pipeline', lambda *args: None)
    for path, content in [('workbench/index.html', '<h1>Workbench</h1>'), ('.git/config','SECRET'),
                          ('out/demo/footage.mp4','0123456789'), ('out/demo/report.json','{}'),
                          ('out/uploads/upload/movie.mov','SOURCE'), ('README.md','PRIVATE')]:
        p = tmp_path/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


@pytest.fixture
def http(isolated):
    service = ThreadingHTTPServer(('127.0.0.1', 0), server.LauncherHandler)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service.server_address[1]
    service.shutdown()
    service.server_close()
    thread.join()


def request(port, path, method='GET', body=None, headers=None):
    connection = HTTPConnection('127.0.0.1', port, timeout=3)
    connection.request(method, path, body, headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def test_continuous_api_rejects_paths_urls_bad_rates_and_unretained_sources(http,isolated):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    assert request(http,'/api/live')[0]==200
    assert request(http,'/api/live/start','POST','{}')[0]==403
    for payload in [{'source':'/tmp/private.mov'},{'source':'rtsp://camera'},
                    {'source_run':'missing'},{'source_run':'missing','duration':True},
                    {'source_run':'missing','duration':float('nan')},{'source_run':'missing','fps':60},
                    {'source_run':'missing','loop':'true'},[]]:
        assert request(http,'/api/live/start','POST',json.dumps(payload),headers)[0]==400
    assert server.LIVE_SERVICE is None


def test_live_geometry_endpoint_is_read_only_and_reports_unavailable_mapping(http, monkeypatch):
    def geometry(root, run):
        if run != 'source': raise ValueError('mapping unavailable')
        return {'binding': {'source_run': run}, 'registration': [], 'metric_accuracy_validated': False}
    monkeypatch.setattr(server, 'live_geometry', geometry)
    status, _, raw = request(http, '/api/runs/source/live-geometry')
    assert status == 200 and json.loads(raw)['binding']['source_run'] == 'source'
    assert request(http, '/api/runs/unknown/live-geometry')[0] == 400


def test_assisted_geometry_endpoints_are_token_protected_bounded_and_separate(http,monkeypatch):
    calls=[]
    def preview(root,run,payload):
        calls.append(('preview',run,payload));return {'status':'unsaved-assisted-estimate'}
    def save(root,run,payload):
        calls.append(('save',run,payload));return {'status':'draft-unvalidated'}
    monkeypatch.setattr(server,'preview_assisted',preview)
    monkeypatch.setattr(server,'save_assisted',save)
    path='/api/runs/source/reconstruction/assist'
    assert request(http,path,'POST','{}')[0]==403
    assert not calls
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    assert request(http,path,'POST','{}',headers)[0]==200
    assert request(http,path+'/save','POST','{}',headers)[0]==201
    assert [c[0] for c in calls]==['preview','save']
    assert request(http,path,'POST','x'*32769,headers)[0]==400
    assert request(http,path,'POST','{bad',headers)[0]==400
    assert len(calls)==2


def test_assisted_geometry_real_http_preview_save_and_reload(http,isolated):
    from test_site_profiles import make_source
    from test_assisted_geometry import selection
    make_source(isolated)
    folder=isolated/'out'/'source'
    (folder/'tracks.json').write_text(json.dumps({'counted':[],'extras':[]}))
    (folder/'plate.jpg').write_bytes(b'synthetic test plate')
    status,_,raw=request(http,'/api/runs/source/reconstruction')
    assert status==200
    current=json.loads(raw);lines,base=selection()
    body=json.dumps({'binding':current['binding'],'base_revision':None,'calibration':base,'lines':lines})
    headers={'X-Theiatron-Token':server.SESSION_TOKEN,'Content-Type':'application/json'}
    path='/api/runs/source/reconstruction/assist'
    status,_,raw=request(http,path,'POST',body,headers)
    assert status==200,raw
    preview=json.loads(raw)
    assert preview['status']=='unsaved-assisted-estimate'
    assert not (isolated/'out'/'.reconstructions').exists()
    status,_,raw=request(http,path+'/save','POST',body,headers)
    assert status==201,raw
    saved=json.loads(raw)
    assert saved['calibration']==preview['calibration']
    status,_,raw=request(http,'/api/runs/source/reconstruction')
    fresh=json.loads(raw)
    assert status==200 and fresh['revision']==saved['revision']
    assert fresh['assistance']['method']=='operator-road-directions-v1'
    assert fresh['metric_accuracy_validated'] is False
    assert request(http,path+'/save','POST',body,headers)[0]==400
    # Saved directions alone do not authorize projecting native frames.
    assert request(http,'/api/runs/source/live-geometry')[0]==400
    from test_reconstruction import install_live_registration
    (folder/'manifest.json').write_text(json.dumps({'three_d': {'plate_mode': 'first-processed-frame'}}))
    install_live_registration(isolated)
    status,_,raw=request(http,'/api/runs/source/live-geometry')
    assert status==200,raw
    geometry=json.loads(raw)
    assert geometry['projection_kind']=='operator-assisted-estimate'
    assert geometry['calibration']==saved['calibration']
    assert geometry['calibration_revision']==saved['revision']
    assert 'NEVER_SEND_SAVED_MOTION' not in raw.decode()
    assert geometry['metric_accuracy_validated'] is False


def test_live_admission_excludes_file_jobs_and_requires_matching_stop_id(http,isolated,monkeypatch):
    class Live:
        active=False
        def __init__(self,*args):pass
        def busy(self):return self.active
        def snapshot(self):return {'busy':self.active,'session':{'id':'live-test'},'worker':{'state':'ready'}}
        def start(self,*args):self.active=True;return self.snapshot()
        def stop(self,ident):
            if ident!='live-test':raise ValueError('session identity changed')
            self.active=False;return self.snapshot()
    monkeypatch.setattr('theiatron.live_service.LiveService',Live)
    server.JOBS['source']={'kind':'video','state':'complete','upload_path':str(isolated/'out/uploads/upload/movie.mov')}
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    assert request(http,'/api/live/start','POST',json.dumps({'source_run':'source'}),headers)[0]==202
    assert request(http,'/api/compare','POST','{}',headers)[0]==409
    assert request(http,'/api/live/start','POST',json.dumps({'source_run':'source'}),headers)[0] in {400,409}
    assert request(http,'/api/live/stop','POST','{"id":"wrong"}',headers)[0]==400
    assert request(http,'/api/live/stop','POST','{"id":"live-test"}',headers)[0]==200
    assert request(http,'/api/compare','POST','{}',headers)[0]==202


@pytest.mark.parametrize('path', ['/.git/config', '/README.md', '/out/', '/out/uploads/upload/movie.mov',
    '/out/demo/../../README.md', '/workbench/%2e%2e/README.md', '/out/.launcher/jobs.json'])
def test_private_paths_never_served(http, path):
    assert request(http, path)[0] == 404
    assert request(http, path, 'HEAD')[0] == 404


def test_automatic_demo_requires_completed_source_and_explicit_estimates(http,isolated):
    from test_site_profiles import make_source
    make_source(isolated)
    path='/api/runs/source/demo-profile'
    payload=json.dumps({'acknowledge_estimates':True})
    headers={'X-Theiatron-Token':server.SESSION_TOKEN,'Content-Type':'application/json'}
    assert request(http,path,'POST',payload)[0]==403
    assert request(http,path,'POST',payload,headers)[0]==400
    server.JOBS['source']={'kind':'video','state':'complete'}
    assert request(http,path,'POST','{}',headers)[0]==400
    status,_,body=request(http,path,'POST',payload,headers)
    assert status==201 and json.loads(body)['review_status']=='draft-unreviewed'
    p=json.loads(body)
    scenario={'duration':60,'demand':'balanced','generated_demand':True,'site_revision':p['revision'],
              'acknowledge_assumptions':True,'pace':0}
    assert request(http,'/api/compare','POST',json.dumps(scenario),headers)[0]==202
    assert request(http,'/api/runs/source/evidence.zip')[0]==400


def test_symlinks_cannot_escape_allowlist(http, isolated):
    (isolated/'workbench'/'leak.js').symlink_to(isolated/'.git'/'config')
    assert request(http, '/workbench/leak.js')[0] == 404


def test_public_asset_and_video_ranges(http):
    assert request(http, '/workbench/')[0] == 200
    status, headers, data = request(http, '/out/demo/footage.mp4', headers={'Range':'bytes=2-4'})
    assert status == 206 and data == b'234'
    assert headers['Content-Range'] == 'bytes 2-4/10'
    assert request(http, '/out/demo/footage.mp4', 'HEAD')[2] == b''
    assert request(http, '/out/demo/footage.mp4', headers={'Range':'bytes=40-'})[0] == 416


def test_reconstruction_http_is_source_bound_and_write_protected(http,isolated):
    from test_site_profiles import make_source
    from theiatron.reconstruction import default_calibration, IMG_0635_SHA
    make_source(isolated)
    (isolated/'out'/'source'/'tracks.json').write_text('{"counted":[],"extras":[]}')
    (isolated/'out'/'source'/'plate.jpg').write_bytes(b'plate')
    path='/api/runs/source/reconstruction'
    status,_,raw=request(http,path)
    assert status==200
    source=json.loads(raw)
    assert source['calibration']['road']==[]  # no first-clip fallback
    payload={'binding':source['binding'],'calibration':default_calibration(IMG_0635_SHA)}
    assert request(http,path,'POST',json.dumps(payload))[0]==403
    headers={'X-Theiatron-Token':server.SESSION_TOKEN,'Content-Type':'application/json'}
    status,_,raw=request(http,path,'POST',json.dumps(payload),headers)
    assert status==201
    assert json.loads(raw)['status']=='draft-unvalidated'
    assert json.loads(request(http,path)[2])['revision']==json.loads(raw)['revision']
    payload['binding']['source_sha256']='b'*64
    assert request(http,path,'POST',json.dumps(payload),headers)[0]==400
    assert request(http,path,'POST','x'*32769,headers)[0]==400
    assert request(http,'/api/runs/missing/reconstruction')[0]==400


def test_dns_rebinding_and_cross_origin_blocked(http):
    assert request(http, '/api/health', headers={'Host':f'evil.example:{http}'})[0] == 403
    assert request(http, '/api/health', headers={'Origin':'https://evil.example'})[0] == 403
    assert request(http, '/api/compare', 'POST', '{}')[0] == 403
    assert request(http, '/api/health')[0] == 200


def test_atomic_admission_during_concurrent_requests(isolated):
    def reserve(_):
        try:
            return server._reserve('movie.mov', 'video')
        except ValueError:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert len([r for r in pool.map(reserve, range(8)) if r]) == 1
    assert len(server.JOBS) == 1
    assert next(iter(server.JOBS.values()))['state'] == 'uploading'


def test_upload_reserves_before_body_and_cancel_is_durable(http):
    sock = socket.create_connection(('127.0.0.1', http), timeout=3)
    sock.sendall((f'POST /api/runs?filename=test.mov HTTP/1.1\r\nHost: 127.0.0.1:{http}\r\n'
                 f'Content-Length: 100\r\nX-Theiatron-Token: {server.SESSION_TOKEN}\r\n\r\n').encode())
    try:
        deadline = time.monotonic()+2
        while not server.JOBS and time.monotonic()<deadline:
            time.sleep(.01)
        run_id = next(iter(server.JOBS))
        assert server.JOBS[run_id]['state'] == 'uploading'
        headers={'X-Theiatron-Token':server.SESSION_TOKEN}
        assert request(http, '/api/compare', 'POST', '{}', headers)[0] == 409
        assert request(http, f'/api/runs/{run_id}/cancel', 'POST', '{}', headers)[0] == 200
        assert json.loads(server.JOB_STORE.read_text())[run_id]['state'] == 'cancelled'
        sock.sendall(b'x'*100)
        sock.recv(4096)
        assert server.JOBS[run_id]['state'] == 'cancelled'
    finally:
        sock.close()


def test_recovery_never_labels_interrupted_work_complete(isolated):
    run_id=server._reserve('sumo', 'sumo')
    server._update_job(run_id,state='processing')
    server.JOBS.clear()
    server._load_jobs()
    assert server.JOBS[run_id]['state'] == 'interrupted'
    assert 'Partial output' in server.JOBS[run_id]['message']


def test_cancel_stops_owned_process(isolated):
    run_id=server._reserve('sumo', 'sumo')
    proc=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], start_new_session=True)
    server.PROCESSES[run_id]=proc
    try:
        server._cancel(run_id)
        assert proc.poll() is not None
        assert server.JOBS[run_id]['state'] == 'cancelled'
    finally:
        server._stop_process(proc)


def test_scenario_validation_rejects_bad_payload_and_no_jobs(http):
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    for payload in ['{"duration": -1}', '{"seed":true}', '{"scale":NaN}', '{"path":"/tmp/evil"}', '[]']:
        assert request(http,'/api/compare','POST',payload,headers)[0] == 400
    assert not server.JOBS


def test_profile_api_requires_real_complete_source_and_explicit_assumptions(http, isolated):
    from test_site_profiles import make_source, routed
    profile = make_source(isolated)
    headers = {'X-Theiatron-Token':server.SESSION_TOKEN}
    endpoint = '/api/profiles'
    body = json.dumps({'source_run':'source'})
    assert request(http,endpoint,'POST',body)[0] == 403
    assert request(http,endpoint,'POST',body,headers)[0] == 400
    server.JOBS['source'] = {'id':'source','kind':'video','state':'processing'}
    assert request(http,endpoint,'POST',body,headers)[0] == 400
    server.JOBS['source']['state'] = 'complete'
    status, _, data = request(http,endpoint,'POST',body,headers)
    assert status == 201 and json.loads(data) == profile
    path = endpoint + '/' + profile['revision']
    assert request(http,path)[0] == 200
    assert request(http,path+'/revisions','POST','{"review_status":"reviewed"}',headers)[0] == 400
    assert request(http,path+'/revisions','POST','{"label":"Renamed hypothesis"}',headers)[0] == 201
    assert json.loads(request(http,path)[2]) == profile
    payload = {'site_revision':profile['revision'],'demand':'observed','duration':36,'pace':0}
    assert request(http,'/api/compare','POST',json.dumps(payload),headers)[0] == 400
    payload['acknowledge_assumptions'] = True
    # Acknowledgement alone cannot make missing routes runnable.
    assert request(http,'/api/compare','POST',json.dumps(payload),headers)[0] == 400
    ready = routed(isolated,profile)
    payload.update(site_revision=ready['revision'],duration=60)
    assert request(http,'/api/compare','POST',json.dumps(payload),headers)[0] == 400
    payload['duration'] = 36
    status, _, result = request(http,'/api/compare','POST',json.dumps(payload),headers)
    assert status == 202
    assert json.loads(result)['scenario']['site_revision'] == ready['revision']


def test_recount_uses_only_known_retained_upload_and_creates_new_job(http,isolated):
    from test_site_profiles import make_source
    from theiatron.recount import counting_source
    make_source(isolated)
    video = isolated/'out'/'uploads'/'upload'/'movie.mov'
    server.JOBS['source']={'id':'source','kind':'video','state':'complete','upload_path':str(video)}
    headers={'X-Theiatron-Token':server.SESSION_TOKEN}
    status,_,body = request(http,'/api/runs/source/counting')
    assert status == 200
    camera = json.loads(body)
    assert 'config' not in camera and 'source' not in camera
    payload={'source_run':'source','approaches':camera['approaches'],'acknowledge_candidate':True}
    assert request(http,'/api/recounts','POST',json.dumps(payload))[0] == 403
    payload['video']='/etc/passwd'
    assert request(http,'/api/recounts','POST',json.dumps(payload),headers)[0] == 400
    payload.pop('video')
    payload['acknowledge_candidate']=False
    assert request(http,'/api/recounts','POST',json.dumps(payload),headers)[0] == 400
    payload['acknowledge_candidate']=True
    original = counting_source(isolated,'source')
    status,_,body = request(http,'/api/recounts','POST',json.dumps(payload),headers)
    assert status == 202
    job=json.loads(body)
    assert job['id'] != 'source' and job['kind']=='video' and job['state']=='queued'
    assert job['camera_revision'] and job['parent_source_run']=='source'
    assert 'upload_path' not in job
    assert server.JOBS[job['id']]['upload_path'] == str(video)
    assert counting_source(isolated,'source') == original
    assert request(http,'/api/recounts','POST',json.dumps(payload),headers)[0] == 409


def test_recount_rejects_missing_or_escaped_retained_file(isolated):
    server.JOBS['source']={'kind':'video','state':'complete'}
    with pytest.raises(ValueError,match='not retained'):
        server._retained_source('source')
    server.JOBS['source']['upload_path']=str(isolated/'README.md')
    with pytest.raises(ValueError):
        server._retained_source('source')
    link=isolated/'out'/'uploads'/'link.mov'
    link.symlink_to(isolated/'README.md')
    server.JOBS['source']['upload_path']=str(link)
    with pytest.raises(ValueError,match='symlink'):
        server._retained_source('source')


@pytest.fixture
def refinement_source(isolated, monkeypatch):
    """Keep lifecycle tests independent of CV, model weights and user artifacts."""
    binding = {'source_sha256': 'a'*64, 'artifact_sha256': 'b'*64}
    video = isolated/'out'/'uploads'/'upload'/'movie.mov'
    server.JOBS['source'] = {'id': 'source', 'kind': 'video', 'state': 'complete',
                             'upload_path': str(video)}
    monkeypatch.setattr(server, 'reconstruction_source', lambda *_: {'binding': binding})
    monkeypatch.setattr(server, '_refinement_worker', lambda *_: None)
    return binding, video


def test_refinement_http_requires_token_same_origin_and_source_binding(http, refinement_source):
    binding, _ = refinement_source
    endpoint = '/api/runs/source/refine'
    payload = json.dumps({'binding': binding})
    headers = {'X-Theiatron-Token': server.SESSION_TOKEN, 'Content-Type': 'application/json'}
    assert request(http, endpoint, 'POST', payload)[0] == 403
    assert request(http, endpoint, 'POST', payload, headers | {'Origin': 'https://evil.example'})[0] == 403
    assert request(http, endpoint, 'POST', payload, headers | {'Host': 'evil.example'})[0] == 403
    for body in ['', '[]', '{}', '{"binding":{}}', '{"binding":null}',
                 json.dumps({'binding': binding, 'video': '/etc/passwd'}), 'x'*4097]:
        assert request(http, endpoint, 'POST', body, headers)[0] == 400
    assert not server.REFINEMENTS
    assert json.loads(request(http, endpoint)[2])['state'] == 'idle'
    status, _, body = request(http, endpoint, 'POST', payload, headers)
    assert status == 202 and json.loads(body)['state'] == 'queued'
    assert json.loads(request(http, endpoint)[2])['state'] == 'queued'
    assert request(http, endpoint, 'POST', payload, headers)[0] == 409


def test_refinement_http_requires_retained_completed_local_footage(http, refinement_source):
    binding, _ = refinement_source
    headers = {'X-Theiatron-Token': server.SESSION_TOKEN}
    payload = json.dumps({'binding': binding})
    endpoint = '/api/runs/source/refine'
    for state in ['queued', 'processing', 'failed', 'cancelled']:
        server.JOBS['source']['state'] = state
        assert request(http, endpoint, 'POST', payload, headers)[0] == 400
    server.JOBS['source'].update(state='complete', upload_path='/etc/passwd')
    assert request(http, endpoint, 'POST', payload, headers)[0] == 400
    assert request(http, '/api/runs/missing/refine', 'POST', payload, headers)[0] == 400
    assert not server.REFINEMENTS


def test_refinement_and_other_jobs_share_atomic_single_worker_admission(isolated, refinement_source):
    binding, _ = refinement_source
    def reserve(index):
        try:
            if index % 2:
                server._start_refinement('source', binding)
            else:
                server._reserve('comparison', 'sumo')
            return True
        except ValueError:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(reserve, range(24))) == 1
    active = [j for j in [*server.JOBS.values(), *server.REFINEMENTS.values()]
              if j['state'] in server.ACTIVE]
    assert len(active) == 1


@pytest.mark.parametrize('state', ['queued', 'processing', 'cancelling'])
def test_active_refinement_blocks_upload_and_comparison(http, refinement_source, state):
    server.REFINEMENTS['source'] = {'state': state}
    headers = {'X-Theiatron-Token': server.SESSION_TOKEN}
    assert request(http, '/api/compare', 'POST', '{}', headers)[0] == 409
    assert request(http, '/api/runs?filename=test.mov', 'POST', 'video', headers)[0] == 409
    assert len(server.JOBS) == 1


def test_refinement_cancel_is_authenticated_idempotent_and_leaves_source_unchanged(http, refinement_source):
    binding, _ = refinement_source
    headers = {'X-Theiatron-Token': server.SESSION_TOKEN}
    server._start_refinement('source', binding)
    before = dict(server.JOBS['source'])
    endpoint = '/api/runs/source/refine/cancel'
    assert request(http, endpoint, 'POST', '{}')[0] == 403
    assert server.REFINEMENTS['source']['state'] == 'queued'
    for _ in range(2):
        status, _, data = request(http, endpoint, 'POST', '{}', headers)
        assert status == 200 and json.loads(data)['state'] == 'cancelled'
    assert server.JOBS['source'] == before
    assert json.loads(request(http, '/api/runs/source/refine')[2])['state'] == 'cancelled'
    assert json.loads(request(http, '/api/runs/missing/refine/cancel', 'POST', '{}', headers)[2])['state'] == 'idle'
    server._reserve('next comparison', 'sumo')


def test_refinement_cancel_stops_only_its_owned_process(isolated):
    server.REFINEMENTS['source'] = {'state': 'processing'}
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    server.PROCESSES['refine-source'] = proc
    try:
        server._cancel_refinement('source')
        assert proc.poll() is not None
        assert server.REFINEMENTS['source']['state'] == 'cancelled'
    finally:
        server._stop_process(proc)


class RefinementTimer:
    def __init__(self, seconds, callback):
        self.seconds, self.callback = seconds, callback
        self.started = self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.mark.parametrize('exit_code,result,expected', [
    (0, {'revision': 'r1', 'stale': False}, 'complete'),
    (1, {'revision': 'r1', 'stale': False}, 'failed'),
    (0, {'revision': 'r1', 'stale': True}, 'failed'),
    (0, None, 'failed'),
])
def test_refinement_worker_bounded_runtime_validates_result_and_cleans_up(
        isolated, monkeypatch, exit_code, result, expected):
    timers, launches, stopped = [], [], []
    class Process:
        stdout = iter(['Registering frame 1/10\n', 'Refining track 1/2\n'])
        def wait(self):
            return exit_code
    proc = Process()
    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return proc
    def timer(seconds, callback):
        timers.append(RefinementTimer(seconds, callback))
        return timers[-1]
    monkeypatch.setattr(server.subprocess, 'Popen', launch)
    monkeypatch.setattr(server.threading, 'Timer', timer)
    monkeypatch.setattr(server, '_stop_process', stopped.append)
    monkeypatch.setattr(server, 'reconstruction_source', lambda *_: {'refinement': result})
    server.REFINEMENTS['source'] = {'state': 'queued'}
    video = isolated/'out'/'uploads'/'upload'/'movie.mov'
    server._refinement_worker('source', video)
    assert server.REFINEMENTS['source']['state'] == expected
    assert 'refine-source' not in server.PROCESSES
    assert stopped == [proc]
    assert len(timers) == 1 and timers[0].seconds == 600
    assert timers[0].started and timers[0].cancelled
    command, options = launches[0]
    assert command == [sys.executable, '-m', 'theiatron.refinement', '--run', 'source', '--video', str(video)]
    assert options['cwd'] == isolated and options['start_new_session'] is True
    assert options['env']['THEIATRON_PARENT_PID'].isdigit()
    if expected == 'complete':
        assert server.REFINEMENTS['source']['revision'] == 'r1'
    else:
        assert 'revision' not in server.REFINEMENTS['source']


def test_cancelled_queued_refinement_never_spawns_process(isolated, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('A cancelled queued refinement must not start a process')
    monkeypatch.setattr(server.subprocess, 'Popen', unexpected)
    server.REFINEMENTS['source'] = {'state': 'cancelled'}
    server._refinement_worker('source', isolated/'unused.mov')
    assert server.REFINEMENTS['source']['state'] == 'cancelled'


def test_old_refinement_cleanup_does_not_remove_restarted_worker(isolated, monkeypatch):
    """Cancel/retry may publish the next attempt before the old thread unwinds."""
    new_proc = object()
    class OldProcess:
        stdout = iter([])
        def wait(self):
            # Simulate cancellation followed by a new attempt while this old
            # worker is unwinding. The new attempt must retain process ownership.
            server.REFINEMENTS['source'] = {'state': 'queued'}
            server.PROCESSES['refine-source'] = new_proc
            return -15
    old_proc = OldProcess()
    monkeypatch.setattr(server.subprocess, 'Popen', lambda *args, **kwargs: old_proc)
    monkeypatch.setattr(server.threading, 'Timer', RefinementTimer)
    monkeypatch.setattr(server, '_stop_process', lambda *_: None)
    server.REFINEMENTS['source'] = {'state': 'queued'}
    server._refinement_worker('source', isolated/'unused.mov')
    assert server.REFINEMENTS['source']['state'] == 'queued'
    assert server.PROCESSES.get('refine-source') is new_proc
