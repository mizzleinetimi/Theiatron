#!/usr/bin/env python3
"""Read-only readiness report for the local workbench. Does not download models."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from theiatron.provenance import file_hash
from theiatron.sumo_demo import preflight


def main():
    files = ['yolo26n.pt', 'viz/vendor/three.min.js', 'workbench/index.html', 'workbench/app.js',
             'workbench/view.js', 'workbench/profiles.js', 'workbench/counting.js', 'workbench/style.css',
             'viz/vendor/OrbitControls.js', 'workbench/replay.html', 'workbench/replay.css',
             'workbench/replay.js', 'workbench/replay-math.js', 'workbench/traffic-scene.js',
             'workbench/demo.html','workbench/demo.css','workbench/demo.js','workbench/demo-math.js','workbench/demo-scene.js',
             'workbench/live.html','workbench/live.css','workbench/live.js','workbench/live-math.js',
             'workbench/live-scene.js','workbench/live-scene-math.js','workbench/live-upload.js',
             'workbench/showcase.html','workbench/showcase.css','workbench/showcase.js','workbench/showcase-math.js',
             'workbench/presentation-mode.css','workbench/presentation-mode.js']
    assets = {name: {'present': (ROOT/name).is_file(),
                     'sha256': file_hash(ROOT/name) if (ROOT/name).is_file() else None} for name in files}
    packages = {}
    for name in ('ultralytics', 'torch', 'opencv-python', 'numpy', 'lap', 'pyyaml'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    result = {'sumo': preflight(), 'assets': assets, 'vision_packages': packages,
              'ffmpeg': shutil.which('ffmpeg'), 'python': sys.version.split()[0],
              'scope': 'Readiness only; no inference-throughput, empirical-accuracy or Pi claim'}
    print(json.dumps(result, indent=2))
    return 0 if result['sumo']['ready'] and all(v['present'] for v in assets.values()) and all(packages.values()) and result['ffmpeg'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
