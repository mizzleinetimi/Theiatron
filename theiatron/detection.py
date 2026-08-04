"""Nano-detector + tracker wrapper, one instance per camera feed.

IMPORTANT: ultralytics keeps ByteTrack state on the model's predictor, so
feeds must NOT share a YOLO instance — interleaving frames from different
cameras through one tracker silently corrupts track IDs. Each VehicleDetector
owns its own model instance (nano weights are ~6 MB; four copies are cheap).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import VisionConfig


@dataclass
class Detection:
    track_id: int
    x: float  # bottom-center: closest point to the road plane
    y: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2
    cls: int
    conf: float


class VehicleDetector:
    def __init__(self, cfg: VisionConfig, model: str | None = None, device: str | None = None):
        from ultralytics import YOLO  # deferred: core logic stays importable without ML deps

        self.cfg = cfg
        self.model_name = model or cfg.model
        self.device = device or cfg.device
        self.model = YOLO(self.model_name)

    def track(self, frame) -> list[Detection]:
        results = self.model.track(
            frame,
            persist=True,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            classes=list(self.cfg.classes),
            tracker="bytetrack.yaml",
            device=self.device,
            verbose=False,
        )
        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            return []
        out = []
        ids = boxes.id.int().tolist()
        xyxy = boxes.xyxy.tolist()
        clss = boxes.cls.int().tolist()
        confs = boxes.conf.tolist()
        for tid, (x1, y1, x2, y2), cls, conf in zip(ids, xyxy, clss, confs):
            out.append(
                Detection(
                    track_id=tid,
                    x=(x1 + x2) / 2.0,
                    y=y2,
                    box=(x1, y1, x2, y2),
                    cls=cls,
                    conf=conf,
                )
            )
        return _dedupe(out)

    def reset(self) -> None:
        """Drop tracker state (video loop wraparound)."""
        self.model.predictor = None


def _iou(a: tuple, b: tuple) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _dedupe(dets: list[Detection], iou_thr: float = 0.7) -> list[Detection]:
    """Class-agnostic suppression: one physical vehicle sometimes yields two
    boxes under different classes (car + truck); two tracks would then cross
    the count line and double-count one arrival."""
    kept: list[Detection] = []
    for det in sorted(dets, key=lambda d: d.conf, reverse=True):
        if all(_iou(det.box, k.box) < iou_thr for k in kept):
            kept.append(det)
    return kept
