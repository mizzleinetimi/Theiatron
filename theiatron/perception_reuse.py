"""Bounded-memory, same-run reuse of observations used to learn count lines.

The source is decoded again for overlays, but the detector/tracker sees each
sampled frame only once. Once the retained prefix is exhausted, its original
tracker continues on the next frame. This is not a held-out evaluation and never
loads detections from another run. Pixel hashes fail closed on decoder mismatch.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from .detection import Detection


class ObservationReuse:
    def __init__(self, detector, path):
        self.detector = detector
        self.path = Path(path)
        self.stream = self.path.open('x+', encoding='utf-8')
        self.inference_ticks = self.reused_ticks = self.remaining = 0
        self.inference_wall_s = 0.
        self.rewound = False

    def rewind(self):
        if self.rewound:
            raise ValueError('observations may only be replayed once')
        self.stream.flush()
        self.stream.seek(0)
        self.remaining = self.inference_ticks
        self.rewound = True

    def track(self, frame):
        frame_hash = hashlib.sha256(memoryview(frame)).hexdigest()
        if self.remaining:
            packet = json.loads(self.stream.readline())
            if packet['index'] != self.reused_ticks or packet['frame_sha256'] != frame_hash:
                raise ValueError('decoded frame differs from its retained observation; run a fresh pass')
            detections = [Detection(**{**d, 'box': tuple(d['box'])}) for d in packet['detections']]
            self.remaining -= 1
            self.reused_ticks += 1
            if not self.remaining:
                self.stream.seek(0, 2)
            return detections
        start = time.perf_counter()
        detections = self.detector.track(frame)
        self.inference_wall_s += time.perf_counter() - start
        self.stream.write(json.dumps({'index': self.inference_ticks,
                                     'frame_sha256': frame_hash,
                                     'detections': [asdict(d) for d in detections]}, allow_nan=False) + '\n')
        self.inference_ticks += 1
        return detections

    def stats(self):
        self.stream.flush()
        return {'mode': 'single-inference-pass-recounted',
                'inference_ticks': self.inference_ticks, 'reused_ticks': self.reused_ticks,
                'detector_wall_s': round(self.inference_wall_s, 3),
                'detector_ticks_per_wall_second': round(self.inference_ticks / max(self.inference_wall_s, 1e-9), 2),
                'observations_file': self.path.name}

    def close(self):
        self.stream.close()
