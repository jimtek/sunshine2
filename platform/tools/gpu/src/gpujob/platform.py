"""Read the platform config that the cluster was rendered from.

v1 reads config/platform.yaml (path from --platform or $GPU_PLATFORM_CONFIG).
A later version reads the same file from a ConfigMap in the cluster, so
researchers don't need the repo.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_REPO_DEFAULT = Path(__file__).resolve().parents[4] / "config" / "platform.yaml"
_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_MEM = re.compile(r"^(\d+)(Mi|Gi|Ti)$")


def default_path() -> Path:
    return Path(os.environ.get("GPU_PLATFORM_CONFIG", _REPO_DEFAULT))


def load(path: str | Path | None = None) -> dict[str, Any]:
    with open(path or default_path()) as fh:
        return yaml.safe_load(fh)


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
        raise ValueError(f"bad memory {value!r}")
    n, unit = int(m.group(1)), m.group(2)
    return {"Mi": n // 1024, "Gi": n, "Ti": n * 1024}[unit]


def nominal_gpus(cfg: dict, team: str, pool: str) -> int:
    """The team's guaranteed GPUs in a pool: whole nodes, same rule as `fleetops render`."""
    p = cfg["pools"][pool]
    teams = list(cfg["teams"])
    given = 0
    for i, t in enumerate(teams):
        n = p["nodes"] - given if i == len(teams) - 1 else round(p["nodes"] * cfg["teams"][t]["share"])
        given += n
        if t == team:
            return n * p["gpus_per_node"]
    raise KeyError(team)
