"""Replay a job trace against the simulation cluster and measure scheduling.

This is the Phase 1 pilot test: replay a real week of jobs (or a synthetic
one, until Phase 0 provides real logs) on kind + KWOK, at accelerated time,
and measure gang placement, queue wait, preemption and allocation. The result
feeds the scheduler decision record (docs/decisions/0004).

Trace CSV columns: id, submit_s, team, gpus, runtime_s, priority
(times in simulated seconds from the start of the trace).
"""

from __future__ import annotations

import csv
import io
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import manifest, preflight
from .spec import JobSpec

SIM_IMAGE = "public.ecr.aws/docker/library/busybox:1.36"

# ADR 0004 pass criteria (defaults agreed before running). Override with
# `gpu replay --criteria FILE.yaml` if a different set is agreed.
CRITERIA = {
    "partial_placements_max": 0,
    "p90_wait_standard_h_max": 4.0,
    "allocation_ratio_busy_min": 0.85,
    "never_admitted_max": 0,
    "nonpreemptible_borrow_evictions_max": 0,
}
# Kueue Preempted-condition reason for a borrower preempting a workload.
BORROW_PREEMPTION_REASONS = {"InCohortReclaimWhileBorrowing"}


@dataclass
class TraceJob:
    id: str
    submit_s: float
    team: str
    gpus: int
    runtime_s: float
    priority: str


def read_trace(text: str) -> list[TraceJob]:
    rows = csv.DictReader(io.StringIO(text))
    return sorted((TraceJob(r["id"], float(r["submit_s"]), r["team"], int(r["gpus"]),
                            float(r["runtime_s"]), r["priority"]) for r in rows), key=lambda j: j.submit_s)


def write_trace(jobs: Iterable[TraceJob]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "submit_s", "team", "gpus", "runtime_s", "priority"])
    for j in jobs:
        w.writerow([j.id, f"{j.submit_s:.0f}", j.team, j.gpus, f"{j.runtime_s:.0f}", j.priority])
    return buf.getvalue()


def synthetic(cfg: dict, jobs: int = 300, days: float = 7, seed: int = 1,
              interactive_share: float = 0.2) -> list[TraceJob]:
    """A week shaped like the Phase 0 defaults: ~80% multi-node batch
    training, ~20% single-GPU dev work, Poisson arrivals, long-tailed runtimes."""
    rng = random.Random(seed)
    teams = list(cfg["teams"])
    horizon = days * 86400
    out = []
    t = 0.0
    for i in range(jobs):
        t += rng.expovariate(jobs / horizon)
        if rng.random() < interactive_share:
            gpus, runtime, prio = 1, rng.uniform(0.5, 4) * 3600, "standard"
        else:
            gpus = rng.choices([8, 16, 32, 64], weights=[45, 30, 17, 8])[0]
            runtime = min(rng.lognormvariate(math.log(6 * 3600), 0.9), 48 * 3600)
            prio = rng.choices(["high", "standard", "preemptible"], weights=[10, 70, 20])[0]
        out.append(TraceJob(f"r{i:04d}", t, rng.choice(teams), gpus, runtime, prio))
    return out


def spec_for(job: TraceJob) -> JobSpec:
    hours = max(1, math.ceil(job.runtime_s / 3600))
    return JobSpec(
        name=f"replay-{job.id}", team=job.team, project="replay", experiment=job.id,
        image=SIM_IMAGE, command=["sleep", "infinity"], gpus=job.gpus,
        max_runtime=f"{hours}h", priority=job.priority,
        checkpoint_dir=f"s3://sim-replay/checkpoints/{job.id}", resume_tested=True, cuda="12.4",
    )


@dataclass
class JobState:
    job: TraceJob
    submitted_at: float | None = None
    admitted_at: float | None = None
    first_admitted_at: float | None = None
    run_s: float = 0.0              # simulated seconds run so far (survives preemption)
    finished_at: float | None = None
    rejected: str | None = None
    evictions: int = 0
    seen_evictions: set = field(default_factory=set)
    eviction_reasons: list = field(default_factory=list)
    partial_polls: int = 0
    partial: bool = False


