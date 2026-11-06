"""Check an inventory against the `revisit_if` triggers in the defaults.

Each check that fires means a planning default no longer holds and must be
revisited (and its section's status changed to `corrected`).
"""

from __future__ import annotations

from typing import Any


def check(cfg: dict[str, Any], inv: dict[str, Any]) -> list[str]:
    fired: list[str] = []
    fleet = cfg.get("fleet", {})
    total = inv.get("total_gpus", 0)
    gmax = fleet.get("gpus", {}).get("max")
    gmin = fleet.get("gpus", {}).get("min")
    if gmax and total > gmax:
        fired.append(f"fleet: {total} GPUs exceeds planned maximum {gmax}")
    if total > 2048:
        fired.append(f"fleet: {total} GPUs exceeds 2,048 — Capacity Block org limit becomes binding")
    if gmin and 0 < total < gmin:
        fired.append(f"fleet: {total} GPUs is below planned minimum {gmin} — resize the plan")

    regions = {row["region"] for row in inv.get("summary", [])}
    primary = fleet.get("primary_region")
    extra = sorted(regions - {primary} - set(fleet.get("secondary_regions", [])))
    if extra:
        fired.append(f"fleet: GPUs found outside the primary region: {', '.join(extra)}")

    families = {row["instance_type"].split(".")[0] for row in inv.get("summary", [])}
    planned = set(fleet.get("instance_families", []))
    if planned and families - planned:
        fired.append(f"fleet: unplanned instance families present: {', '.join(sorted(families - planned))}")

    limit = cfg.get("capacity_mix", {}).get("capacity_block_org_limit_instances")
    blocks = inv.get("active_capacity_block_instances", 0)
    if limit and blocks >= 0.8 * limit:
        fired.append(f"capacity_mix: {blocks} Capacity Block instances is >= 80% of the {limit} org limit")

    idle = inv.get("idle_reserved_gpus", 0)
    if total and idle / max(total, 1) > 0.15:
        fired.append(f"capacity_mix: {idle} reserved GPUs idle (>15% of fleet) — blocks sitting idle")

    if inv.get("unknown_accelerated_types"):
        fired.append("inventory: unknown accelerated instance types — add them to gpus.py: "
                     + ", ".join(sorted(inv["unknown_accelerated_types"])))
    return fired
