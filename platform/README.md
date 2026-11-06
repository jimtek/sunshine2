# GPU Fleet Platform

Multi-account EKS platform with Kueue scheduling for a 1,000+ GPU NVIDIA fleet on
AWS: automated GPU failure handling, researcher self-service, per-experiment cost
metrics, and Terraform for everything. The build plan lives in the
"GPU Fleet Platform: Build Plan" doc; this directory is its implementation.

## Status: Phase 1 (Pilot) in progress, on Phase 0 defaults

| Phase | Weeks | Status |
|---|---|---|
| 0 Assess | 1-4 | Running in parallel; defaults accepted — `docs/phase0/README.md` |
| 1 Pilot | 5-12 | **In progress** — `docs/phase1/README.md` |
| 2 Harden | 13-20 | Not started |
| 3 Scale | 21-26 | Not started |

## Layout

```
config/
  fleet-defaults.yaml       Phase 0 planning defaults + Goals targets
  platform.yaml             teams, quotas, pools, priorities — source for cluster/ and preflight
cluster/                    Kubernetes objects (kustomize): Kueue queues/flavors, label policy, RBAC, add-on values
sim/                        kind + KWOK simulation cluster, smoke test
observability/              Prometheus rules and Grafana dashboards
terraform/modules/          network, eks-cluster, gpu-nodegroup, storage, inventory-readonly-role
terraform/live/             phase0 (inventory role), platform-test (pilot cluster)
tools/fleetops/             platform-team CLI: inventory, triggers, baseline, render
tools/gpu/                  researcher CLI: preflight, submit, status, logs, cancel; replay for the pilot test
docs/                       decisions, runbooks, getting started, support, phase plans
```

Still to come: remediation controller and `gpu explain` (Phase 2), cost reporting (Phase 3).

## Quick start

```bash
pip install -e 'tools/fleetops[dev]' -e 'tools/gpu[dev]'
pytest tools/fleetops tools/gpu
fleetops render --check
gpu preflight tools/gpu/examples/multi-node-training.yaml
sim/up.sh && sim/smoke.sh        # needs docker, kind, kubectl
```