class Tracker:
    """Pure bookkeeping: fed observations, decides what to finish, reports."""

    def __init__(self, jobs: list[TraceJob], capacity_gpus: int):
        self.states = {j.id: JobState(j) for j in jobs}
        self.capacity = capacity_gpus
        self.gpu_seconds = 0.0
        self.busy_seconds = 0.0         # sim seconds with at least one job waiting
        self.busy_gpu_seconds = 0.0     # GPU-seconds allocated during those seconds
        self.last_now = 0.0

    def due(self, now: float) -> list[JobState]:
        return [s for s in self.states.values()
                if s.submitted_at is None and s.rejected is None and s.job.submit_s <= now]

    def observe(self, now: float, workloads: dict[str, dict[str, Any]],
                unscheduled_pods: dict[str, int]) -> list[JobState]:
        """Update from a poll; return jobs whose runtime is done (to delete)."""
        dt = now - self.last_now
        self.last_now = now
        done = []
        step_gpus = 0
        waiting = False
        for s in self.states.values():
            if s.submitted_at is None or s.finished_at is not None or s.rejected:
                continue
            wl = workloads.get(s.job.id)
            conds = {c["type"]: c for c in (wl or {}).get("status", {}).get("conditions", [])}
            ev = conds.get("Evicted")
            if ev and ev.get("status") == "True" and ev.get("lastTransitionTime") not in s.seen_evictions:
                s.seen_evictions.add(ev.get("lastTransitionTime"))
                s.evictions += 1
                s.admitted_at = None
                pre = conds.get("Preempted", {})
                reason = pre.get("reason") if pre.get("status") == "True" else None
                s.eviction_reasons.append(reason or ev.get("reason") or "unknown")
            admitted = conds.get("Admitted", {}).get("status") == "True"
            if admitted:
                if s.admitted_at is None:
                    s.admitted_at = now
                    s.first_admitted_at = s.first_admitted_at or now
                else:
                    s.run_s += dt
                    self.gpu_seconds += dt * s.job.gpus
                    step_gpus += s.job.gpus
                if unscheduled_pods.get(s.job.id, 0) > 0:
                    s.partial_polls += 1
                    s.partial = s.partial or s.partial_polls >= 3
                else:
                    s.partial_polls = 0
                if s.run_s >= s.job.runtime_s:
                    s.finished_at = now
                    done.append(s)
            else:
                s.admitted_at = None
                waiting = True
        if waiting:
            self.busy_seconds += dt
            self.busy_gpu_seconds += dt * step_gpus
        return done

    def finished(self) -> bool:
        return all(s.finished_at is not None or s.rejected for s in self.states.values())

    def report(self, elapsed: float) -> dict[str, Any]:
        by_prio: dict[str, list[float]] = {}
        for s in self.states.values():
            if s.first_admitted_at is not None:
                by_prio.setdefault(s.job.priority, []).append((s.first_admitted_at - s.submitted_at) / 3600)
        waits = {}
        for prio, w in sorted(by_prio.items()):
            w.sort()
            p90 = w[min(len(w) - 1, math.ceil(0.9 * len(w)) - 1)]
            waits[prio] = {"jobs": len(w), "p50_h": round(statistics.median(w), 2), "p90_h": round(p90, 2)}
        states = list(self.states.values())
        return {
            "jobs": len(states),
            "finished": sum(s.finished_at is not None for s in states),
            "never_admitted": sum(s.first_admitted_at is None and not s.rejected for s in states),
            "rejected_by_preflight": sum(bool(s.rejected) for s in states),
            "evictions": sum(s.evictions for s in states),
            "evictions_by_priority_reason": _count(
                f"{s.job.priority}/{r}" for s in states for r in s.eviction_reasons),
            "nonpreemptible_borrow_evictions": sum(
                r in BORROW_PREEMPTION_REASONS for s in states if s.job.priority != "preemptible"
                for r in s.eviction_reasons),
            "partial_placements": sum(s.partial for s in states),
            "allocation_ratio": round(self.gpu_seconds / (self.capacity * elapsed), 3) if elapsed else 0,
            "allocation_ratio_busy": (round(self.busy_gpu_seconds / (self.capacity * self.busy_seconds), 3)
                                      if self.busy_seconds else None),
            "busy_h": round(self.busy_seconds / 3600, 1),
            "sim_elapsed_h": round(elapsed / 3600, 1),
            "queue_wait_by_priority": waits,
        }


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


