import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from theiatron import visual_capture
from theiatron.artifacts import fingerprint, load_artifact
from theiatron.detection import Detection
from theiatron.io import atomic_json
from theiatron.provenance import file_hash
from theiatron.reconstruction import source


@pytest.fixture
def visual(tmp_path, monkeypatch):
    import run_demo
    # An explicit regression guard: no counting calibration may be invoked.
    def forbidden(*args, **kwargs): raise AssertionError('counting calibration must not run')
    monkeypatch.setattr(run_demo,'_calibration_quality',forbidden)
    monkeypatch.setattr(visual_capture,'vision_provenance',lambda model: {'code_sha256':{}})
    video = tmp_path/'input.mp4'
    writer = cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),30.,(320,180))
    assert writer.isOpened()
    for _ in range(30): writer.write(np.full((180,320,3),80,np.uint8))
    writer.release()
    class Detector:
        ticks = 0
        def __init__(self,cfg): pass
        def track(self,frame):
            assert frame.shape == (720,1280,3)
            self.ticks += 1
            return [Detection(1,400+self.ticks,500,(380+self.ticks,450,420+self.ticks,500),2,.9)]
    out = tmp_path/'out'/'visual'
    artifact = visual_capture.capture(video,out,duration=1,detector_factory=Detector)
    return tmp_path,out,artifact


def test_capture_without_counting_has_exact_clock_and_no_simulation(visual):
    root,out,artifact = visual
    assert visual_capture.load_source(out) == artifact
    assert artifact['frames'] == 10 and artifact['duration'] == 1 and artifact['cadence_s'] == .1
    assert not any((out/name).exists() for name in ['simulation.json','events.json','manifest.json','config.yaml','footage-raw.mp4'])
    current = source(root,'visual')
    assert current['counting_available'] is False and current['plate_reference_supported']
    assert current['calibration']['road'] == []
    assert current['tracks']['counted'] == []
    assert current['tracks']['extras'][0]['pts'][-1] == [1,410,500]
    assert current['binding']['source_artifact_id'] == artifact['artifact_id']
    with pytest.raises(ValueError): load_artifact(out/visual_capture.NAME)


@pytest.mark.parametrize('asset',visual_capture.ASSETS)
def test_visual_source_rejects_changed_assets(visual,asset):
    root,out,_ = visual
    (out/asset).write_bytes(b'changed')
    with pytest.raises(ValueError,match='asset checksum'): source(root,'visual')


def test_visual_source_cannot_smuggle_arrival_counts(visual):
    root,out,artifact = visual
    path = out/'recorded-tracks.json'
    dense = json.loads(path.read_text())
    dense['tracks'][0].update(approach='north',count_number=1)
    atomic_json(path,dense)
    artifact['assets'][path.name] = file_hash(path)
    artifact.pop('artifact_id')
    artifact['artifact_id'] = fingerprint(artifact)
    atomic_json(out/visual_capture.NAME,artifact)
    with pytest.raises(ValueError,match='arrival counts'): source(root,'visual')


def test_counting_quality_gate_still_rejects_two_track_corridor():
    from run_demo import _calibration_quality
    corridors = [SimpleNamespace(tracks=list(range(n)),phase=p,name=str(i),
                    count_line=[[0,0],[100,100]],approach_side=[0,50])
                 for i,(n,p) in enumerate([(12,'NS'),(12,'NS'),(13,'EW'),(2,'EW')])]
    result = _calibration_quality(corridors,44)
    assert result['score'] > .9 and result['label'] == 'low'
