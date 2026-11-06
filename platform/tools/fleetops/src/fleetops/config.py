"""Load and sanity-check the Phase 0 defaults file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

VALID_STATUS = {"assumed", "confirmed", "corrected"}
REQUIRED_SECTIONS = [
    "fleet", "accounts", "capacity_mix", "workload_mix", "checkpointing",
    "staffing", "shared_services", "partner_isolation", "targets",
]


def load(path: str | Path) -> dict[str, Any]:
    with open(path) as fh:
        return yaml.safe_load(fh)


def validate(cfg: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty means the file is usable."""
    problems: list[str] = []
    for name in REQUIRED_SECTIONS:
        if name not in cfg:
            problems.append(f"missing section: {name}")
    for name, section in cfg.items():
        if isinstance(section, dict) and "status" in section:
            if section["status"] not in VALID_STATUS:
                problems.append(f"{name}.status must be one of {sorted(VALID_STATUS)}")
            if section["status"] == "assumed" and name != "accounts" and "revisit_if" not in section \
                    and "decision_record" not in section:
                problems.append(f"{name}: assumed defaults need a revisit_if trigger")
    for key, t in (cfg.get("targets") or {}).items():
        if t.get("direction") not in ("higher", "lower"):
            problems.append(f"targets.{key}.direction must be higher or lower")
        if t.get("target") is None and "relative_reduction" not in t:
            problems.append(f"targets.{key} needs target or relative_reduction")
    fleet = cfg.get("fleet", {})
    gpus = fleet.get("gpus", {})
    if gpus and gpus.get("min", 0) > gpus.get("max", 0):
        problems.append("fleet.gpus.min is greater than fleet.gpus.max")
    return problems


def open_assumptions(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Sections still at 'assumed', with the trigger that would change them."""
    out = []
    for name, section in cfg.items():
        if isinstance(section, dict) and section.get("status") == "assumed":
            out.append((name, section.get("revisit_if", "see decision record")))
    return out
