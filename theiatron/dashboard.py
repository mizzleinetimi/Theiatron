"""Demo dashboard, designed for a non-technical audience.

Layout: 2x2 camera tiles (one per intersection approach), each with a
colored border and a plain-language banner ("NORTH - GREEN, clearing 3
cars"). The right panel shows a schematic top-down intersection with live
lights and queued-car icons, one headline comparison (average wait with
Theiatron vs an old fixed timer), and a one-line narration of what the AI
is doing right now and why.

All GUI calls must stay on the main thread (macOS requirement). The same
composited canvas is optionally written to an MP4 recording.
"""

from __future__ import annotations

import cv2
import numpy as np

TILE_W, TILE_H = 640, 360
PANEL_W = 420

LIGHT_COLORS = {
    "GREEN": (80, 200, 80),
    "YELLOW": (60, 200, 240),
    "RED": (70, 70, 230),
}
BG = (26, 24, 22)
FG = (235, 235, 235)
DIM = (150, 150, 150)
ACCENT = (200, 160, 60)
GOOD = (80, 220, 80)
ROAD = (58, 58, 58)

PHASE_LABEL = {"NS": "North-South", "EW": "East-West"}


def annotate_frame(frame, detections, extractor, flash_ids, light, name, waiting):
    """Camera tile: border + banner in plain language, boxes on vehicles."""
    out = frame.copy()
    h, w = out.shape[:2]
    # Counting line with a small label so viewers know what it is.
    p1 = tuple(map(int, extractor.p1))
    p2 = tuple(map(int, extractor.p2))
    cv2.line(out, p1, p2, (60, 60, 230), 3)
    lx, ly = min(p1[0], p2[0]), min(p1[1], p2[1])
    cv2.putText(out, "counting line", (lx + 8, max(24, ly - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 230), 2)
    initial = name[0].upper()
    for det in detections:
        x1, y1, x2, y2 = map(int, det.box)
        num = extractor.count_num.get(det.track_id)
        if det.track_id in flash_ids:
            cv2.rectangle(out, (x1, y1), (x2, y2), GOOD, 4)
        elif num is not None:
            cv2.rectangle(out, (x1, y1), (x2, y2), ACCENT, 2)
        else:
            cv2.rectangle(out, (x1, y1), (x2, y2), (255, 255, 255), 1)
        if num is not None:
            # Same tag the 3D replay shows on this car (e.g. N7).
            tag = f"{initial}{num}"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_DUPLEX, 0.9, 2)
            ty = max(th + 8, y1 - 6)
            cv2.rectangle(out, (x1, ty - th - 8), (x1 + tw + 12, ty + 6), (20, 20, 20), -1)
            cv2.putText(out, tag, (x1 + 6, ty),
                        cv2.FONT_HERSHEY_DUPLEX, 0.9,
                        GOOD if det.track_id in flash_ids else ACCENT, 2)
    # Banner strip: name + light + what it means.
    color = LIGHT_COLORS[light]
    if light == "GREEN":
        msg = "GREEN - traffic flowing"
    elif light == "YELLOW":
        msg = "YELLOW - about to change"
    else:
        msg = f"RED - {waiting} waiting" if waiting else "RED"
    cv2.rectangle(out, (0, 0), (w, 46), (20, 20, 20), -1)
    cv2.circle(out, (26, 23), 12, color, -1)
    cv2.circle(out, (26, 23), 12, (255, 255, 255), 1)
    cv2.putText(out, f"{name.upper()}  |  {msg}", (48, 32),
                cv2.FONT_HERSHEY_DUPLEX, 0.8, FG, 1)
    # Thick border in the light color ties tile to schematic.
    cv2.rectangle(out, (0, 0), (w - 1, h - 1), color, 8)
    return out


APPROACH_COLORS = {  # BGR, one distinct hue per approach for the shared view
    "north": (60, 60, 230),
    "south": (200, 60, 200),
    "east": (230, 200, 60),
    "west": (50, 200, 240),
}


