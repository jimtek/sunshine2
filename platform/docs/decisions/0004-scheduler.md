# 0004. Scheduler: EKS + Kueue

- Status: proposed; decided by the Phase 1 replay and real-GPU tests
- Date: 2026-11-06
- Phase: 1

## Context

The build plan defaults to Kubernetes with Kueue, adding Volcano or Slurm only
if a pilot test shows a gap. Kueue is a beta API (v0.19.2 pinned), so the
decision needs evidence, not preference.

## Proposed decision

Kueue on EKS, configured from `config/platform.yaml`:

- one ClusterQueue per team in a shared `research` cohort, quotas in whole nodes,
  borrowing allowed, lent quota reclaimable;
- one ResourceFlavor per capacity pool, Capacity Blocks tried first;
- all-or-nothing admission (`waitForPodsReady`) and fair sharing on;
- WorkloadPriorityClasses `high`, `standard`, `preemptible`;
- multi-node training as Indexed Jobs (one pod per node), so a gang is one Kueue workload.

## Test (how this gets accepted or rejected)

Run `sim/smoke.sh` and a full-week replay on the simulation cluster:

```bash
gpu trace --jobs 300 --days 7 > week.csv        # or a real week from Phase 0 logs
gpu --context kind-gpu-sim replay week.csv --speed 600 --out replay-report.json --check
```

Pass criteria (agree before running; defaults shown):

| Measure | Pass |
|---|---|
| Partial placements (admitted gang with pods unscheduled ≥ 3 polls) | 0 |
| P90 queue wait, standard priority | Under 4 h (simulated) |
| Allocation ratio over the replay | ≥ 0.85 while the queue is non-empty |
| Jobs never admitted | 0 |
| Evictions of non-preemptible jobs by borrowing | 0 |

The replay scores itself against this table (`adr_0004` in the report; `--check`
exits non-zero on a fail; `--criteria FILE.yaml` overrides the targets if a
different set is agreed). Allocation counts only simulated time when a job is
waiting. A borrowing eviction is a `Preempted` condition with reason
`InCohortReclaimWhileBorrowing` on a `high` or `standard` job.

Then confirm on real GPUs (week 9 smoke, weeks 10-12 multi-node).

## Findings so far

- 2026-11-06: Kueue v0.19.2 stores `kueue.x-k8s.io/v1beta2` and marks `v1beta1`
  deprecated. Our rendered objects (`cluster/kueue/`) and the controller
  `Configuration` still use `v1beta1`. They need the controller's conversion
  webhook to apply, and should move to `v1beta2` before the pin is accepted.

## Revisit if

Partial placement or deadlocks appear (add Volcano or Kueue topology-aware
scheduling), or interviews show more than a third of researchers depend on
Slurm scripts they can't port (add Slinky).