def evaluate(report: dict[str, Any], criteria: dict[str, float] | None = None) -> dict[str, Any]:
    """Score a replay report against the ADR 0004 pass criteria."""
    c = {**CRITERIA, **(criteria or {})}
    p90 = report["queue_wait_by_priority"].get("standard", {}).get("p90_h")
    busy = report.get("allocation_ratio_busy")
    checks = {
        "partial_placements": (report["partial_placements"], f"<= {c['partial_placements_max']}",
                               report["partial_placements"] <= c["partial_placements_max"]),
        "p90_wait_standard_h": (p90, f"< {c['p90_wait_standard_h_max']}",
                                p90 is not None and p90 < c["p90_wait_standard_h_max"]),
        # No queue ever formed: allocation can't be judged, and isn't the bottleneck.
        "allocation_ratio_busy": (busy, f">= {c['allocation_ratio_busy_min']}",
                                  busy is None or busy >= c["allocation_ratio_busy_min"]),
        "never_admitted": (report["never_admitted"], f"<= {c['never_admitted_max']}",
                           report["never_admitted"] <= c["never_admitted_max"]),
        "nonpreemptible_borrow_evictions": (
            report["nonpreemptible_borrow_evictions"], f"<= {c['nonpreemptible_borrow_evictions_max']}",
            report["nonpreemptible_borrow_evictions"] <= c["nonpreemptible_borrow_evictions_max"]),
    }
    return {
        "pass": all(ok for _, _, ok in checks.values()),
        "checks": {k: {"value": v, "target": t, "pass": ok} for k, (v, t, ok) in checks.items()},
    }


def run(kube, cfg: dict, jobs: list[TraceJob], speed: float = 600, poll_s: float = 5,
        max_sim_s: float | None = None, clock=time.monotonic, sleep=time.sleep,
        log=print) -> dict[str, Any]:
    """Drive the replay. `speed` = simulated seconds per real second."""
    capacity = sum(p["gpus_per_node"] * p["nodes"] for p in cfg["pools"].values())
    tracker = Tracker(jobs, capacity)
    horizon = max_sim_s or (max(j.submit_s + j.runtime_s for j in jobs) * 3 if jobs else 0)
    start = clock()
    now = 0.0
    namespaces = list(cfg["teams"])
    while not tracker.finished() and now <= horizon:
        now = (clock() - start) * speed
        for s in tracker.due(now):
            spec = spec_for(s.job)
            res = preflight.run(spec, cfg)
            if not res.ok:
                s.rejected = ",".join(sorted({f.code for f in res.findings if f.level == "error"}))
                continue
            kube.apply(manifest.build(spec, res, cfg))
            s.submitted_at = now
        workloads, unscheduled = _poll(kube, namespaces)
        for s in tracker.observe(now, workloads, unscheduled):
            name = spec_for(s.job).name
            kube.delete("job", name, s.job.team)
            kube.delete("service", name, s.job.team)
        sleep(poll_s)
    report = tracker.report(now)
    log(f"replay finished at sim {now / 3600:.1f}h")
    return report


def _poll(kube, namespaces: list[str]) -> tuple[dict[str, dict], dict[str, int]]:
    workloads: dict[str, dict] = {}
    unscheduled: dict[str, int] = {}
    for ns in namespaces:
        for wl in kube.get_json(["workloads.kueue.x-k8s.io", "-n", ns]).get("items", []):
            for ref in wl["metadata"].get("ownerReferences", []):
                if ref.get("kind") == "Job" and ref["name"].startswith("replay-"):
                    workloads[ref["name"][len("replay-"):]] = wl
        for pod in kube.get_json(["pods", "-n", ns, "-l", "project=replay"]).get("items", []):
            conds = {c["type"]: c.get("status") for c in pod.get("status", {}).get("conditions", [])}
            if conds.get("PodScheduled") == "False":
                jid = pod["metadata"]["labels"].get("experiment-id", "")
                unscheduled[jid] = unscheduled.get(jid, 0) + 1
    return workloads, unscheduled