def annotate_intersection(frame, detections, extractors, lights, waiting):
    """Single elevated view shared by several approaches: draw every
    approach's count line in its own color, tag counted cars, and show a
    compact per-approach status chip row."""
    out = frame.copy()
    h, w = out.shape[:2]
    for name, ex in extractors.items():
        color = APPROACH_COLORS.get(name, (200, 200, 200))
        p1, p2 = tuple(map(int, ex.p1)), tuple(map(int, ex.p2))
        cv2.line(out, p1, p2, color, 3)
        cv2.putText(out, name[0].upper(), (p1[0] + 6, p1[1] - 8),
                    cv2.FONT_HERSHEY_DUPLEX, 0.8, color, 2)
    flash = set().union(*(ex.last_counted for ex in extractors.values()))
    for det in detections:
        x1, y1, x2, y2 = map(int, det.box)
        owner, num = None, None
        for name, ex in extractors.items():
            if det.track_id in ex.count_num:
                owner, num = name, ex.count_num[det.track_id]
                break
        # Dark outline underneath makes every box pop on any background.
        cv2.rectangle(out, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), (0, 0, 0), 5)
        if det.track_id in flash:
            cv2.rectangle(out, (x1, y1), (x2, y2), GOOD, 4)
        elif owner:
            cv2.rectangle(out, (x1, y1), (x2, y2), APPROACH_COLORS[owner], 3)
        else:
            cv2.rectangle(out, (x1, y1), (x2, y2), (255, 255, 255), 2)
        if owner:
            tag = f"{owner[0].upper()}{num}"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_DUPLEX, 1.0, 2)
            ty = max(th + 8, y1 - 6)
            cv2.rectangle(out, (x1 - 2, ty - th - 8), (x1 + tw + 12, ty + 6), (10, 10, 10), -1)
            cv2.putText(out, tag, (x1 + 5, ty), cv2.FONT_HERSHEY_DUPLEX, 1.0,
                        GOOD if det.track_id in flash else APPROACH_COLORS[owner], 2)
    # Status chips across the top: light + waiting count per approach.
    cv2.rectangle(out, (0, 0), (w, 44), (20, 20, 20), -1)
    x = 14
    for name in extractors:
        color = LIGHT_COLORS[lights.get(name, "RED")]
        cv2.circle(out, (x + 10, 22), 10, color, -1)
        cv2.circle(out, (x + 10, 22), 10, (255, 255, 255), 1)
        label = f"{name.upper()} {waiting.get(name, 0)}"
        cv2.putText(out, label, (x + 28, 30), cv2.FONT_HERSHEY_DUPLEX, 0.7, FG, 1)
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.7, 1)
        x += 46 + tw
    return out


def _draw_intersection(panel, cx, cy, lights, waiting):
    """Top-down schematic: one crossing, four lights, queued-car icons."""
    arm = 128
    half = 30
    cv2.rectangle(panel, (cx - half, cy - arm), (cx + half, cy + arm), ROAD, -1)
    cv2.rectangle(panel, (cx - arm, cy - half), (cx + arm, cy + half), ROAD, -1)
    for k in range(3):  # lane dashes
        cv2.line(panel, (cx, cy - arm + 14 + k * 26), (cx, cy - arm + 26 + k * 26), DIM, 1)
        cv2.line(panel, (cx, cy + arm - 14 - k * 26), (cx, cy + arm - 26 - k * 26), DIM, 1)
        cv2.line(panel, (cx - arm + 14 + k * 26, cy), (cx - arm + 26 + k * 26, cy), DIM, 1)
        cv2.line(panel, (cx + arm - 14 - k * 26, cy), (cx + arm - 26 - k * 26, cy), DIM, 1)
    # Per-arm: light dot at the stop line, car icons queuing behind it.
    spots = {
        "north": ((cx - half - 14, cy - half - 14), (0, -1)),
        "south": ((cx + half + 14, cy + half + 14), (0, 1)),
        "east": ((cx + half + 14, cy - half - 14), (1, 0)),
        "west": ((cx - half - 14, cy + half + 14), (-1, 0)),
    }
    for name, ((lx, ly), (dx, dy)) in spots.items():
        color = LIGHT_COLORS[lights.get(name, "RED")]
        cv2.circle(panel, (lx, ly), 10, color, -1)
        cv2.circle(panel, (lx, ly), 10, (255, 255, 255), 1)
        n = min(waiting.get(name, 0), 6)
        for k in range(n):  # car icons stack away from the crossing
            ox = cx + dx * (half + 16 + k * 18) - 7
            oy = cy + dy * (half + 16 + k * 18) - 5
            cv2.rectangle(panel, (ox, oy), (ox + 14, oy + 10), (210, 210, 210), -1)
        total = waiting.get(name, 0)
        if total:
            # Count sits just past the last car icon, clear of the letters.
            tx = cx + dx * (half + 26 + n * 18) - 6
            ty = cy + dy * (half + 26 + n * 18) + 6
            cv2.putText(panel, str(total), (tx, ty),
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, ACCENT, 1)
    for lbl, (px, py) in (("N", (cx - 40, cy - arm - 6)), ("S", (cx + 34, cy + arm + 14)),
                          ("E", (cx + arm + 6, cy - 38)), ("W", (cx - arm - 18, cy + 44))):
        cv2.putText(panel, lbl, (px, py), cv2.FONT_HERSHEY_SIMPLEX, 0.6, DIM, 1)


