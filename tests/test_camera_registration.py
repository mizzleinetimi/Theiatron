import copy

import cv2
import numpy as np
import pytest

from theiatron.camera_registration import BackgroundRegistrar, register_camera, registration_at, transform_point
from scripts.registration_candidate import AdaptiveBackgroundRegistrar


def textured_frame():
    rng = np.random.default_rng(31)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for _ in range(2500):
        x, y = rng.integers([10, 10], [1270, 710])
        color = tuple(int(v) for v in rng.integers(35, 255, 3))
        cv2.circle(frame, (int(x), int(y)), int(rng.integers(2, 6)), color, -1)
    return frame


def test_stationary_registration():
    frame = textured_frame()
    result = BackgroundRegistrar(frame).register(frame)
    assert result["status"] == "accepted"
    assert result["inlier_fraction"] > .99
    assert np.allclose(result["H"], np.eye(3), atol=1e-5)


def test_perspective_registration_maps_current_back_to_reference():
    frame = textured_frame()
    source_to_current = np.array([[1.008, -.012, 22.], [.006, .995, -15.], [.000012, -.000009, 1.]])
    current = cv2.warpPerspective(frame, source_to_current, (1280, 720))
    # A foreground occluder is deliberately excluded in the current frame.
    current[330:550, 440:770] = (60, 230, 10)
    result = BackgroundRegistrar(frame).register(current, [[440, 330, 770, 550]])
    assert result["status"] == "accepted"
    for point in ([200, 180], [900, 160], [340, 600], [950, 550]):
        transformed = transform_point(source_to_current, point)
        assert np.linalg.norm(np.array(transform_point(result["H"], transformed)) - point) < 1.5


def test_no_feature_or_unrelated_frames_reject_without_identity_fallback():
    frame = textured_frame()
    blank = np.zeros_like(frame)
    assert BackgroundRegistrar(blank).register(frame)["H"] is None
    rejected = BackgroundRegistrar(frame).register(blank)
    assert rejected["status"] == "rejected" and rejected["H"] is None


def test_exact_registration_lookup_never_interpolates_failed_frames():
    identity = np.eye(3).tolist()
    result = {"frames": [dict(t=.1, H=identity, status="reference"),
                          dict(t=.2, H=None, status="rejected"),
                          dict(t=.3, H=identity, status="accepted")]}
    assert registration_at(result, .1)["H"] == identity
    assert registration_at(result, .2) is None
    assert registration_at(result, .25) is None
    assert registration_at(result, .3)["status"] == "accepted"
    assert transform_point(None, [3, 4]) is None
    assert transform_point([[1, 0, 0], [0, 1, 0], [0, 0, -1]], [3, 4]) is None


def test_adaptive_registration_matches_known_transform_without_reusing_previous_frames():
    frame=textured_frame();registrar=AdaptiveBackgroundRegistrar(frame)
    for dx,dy in [(4,8),(30,-12),(-14,19)]:
        known=np.array([[1.,0,dx],[0,1.,dy],[0,0,1.]])
        result=registrar.register(cv2.warpPerspective(frame,known,(1280,720)))
        assert result['status']=='accepted'
        for xy in [[200,180],[900,550]]:
            assert np.linalg.norm(np.array(transform_point(result['H'],transform_point(known,xy)))-xy)<1.5
    rejected=registrar.register(np.zeros_like(frame))
    assert rejected['status']=='rejected' and rejected['H'] is None
    assert rejected['search_mode']=='full-fallback'


@pytest.mark.parametrize('change',[{'status':'rejected','reason':'weak-background-consensus'},
    {'inliers':79},{'inlier_fraction':.64},{'background_coverage':.14},{'residual_px':{'p90':1.91}}])
def test_weak_fast_fit_retries_full_matcher_with_no_quality_relaxation(monkeypatch,change):
    registrar=AdaptiveBackgroundRegistrar(textured_frame())
    row={'status':'accepted','H':np.eye(3).tolist(),'inliers':120,'inlier_fraction':.9,
         'background_coverage':.4,'residual_px':{'p90':1.2}}
    monkeypatch.setattr(registrar.fast,'register',lambda *args:{**row,**change})
    calls=[]
    class Full:
        def register(self,*args):calls.append(True);return {'status':'rejected','H':None,'reason':'unchanged-gate'}
    monkeypatch.setattr(registrar,'_full',lambda:Full())
    result=registrar.register(textured_frame())
    assert calls==[True] and result['status']=='rejected' and result['H'] is None


def test_video_cadence_first_analysed_frame_and_immutability(tmp_path):
    path = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30., (1280, 720))
    if not writer.isOpened():
        pytest.skip("MJPG video encoder unavailable")
    frame = textured_frame()
    for index in range(12):
        # Native frames 0 and 1 must not become the reference.
        writer.write(np.zeros_like(frame) if index < 2 else frame)
    writer.release()
    dense = {"image_size": [1280, 720], "tracks": [{"samples": [
        {"t": .1, "box": [300, 300, 400, 400]},
        {"t": .2, "box": [305, 300, 405, 400]},
        {"t": .4, "box": [315, 300, 415, 400]},
    ]}]}
    original = copy.deepcopy(dense)
    result = register_camera(path, dense)
    assert result["reference_frame_index"] == 2
    assert result["reference_t"] == .1
    assert [r["frame_index"] for r in result["frames"]] == [2, 5, 8, 11]
    assert result["summary"]["accepted"] == 4
    assert result["summary"]["accuracy_validated"] is False
    assert dense == original
    dense["tracks"][0]["samples"][0]["t"] = .05
    with pytest.raises(ValueError, match="cadence"):
        register_camera(path, dense)
