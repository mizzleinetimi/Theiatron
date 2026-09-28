import json
import pytest

from theiatron.detection import Detection
from theiatron.perception_reuse import ObservationReuse


class Detector:
    def __init__(self): self.calls = []
    def track(self, frame):
        self.calls.append(frame)
        return [Detection(len(self.calls), 2, 4, (1, 1, 3, 4), 2, .9)]


def test_reuse_prefix_then_continue_same_tracker(tmp_path):
    detector = Detector()
    reuse = ObservationReuse(detector, tmp_path / 'observations.jsonl')
    first = [reuse.track(f) for f in (b'frame1', b'frame2')]
    reuse.rewind()
    assert [reuse.track(f) for f in (b'frame1', b'frame2')] == first
    assert reuse.track(b'frame3')[0].track_id == 3
    assert detector.calls == [b'frame1', b'frame2', b'frame3']
    stats = reuse.stats()
    assert stats['reused_ticks'] == 2 and stats['inference_ticks'] == 3
    reuse.close()
    assert len([json.loads(l) for l in (tmp_path / 'observations.jsonl').read_text().splitlines()]) == 3


def test_decoder_mismatch_fails_without_new_inference(tmp_path):
    detector = Detector()
    reuse = ObservationReuse(detector, tmp_path / 'observations.jsonl')
    reuse.track(b'frame1'); reuse.rewind()
    with pytest.raises(ValueError, match='decoded frame differs'):
        reuse.track(b'wrong frame')
    assert len(detector.calls) == 1
    reuse.close()


def test_short_recount_is_valid_and_cannot_rewind_twice_or_overwrite(tmp_path):
    path = tmp_path / 'observations.jsonl'
    reuse = ObservationReuse(Detector(), path)
    for f in (b'a', b'b', b'c'): reuse.track(f)
    reuse.rewind(); reuse.track(b'a')
    assert reuse.stats()['reused_ticks'] == 1
    with pytest.raises(ValueError, match='only be replayed once'): reuse.rewind()
    with pytest.raises(FileExistsError): ObservationReuse(Detector(), path)
    reuse.close()
