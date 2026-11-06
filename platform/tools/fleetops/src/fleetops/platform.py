"""Load the Phase 1 platform config (config/platform.yaml) and derive quotas."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_MEM = re.compile(r"^(\d+)(Gi|Mi|Ti)$")

RESOURCES = ["cpu", "memory", "nvidia.com/gpu", "vpc.amazonaws.com/efa"]


def seconds(value: str | int) -> int:
    if isinstance(value, int):
        return value
    m = _DURATION.match(str(value).strip())
    if not m:
        raise ValueError(f"bad duration {value!r}; use e.g. 30m, 8h, 2d")
    return int(m.group(1)) * _UNIT[m.group(2)]


def mem_gi(value: str) -> int:
    m = _MEM.match(value)
    if not m:
        raise ValueError(f"bad memory {value!r}; use e.g. 1900Gi")
    n, unit = int(m.group(1)), m.group(2)
    return {"Mi": n // 1024, "Gi": n, "Ti": n * 1024}[unit]


def load(path: str | Path) -> dict[str, Any]:
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    problems = validate(cfg)
    if problems:
        raise ValueError("invalid platform config:\n  " + "\n  ".join(problems))
    return cfg


def validate(cfg: dict[str, Any]) -> list[str]:
    problems = []
    for key in ("kueue_version", "cohort", "pools", "teams", "priorities", "default_priority"):
        if key not in cfg:
            problems.append(f"missing {key}")
    if problems:
        return problems
    total_share = sum(t["share"] for t in cfg["teams"].values())
    if abs(total_share - 1.0) > 0.001:
        problems.append(f"team shares sum to {total_share:.4f}, expected 1.0")
    if cfg["default_priority"] not in cfg["priorities"]:
        problems.append("default_priority is not a defined priority")
    for name, pool in cfg["pools"].items():
        for f in ("instance_type", "gpus_per_node", "efa_per_node", "cpu_per_node", "memory_per_node", "nodes"):
            if f not in pool:
                problems.append(f"pools.{name}.{f} missing")
        if "ends_at" in pool and "drain_before_end" not in pool:
            problems.append(f"pools.{name}: ends_at requires drain_before_end")
    return problems


def pool_totals(pool: dict[str, Any]) -> dict[str, int]:
    n = pool["nodes"]
    return {
        "cpu": pool["cpu_per_node"] * n,
        "memory": mem_gi(pool["memory_per_node"]) * n,
        "nvidia.com/gpu": pool["gpus_per_node"] * n,
        "vpc.amazonaws.com/efa": pool["efa_per_node"] * n,
    }


def team_nodes(cfg: dict[str, Any], pool: str) -> dict[str, int]:
    """Whole nodes of a pool guaranteed to each team. Quotas are set in whole
    nodes so a team can always fill its own nodes (rounding per resource can
    leave a team a few GiB short of its last node). Remainder goes to the last team."""
    teams = list(cfg["teams"])
    total = cfg["pools"][pool]["nodes"]
    out, given = {}, 0
    for i, team in enumerate(teams):
        n = total - given if i == len(teams) - 1 else round(total * cfg["teams"][team]["share"])
        out[team] = n
        given += n
    return out


def team_quotas(cfg: dict[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    """team -> pool -> resource -> nominal quota; sums exactly to each pool."""
    out: dict[str, dict[str, dict[str, int]]] = {t: {} for t in cfg["teams"]}
    for pname, pool in cfg["pools"].items():
        per_node = {r: v // pool["nodes"] for r, v in pool_totals(pool).items()}
        for team, n in team_nodes(cfg, pname).items():
            out[team][pname] = {r: v * n for r, v in per_node.items()}
    return out
