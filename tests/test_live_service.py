import json
from types import SimpleNamespace
import pytest
from theiatron.live_service import LiveService


def test_launch_failure_releases_admission(tmp_path,monkeypatch):
    service=LiveService(tmp_path)
    def fail(*args,**kwargs):raise OSError('test launch failure')
    monkeypatch.setattr('subprocess.Popen',fail)
    with pytest.raises(OSError):service.start(tmp_path/'file.mov','source')
    assert not service.busy() and service.worker_state=='offline'


def test_dead_worker_cannot_be_revived_by_last_saved_running_snapshot(tmp_path):
    service=LiveService(tmp_path)
    service.worker_state='offline'
    service.proc=SimpleNamespace(pid=123)
    service.session={'id':'live-test','state':'interrupted','requested_at':10,'error':'worker exited'}
    out=tmp_path/'out/live-test';out.mkdir(parents=True)
    (out/'latest.json').write_text(json.dumps({'id':'live-test','state':'running','started_at':11,
        'last_observation':{'completed_at':12},'first_observation_s':.2}))
    state=service.snapshot()
    assert not state['busy'] and state['session']['state']=='interrupted'
    assert state['session']['error']=='worker exited'


def test_stop_timeout_only_targets_same_stopping_session(tmp_path,monkeypatch):
    service=LiveService(tmp_path)
    service.worker_state='ready'
    service.proc=SimpleNamespace(pid=123,poll=lambda:None)
    service.session={'id':'one','state':'complete'}
    killed=[]
    monkeypatch.setattr('os.killpg',lambda *args:killed.append(args))
    service._deadline(service.proc,'one');assert not killed
    service.session['state']='stopping'
    service._deadline(service.proc,'old');assert not killed
    service._deadline(service.proc,'one');assert killed[0][0]==123
