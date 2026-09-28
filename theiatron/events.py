"""Record / replay of arrival event streams.

Recording the vision-derived arrivals to JSON makes the adaptive-vs-fixed
comparison deterministic and re-runnable without the vision stage — anyone
can replay the exact demand and reproduce the reported numbers.
"""

from __future__ import annotations

import json
from pathlib import Path


def save_events(events: list[tuple[float, str]], path: str | Path, meta: dict | None = None) -> None:
    payload = {
        "meta": meta or {},
        # JSON floats round-trip; rounding here moves arrivals across ticks.
        "events": [{"t": t, "approach": name} for t, name in sorted(events)],
    }
    Path(path).write_text(json.dumps(payload, indent=1, allow_nan=False))


def load_events(path: str | Path) -> tuple[list[tuple[float, str]], dict]:
    payload = json.loads(Path(path).read_text())
    events = [(e["t"], e["approach"]) for e in payload["events"]]
    return sorted(events), payload.get("meta", {})
