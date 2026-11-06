"""Preflight checks: catch problems before a job queues, not hours into it.

Covers quota, image and driver compatibility, data path access, checkpoint
location, requested topology, and job length against Capacity Block expiry.
Errors block submission; warnings are printed and the job goes ahead.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import platform as pf
from .spec import JobSpec

DNS1035 = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")
LABEL_VALUE = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")
CUDA_IN_TAG = re.compile(r"cuda[-_]?(\d+)\.(\d+)", re.I)
# NGC framework containers are tagged YY.MM; map to their CUDA version.
NGC_CUDA = {"24.01": "12.3", "24.04": "12.4", "24.07": "12.5", "24.10": "12.6",
            "25.01": "12.8", "25.04": "12.9", "25.06": "12.9"}


@dataclass
class Finding:
    level: str   # error | warn
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.code:11} {self.message}"


@dataclass
class Placement:
    pools: list[str]              # pools the job may land in
    nodes: int
    gpus_per_node: int
    avoid: list[str] = field(default_factory=list)  # pools excluded for timing reasons
    cpu: int = 0
    memory_gi: int = 0
    efa: int = 0


@dataclass
class Result:
    findings: list[Finding]
    placement: Placement | None
    priority: str

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings)


def _cuda_of(spec: JobSpec) -> str | None:
    if spec.cuda:
        return spec.cuda
    m = CUDA_IN_TAG.search(spec.image)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    if spec.image.startswith("nvcr.io/nvidia/") and ":" in spec.image:
        tag = spec.image.rsplit(":", 1)[1]
        return NGC_CUDA.get(tag[:5])
    return None


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run(spec: JobSpec, cfg: dict, now: datetime | None = None) -> Result:
    now = now or datetime.now(timezone.utc)
    f: list[Finding] = []
    err = lambda code, msg: f.append(Finding("error", code, msg))  # noqa: E731
    warn = lambda code, msg: f.append(Finding("warn", code, msg))  # noqa: E731

    # --- identity and labels ------------------------------------------------
    if not DNS1035.match(spec.name) or len(spec.name) > 50:
        err("NAME", "name must be lowercase letters, digits and '-', start with a letter, max 50 chars")
    if spec.team not in cfg["teams"]:
        err("TEAM", f"unknown team {spec.team!r}; known: {', '.join(cfg['teams'])}")
    for key, value in (("project", spec.project), ("experiment", spec.experiment)):
        if not value or len(value) > 63 or not LABEL_VALUE.match(value):
            err("LABELS", f"{key} must be 1-63 chars of letters, digits, '-', '_' or '.'")

    priority = spec.priority or cfg["default_priority"]
    if priority not in cfg["priorities"]:
        err("PRIORITY", f"unknown priority {priority!r}; known: {', '.join(cfg['priorities'])}")
    if priority == "preemptible" and not (spec.resume_tested and spec.checkpoint_dir):
        err("PREEMPT", "preemptible jobs need checkpoint_dir and resume_tested: true (pass a resume test first)")

    # --- runtime --------------------------------------------------------------
    try:
        runtime = pf.seconds(spec.max_runtime)
    except ValueError as exc:
        err("RUNTIME", str(exc))
        runtime = 0
    limit = pf.seconds(cfg["jobs"]["max_runtime"])
    if runtime > limit:
        err("RUNTIME", f"max_runtime {spec.max_runtime} exceeds the platform limit {cfg['jobs']['max_runtime']}; "
                       "checkpoint and chain jobs instead")

    # --- topology and pool selection -----------------------------------------
    placement = None
    if spec.gpus < 1:
        err("TOPOLOGY", "gpus must be at least 1")
    else:
        placement = _place(spec, cfg, runtime, now, err, warn)

    # --- quota ----------------------------------------------------------------
    if placement and spec.team in cfg["teams"]:
        guaranteed = max(pf.nominal_gpus(cfg, spec.team, p) for p in placement.pools)
        if spec.gpus > guaranteed:
            warn("QUOTA", f"{spec.gpus} GPUs is above {spec.team}'s guaranteed {guaranteed} in "
                          f"{'/'.join(placement.pools)}; it will run on borrowed quota and other teams can reclaim it")

    # --- checkpointing ----------------------------------------------------------
    # Dev-pool work is interactive and short (the pool caps runtime), so it
    # doesn't need a checkpoint location.
    dev_only = bool(placement) and all("max_runtime" in cfg["pools"][p] for p in placement.pools)
    ck = cfg["data"]["checkpoint_prefixes"]
    if spec.checkpoint_dir:
        if not any(spec.checkpoint_dir.startswith(p) for p in ck):
            err("CHECKPOINT", f"checkpoint_dir must start with one of {', '.join(ck)}")
        if spec.experiment and spec.experiment not in spec.checkpoint_dir:
            warn("CHECKPOINT", "checkpoint_dir doesn't contain the experiment id; runs may overwrite each other")
    elif runtime > pf.seconds(cfg["jobs"]["checkpoint_required_over"]) and not dev_only:
        err("CHECKPOINT", f"jobs longer than {cfg['jobs']['checkpoint_required_over']} must set checkpoint_dir "
                          "so they can resume after preemption or hardware failure")

    # --- image ------------------------------------------------------------------
    if not any(fnmatch.fnmatch(spec.image, pat + "*") for pat in cfg["images"]["allowed_registries"]):
        err("IMAGE", f"image registry not allowed; use one of {', '.join(cfg['images']['allowed_registries'])}")
    tag = spec.image.rsplit(":", 1)[1] if ":" in spec.image.rsplit("/", 1)[-1] else ""
    if "@sha256:" not in spec.image and tag in ("", "latest"):
        err("IMAGE", "pin the image to a tag or digest, not latest")
    cuda = _cuda_of(spec)
    if placement:
        driver_max = min(_ver(cfg["pools"][p]["driver_cuda_max"]) for p in placement.pools)
        if cuda is None:
            warn("DRIVER", "couldn't tell the image's CUDA version; set `cuda:` in the spec to check driver compatibility")
        elif _ver(cuda) > driver_max:
            err("DRIVER", f"image needs CUDA {cuda} but the node driver supports up to "
                          f"{'.'.join(map(str, driver_max))}")

    # --- data ----------------------------------------------------------------------
    for path in spec.data:
        if not any(path.startswith(p) for p in cfg["data"]["allowed_prefixes"]):
            err("DATA", f"{path}: data must live under {', '.join(cfg['data']['allowed_prefixes'])}")

    return Result(f, placement, priority)


def _place(spec, cfg, runtime, now, err, warn) -> Placement | None:
    pools = cfg["pools"]
    if spec.pool:
        if spec.pool not in pools:
            err("TOPOLOGY", f"unknown pool {spec.pool!r}; known: {', '.join(pools)}")
            return None
        candidates = [spec.pool]
    else:
        # Jobs that fit one dev node (size and runtime) go to the dev pool.
        # Anything else runs on the big pools: up to 7 GPUs share one node,
        # more must fill whole nodes.
        big = [p for p, c in pools.items() if "max_runtime" not in c]
        small = [p for p, c in pools.items() if "max_runtime" in c]
        candidates = [p for p in small if spec.gpus <= pools[p]["gpus_per_node"]
                      and runtime <= pf.seconds(pools[p]["max_runtime"])]
        if not candidates:
            candidates = [p for p in big if spec.gpus < pools[p]["gpus_per_node"]
                          or spec.gpus % pools[p]["gpus_per_node"] == 0]
    fitting = []
    for p in candidates:
        c = pools[p]
        gpn = c["gpus_per_node"]
        if spec.gpus % gpn:
            if spec.gpus > gpn:
                err("TOPOLOGY", f"multi-node jobs must use whole nodes: gpus must be a multiple of {gpn} in pool {p}")
                continue
        if spec.gpus > gpn * c["nodes"]:
            err("TOPOLOGY", f"{spec.gpus} GPUs is more than pool {p} has ({gpn * c['nodes']})")
            continue
        if "max_runtime" in c and runtime > pf.seconds(c["max_runtime"]):
            err("RUNTIME", f"pool {p} is for interactive/dev work, max_runtime {c['max_runtime']}")
            continue
        fitting.append(p)
    if not candidates:
        gpn = max(c["gpus_per_node"] for c in pools.values())
        err("TOPOLOGY", f"no pool fits {spec.gpus} GPUs; use 1-{gpn} GPUs on one node, or a multiple of {gpn}")
        return None

    avoid = []
    for p in list(fitting):
        c = pools[p]
        if "ends_at" not in c:
            continue
        deadline = _parse_time(c["ends_at"]) - timedelta(seconds=pf.seconds(c["drain_before_end"]))
        left = (deadline - now).total_seconds()
        if runtime > left:
            hours = max(left, 0) / 3600
            if spec.pool == p:
                err("CAPACITY", f"pool {p} drains in {hours:.1f}h, before this job's {spec.max_runtime} could finish")
            elif len(fitting) > 1:
                warn("CAPACITY", f"pool {p} drains in {hours:.1f}h; this job will avoid it")
            else:
                err("CAPACITY", f"the only pool that fits drains in {hours:.1f}h, before {spec.max_runtime} elapses")
            fitting.remove(p)
            avoid.append(p)
    if not fitting:
        return None

    gpn = min(pools[p]["gpus_per_node"] for p in fitting)
    per_node = min(spec.gpus, gpn)
    nodes = max(1, spec.gpus // gpn)
    frac = per_node / gpn
    cpu = min(int(pools[p]["cpu_per_node"] * frac) for p in fitting)
    mem = min(int(pf.mem_gi(pools[p]["memory_per_node"]) * frac) for p in fitting)
    efa = min(pools[p]["efa_per_node"] for p in fitting) if nodes > 1 else 0
    return Placement(fitting, nodes, per_node, avoid, cpu, mem, efa)
