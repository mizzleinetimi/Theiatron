import json
import numpy as np
from theiatron.preview import PreviewPublisher


def test_preview_is_bounded_and_timestamped(tmp_path):
    publisher = PreviewPublisher(tmp_path)
    publisher.publish(np.zeros((720,1280,3),dtype=np.uint8),12.5,'calibrating',detections=3)
    p=json.loads((tmp_path/'progress.json').read_text())
    assert p['mode'] == 'file-analysed-now' and p['source_time_s']==12.5
    assert p['detections']==3
    assert (tmp_path/'preview.jpg').stat().st_size>0
    publisher.publish(np.zeros((720,1280,3),dtype=np.uint8),13,'calibrating')
    assert json.loads((tmp_path/'progress.json').read_text()) == p
    assert set(f.name for f in tmp_path.iterdir()) == {'preview.jpg','progress.json'}
