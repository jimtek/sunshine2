# Phase 1: Pilot (weeks 5-12)

**Exit gate:** simulated replay meets the agreed scheduling targets (ADR 0004),
and real-GPU tests pass.

## Deliverables

| Deliverable | Where | State |
|---|---|---|
| Terraform: accounts, IAM, VPC, EKS, storage | `terraform/modules/*`, `terraform/live/platform-test` | Written; validated in CI only, not applied |
| GPU node pools: GPU Operator, EFA, pinned images | `terraform/modules/gpu-nodegroup`, `cluster/addons` | Written; untested on real GPUs |
| Kueue pilot: team quotas, priorities, capacity flavors | `config/platform.yaml` → `cluster/kueue/` | Rendered; runs in simulation CI |
| Submit CLI v1 and preflight checks | `tools/gpu` | Done (submit, status, logs, cancel, preflight) |
| Required job labels enforced at admission | `cluster/policy/require-job-labels.yaml` | Done; tested in simulation CI |
| Prometheus rules and Grafana dashboards | `observability/` | Written; needs real metrics (week 9) |
| Support channel, office hours, getting-started guide | `docs/support.md`, `docs/getting-started.md` | Docs written; channel to be created |
| Scheduler decision record | `docs/decisions/0004-scheduler.md` | Proposed; needs the full-week replay |

## Test stages

| Stage | Weeks | How |
|---|---|---|
| Simulation | 5-8 | `sim/up.sh`, `sim/smoke.sh`, full replay (ADR 0004). Runs in CI on every change. |
| GPU smoke test | 9 | `terraform apply` platform-test with `dev_gpu_nodes=1`; install add-ons; submit the dev example; check DCGM metrics in Grafana; capture an evidence bundle by hand; then `dev_gpu_nodes=0`. |
| Real capacity | 10-12 | Point `reserved_capacity_reservation_id` at held capacity; multi-node example with EFA; FSx throughput; Capacity Block end-of-block drain. |

## Changing quotas, teams or pools

Edit `config/platform.yaml`, then:

```bash
fleetops render          # regenerates cluster/kueue, cluster/rbac, sim/kwok-nodes.yaml
fleetops render --check  # what CI runs
```

## Known gaps

- Simulation can't reproduce GPU failures, interconnect performance or AWS
  replacement behavior (build plan); those wait for real capacity.
- The `gpu` tool reads `config/platform.yaml` from the repo; serving it from a
  ConfigMap is next so researchers don't need the repo.
- Kueue's `Configuration` and the add-on chart versions are pinned from known
  releases but haven't been run here; CI's simulation job is the first real test.
