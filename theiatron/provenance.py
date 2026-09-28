"""Record what actually ran; fingerprints are not accuracy or licence claims."""
import hashlib
import importlib.metadata
import platform
from pathlib import Path
import sys


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def vision_provenance(model):
    root = Path(__file__).resolve().parents[1]
    packages = {}
    for name in ('ultralytics', 'torch', 'torchvision', 'numpy', 'opencv-python', 'lap', 'pyyaml'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'not-installed'
    return {'python': sys.version.split()[0], 'platform': platform.platform(), 'packages': packages,
            'model_sha256': file_hash(model),
            'code_sha256': {name: file_hash(root/name) for name in ('run_demo.py', 'theiatron/detection.py',
              'theiatron/approach.py', 'theiatron/autocal.py', 'theiatron/config.py', 'theiatron/engine.py',
              'theiatron/controller.py', 'theiatron/metrics.py', 'theiatron/sim.py', 'theiatron/recorded_tracks.py',
              'theiatron/feeds.py', 'theiatron/perception_reuse.py')}}
