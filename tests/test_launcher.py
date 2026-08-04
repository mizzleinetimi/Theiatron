from launcher_server import _new_run_id, _progress_for_line, _safe_filename


def test_safe_filename_removes_path_and_rejects_non_video():
    assert _safe_filename("../../My Junction.MOV") == "My Junction.mov"
    try:
        _safe_filename("notes.txt")
    except ValueError as exc:
        assert "video" in str(exc)
    else:
        raise AssertionError("non-video extension was accepted")


def test_run_id_is_safe_and_descriptive():
    run_id = _new_run_id("My Lagos Junction.mov", stamp="20260804-120000")
    assert run_id.startswith("ui-20260804-120000-my-lagos-junction-")
    assert all(ch.isalnum() or ch in "._-" for ch in run_id)


def test_progress_parser_tracks_real_pipeline_stages():
    assert _progress_for_line("stage 1/3: observing")[:2] == (8, "calibrating")
    assert _progress_for_line("stage 2/3: learned 4 approaches")[:2] == (38, "calibrated")
    assert _progress_for_line("stage 3/3: live detection")[:2] == (44, "analyzing")
    assert _progress_for_line("wrote out/demo/timeline.js: 20 vehicles")[:2] == (94, "building")
