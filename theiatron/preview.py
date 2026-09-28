"""Bounded latest-frame publishing; no growing queue or pretend live camera."""
import os
from pathlib import Path
import signal
import threading
import time
from .io import atomic_bytes, atomic_json


def parent_watchdog():
    """Stop this isolated worker group if its launcher exits, including SIGKILL."""
    parent = os.environ.get("THEIATRON_PARENT_PID")
    if not parent:
        return
    expected = int(parent)
    def watch():
        while True:
            time.sleep(1)
            if os.getppid() != expected:
                if os.getpgrp() == os.getpid():
                    os.killpg(os.getpid(), signal.SIGTERM)
                os._exit(1)
    threading.Thread(target=watch, daemon=True).start()


class PreviewPublisher:
    def __init__(self, directory: Path):
        self.directory = directory
        self.last = 0.0
        self.started = time.monotonic()

    def publish(self, frame, source_time, stage, **details):
        import cv2
        now = time.monotonic()
        if now - self.last < .33:
            return
        self.last = now
        h, w = frame.shape[:2]
        image = cv2.resize(frame, (960, round(h * 960 / w)))
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise RuntimeError("Cannot encode detection preview")
        atomic_bytes(self.directory / "preview.jpg", jpeg.tobytes())
        atomic_json(self.directory / "progress.json", {
            "mode": "file-analysed-now", "source_time_s": source_time, "stage": stage,
            "published_at": time.time(), "worker_elapsed_s": round(now - self.started, 2), **details,
        })
