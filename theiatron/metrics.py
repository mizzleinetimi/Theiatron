"""Wait-time metrics and the adaptive-vs-fixed comparison report."""

from __future__ import annotations

import json
from pathlib import Path

from .engine import IntersectionEngine

MIN_COMPARISON_ARRIVALS = 10


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile; avoids a hard numpy dependency here."""
    if not values:
        return 0.0
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    rank = (pct / 100.0) * (len(vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(vals) - 1)
    frac = rank - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def total_censored_wait(engine: IntersectionEngine, end_time: float) -> float:
    """Total vehicle-seconds accumulated through ``end_time``.

    Departed vehicles contribute their completed queue wait; vehicles still
    queued contribute their wait so far. Comparing this value between shadow
    controllers gives an intuitive live "vehicle-seconds saved" counter.
    """
    total = 0.0
    for q in engine.queues.values():
        total += sum(v.wait() for v in q.departed)
        total += sum(v.wait(end_time) for v in q.queue)
    return total


def summarize(engine: IntersectionEngine, end_time: float) -> dict:
    """Metrics for one engine run.

    Vehicles still queued at end_time are included with their censored wait
    (end_time - arrival) so a controller cannot look good by stranding cars.
    """
    per_approach: dict[str, dict] = {}
    all_waits: list[float] = []
    total_departed = 0
    total_arrivals = 0
    for name, q in engine.queues.items():
        waits = [v.wait() for v in q.departed]
        waits += [v.wait(end_time) for v in q.queue]
        all_waits.extend(waits)
        total_departed += len(q.departed)
        total_arrivals += q.arrivals_total
        per_approach[name] = {
            "arrivals": q.arrivals_total,
            "served": len(q.departed),
            "still_queued": len(q.queue),
            "avg_wait_s": round(sum(waits) / len(waits), 2) if waits else 0.0,
            "p95_wait_s": round(_percentile(waits, 95), 2),
            "max_queue": q.max_queue,
        }
    return {
        "controller": engine.controller.name,
        "duration_s": round(end_time, 1),
        "arrivals": total_arrivals,
        "served": total_departed,
        "avg_wait_s": round(sum(all_waits) / len(all_waits), 2) if all_waits else 0.0,
        "p95_wait_s": round(_percentile(all_waits, 95), 2),
        "max_wait_s": round(max(all_waits), 2) if all_waits else 0.0,
        "phase_switches": engine.sm.switches,
        "per_approach": per_approach,
    }


def comparison_report(adaptive: dict, fixed: dict) -> tuple[str, dict]:
    """Markdown + JSON comparison of two summaries on identical demand."""

    def _reduction(metric: str) -> float:
        base = fixed[metric]
        return round(100.0 * (base - adaptive[metric]) / base, 1) if base else 0.0

    data = {
        "adaptive": adaptive,
        "fixed": fixed,
        "avg_wait_reduction_pct": _reduction("avg_wait_s"),
        "p95_wait_reduction_pct": _reduction("p95_wait_s"),
        "sample_status": (
            "ready" if adaptive["arrivals"] >= MIN_COMPARISON_ARRIVALS
            else "inconclusive"
        ),
    }

    def _change(reduction: float) -> str:
        # The table expresses change in the adaptive value relative to fixed,
        # so a positive reduction is displayed as a negative change. Avoid the
        # distracting "-0.0%" result on empty or identical samples.
        return "0.0%" if reduction == 0 else f"{-reduction:+.1f}%"

    lines = [
        "# Theiatron — Adaptive vs Fixed-Timer Comparison",
        "",
        "Both controllers were run on the **identical** vision-derived arrival",
        "stream; the only difference is the signal control policy.",
        "",
    ]
    if data["sample_status"] == "inconclusive":
        lines += [
            f"**Inconclusive sample:** only {adaptive['arrivals']} arrivals were counted; ",
            f"at least {MIN_COMPARISON_ARRIVALS} are required before presenting a comparison.",
            "",
        ]
    lines += [
        "| Metric | Fixed timer | Theiatron adaptive | Change |",
        "|---|---|---|---|",
        f"| Average wait | {fixed['avg_wait_s']} s | {adaptive['avg_wait_s']} s |"
        f" **{_change(data['avg_wait_reduction_pct'])}** |",
        f"| 95th percentile wait | {fixed['p95_wait_s']} s | {adaptive['p95_wait_s']} s |"
        f" **{_change(data['p95_wait_reduction_pct'])}** |",
        f"| Worst single wait | {fixed['max_wait_s']} s | {adaptive['max_wait_s']} s | |",
        f"| Vehicles served | {fixed['served']} | {adaptive['served']} | |",
        f"| Phase switches | {fixed['phase_switches']} | {adaptive['phase_switches']} | |",
        "",
        "## Per-approach average wait (s)",
        "",
        "| Approach | Fixed | Adaptive |",
        "|---|---|---|",
    ]
    for name in adaptive["per_approach"]:
        f_a = fixed["per_approach"][name]
        a_a = adaptive["per_approach"][name]
        lines.append(f"| {name} | {f_a['avg_wait_s']} | {a_a['avg_wait_s']} |")
    lines += [
        "",
        "*Demand is real (vehicles detected and tracked in real traffic video);",
        "queue discharge is simulated (recorded vehicles cannot react to our",
        "light). Identical arrivals for both controllers isolate the policy.*",
        "",
    ]
    return "\n".join(lines), data


def write_report(markdown: str, data: dict, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "report.md"
    json_path = out / "report.json"
    md_path.write_text(markdown)
    json_path.write_text(json.dumps(data, indent=2))
    return md_path, json_path
