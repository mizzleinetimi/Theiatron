"""Configuration dataclasses and YAML loading for approaches/tunables."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml


@dataclass
class SignalConfig:
    """Signal timing constraints shared by every controller.

    All durations are in seconds of simulation (video) time.
    """

    min_green: float = 12.0
    max_green: float = 45.0
    yellow: float = 3.0
    all_red: float = 1.0
    # Fixed-timer baseline green split per phase.
    fixed_split: float = 30.0
    # Adaptive: pressure contribution per vehicle-second of accumulated wait.
    wait_weight: float = 0.05
    # Adaptive pre-emption: opposing pressure must exceed
    # active * pressure_ratio + hysteresis to cut short an active discharge.
    hysteresis: float = 10.0
    pressure_ratio: float = 1.5


@dataclass
class QueueConfig:
    lanes: int = 1
    # Saturation headway: one vehicle discharges per lane every `sat_headway`
    # seconds of effective green.
    sat_headway: float = 2.0
    # Dead time after green onset before discharge begins (driver reaction /
    # acceleration). Keeps the adaptive-vs-fixed comparison honest: frequent
    # switching pays this cost every cycle.
    startup_lost: float = 2.0


@dataclass
class ApproachConfig:
    """One camera feed watching one intersection approach."""

    name: str  # north / south / east / west
    video: str
    phase: str  # "NS" or "EW" — which signal phase serves this approach
    # Count line as [[x1, y1], [x2, y2]] in pixels of the (normalized) video.
    count_line: list = field(default_factory=list)
    # A point on the side of the line vehicles approach FROM (sets direction).
    approach_side: list = field(default_factory=list)
    # Optional ROI polygon [[x, y], ...] restricting which tracks count.
    roi: list | None = None
    lanes: int = 1


@dataclass
class VisionConfig:
    model: str = "yolo26n.pt"
    imgsz: int = 416
    conf: float = 0.3
    # COCO ids: car, motorcycle, bus, truck
    classes: tuple = (2, 3, 5, 7)
    # Effective processing cadence in frames per second of video time.
    process_fps: float = 10.0
    # Tracks younger than this many processed frames cannot register arrivals.
    min_track_age: int = 3
    device: str = "cpu"


@dataclass
class AppConfig:
    signal: SignalConfig = field(default_factory=SignalConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    approaches: list[ApproachConfig] = field(default_factory=list)


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    cfg = AppConfig()
    if "signal" in raw:
        cfg.signal = SignalConfig(**raw["signal"])
    if "queue" in raw:
        cfg.queue = QueueConfig(**raw["queue"])
    if "vision" in raw:
        vis = dict(raw["vision"])
        if "classes" in vis:
            vis["classes"] = tuple(vis["classes"])
        cfg.vision = VisionConfig(**vis)
    cfg.approaches = [ApproachConfig(**a) for a in raw.get("approaches", [])]
    return cfg


def save_config(cfg: AppConfig, path: str | Path) -> None:
    data = asdict(cfg)
    data["vision"]["classes"] = list(cfg.vision.classes)
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False))