def _draw_comparison(panel, y, stats):
    theia = stats.get("theia_wait")
    fixed = stats.get("fixed_wait")
    cv2.putText(panel, "AVERAGE WAIT PER CAR", (24, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, ACCENT, 1)
    y += 30
    scale_max = max(theia or 0, fixed or 0, 1.0)
    fixed_label = stats.get("fixed_label", "FIXED TIMER")
    for label, val, color in (("THEIATRON", theia, GOOD), (fixed_label, fixed, DIM)):
        txt = f"{label}  {val:.0f}s" if val is not None else f"{label}  --"
        cv2.putText(panel, txt, (24, y), cv2.FONT_HERSHEY_DUPLEX, 0.65, FG, 1)
        bar = int(250 * (val or 0) / scale_max)
        cv2.rectangle(panel, (24, y + 7), (24 + bar, y + 20), color, -1)
        y += 44
    comparison = stats.get("comparison", {})
    color = DIM
    if comparison.get("sample_status") == "ready":
        color = GOOD if comparison.get("outcome") == "better" else (
            (63, 74, 227) if comparison.get("outcome") == "worse" else DIM
        )
    cv2.putText(panel, comparison.get("headline", "measuring..."), (24, y + 6),
                cv2.FONT_HERSHEY_DUPLEX, 0.65, color, 1)
    y += 30
    a_waiting = stats.get("theia_waiting")
    f_waiting = stats.get("fixed_waiting")
    if a_waiting is not None and f_waiting is not None:
        cv2.putText(panel, f"WAITING NOW   {a_waiting} vs {f_waiting}", (24, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, FG, 1)
        y += 22
    saved = stats.get("time_saved_s")
    if saved is not None:
        color = GOOD if saved > 0 else DIM
        label = f"{saved:.0f} VEHICLE-SECONDS SAVED" if saved >= 0 else (
            f"{-saved:.0f} VEHICLE-SECONDS BEHIND"
        )
        cv2.putText(panel, label, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.56, color, 1)
    return y + 22


class Dashboard:
    def __init__(self, names, record_path=None, fps=10.0, show=True):
        self.names = names
        self.show = show
        self.canvas_w = TILE_W * 2 + PANEL_W
        self.canvas_h = TILE_H * 2
        self.writer = None
        if record_path:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(
                str(record_path), fourcc, fps, (self.canvas_w, self.canvas_h)
            )

    def _panel(self, lights, waiting, stats, narration):
        panel = np.full((self.canvas_h, PANEL_W, 3), BG, dtype=np.uint8)
        cv2.putText(panel, "THEIATRON", (24, 44), cv2.FONT_HERSHEY_DUPLEX, 1.1, ACCENT, 2)
        cv2.putText(panel, "traffic lights that see", (24, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, FG, 1)
        _draw_intersection(panel, PANEL_W // 2, 250, lights, waiting)
        _draw_comparison(panel, 450, stats)
        # Narration: what the AI is doing right now, in plain words.
        cv2.rectangle(panel, (16, self.canvas_h - 84), (PANEL_W - 16, self.canvas_h - 16),
                      (40, 38, 34), -1)
        lines = _wrap(narration, 36)[:2]
        ty = self.canvas_h - 58
        for line in lines:
            cv2.putText(panel, line, (28, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.55, FG, 1)
            ty += 26
        return panel

    def render(self, tile_frames, lights, waiting, stats, narration=""):
        """tile_frames: list of annotated frames, one per camera video.
        A single shared elevated view fills the whole grid area."""
        blank = lambda: np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
        if len(tile_frames) == 1 and tile_frames[0] is not None:
            grid = cv2.resize(tile_frames[0], (TILE_W * 2, TILE_H * 2))
        else:
            tiles = [blank() if f is None else cv2.resize(f, (TILE_W, TILE_H))
                     for f in tile_frames[:4]]
            while len(tiles) < 4:
                tiles.append(blank())
            grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:4])])
        panel = self._panel(lights, waiting, stats, narration)
        canvas = np.hstack([grid, panel])
        if self.writer is not None:
            self.writer.write(canvas)
        return canvas

    def display(self, canvas) -> bool:
        """Show the canvas; returns False when the user quits with 'q'."""
        if not self.show:
            return True
        cv2.imshow("Theiatron", canvas)
        return (cv2.waitKey(1) & 0xFF) != ord("q")

    def close(self):
        if self.writer is not None:
            self.writer.release()
        if self.show:
            cv2.destroyAllWindows()


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]
