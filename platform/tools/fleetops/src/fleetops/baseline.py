"""Baseline report: measured Phase 0 values against the proposed targets.

Input is a small YAML/JSON file of measurements keyed like `targets` in
fleet-defaults.yaml. Missing metrics are reported as not yet measured, which
is itself a Phase 0 finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Row:
    metric: str
    desc: str
    unit: str
    baseline: float | None
    target: float | None
    status: str  # meets | misses | not-measured


def evaluate(targets: dict[str, dict[str, Any]], measured: dict[str, float]) -> list[Row]:
    rows = []
    for key, t in targets.items():
        value = measured.get(key)
        target = t.get("target")
        if target is None and "relative_reduction" in t and value is not None:
            # Target is relative to the baseline itself, e.g. -50% in 6 months.
            target = round(value * (1 - t["relative_reduction"]), 4)
        if value is None:
            status = "not-measured"
        elif target is None:
            status = "not-measured"
        elif t["direction"] == "higher":
            status = "meets" if value >= target else "misses"
        else:
            status = "meets" if value <= target else "misses"
        if "relative_reduction" in t and value is not None:
            status = "baseline-set"
        rows.append(Row(key, t.get("desc", ""), t.get("unit", ""), value, target, status))
    return rows


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "ratio":
        return f"{v:.0%}"
    return f"{v:g} {unit}"


def to_markdown(rows: list[Row], title: str = "Phase 0 baseline") -> str:
    lines = [
        f"# {title}", "",
        "| Metric | Baseline | Target | Status |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r.desc} | {_fmt(r.baseline, r.unit)} | {_fmt(r.target, r.unit)} | {r.status} |")
    missing = [r.metric for r in rows if r.status == "not-measured"]
    lines.append("")
    if missing:
        lines.append("Not yet measured: " + ", ".join(missing) + ".")
    else:
        lines.append("All metrics measured.")
    return "\n".join(lines) + "\n"
