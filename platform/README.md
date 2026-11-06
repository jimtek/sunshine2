# GPU Fleet Platform

Multi-account EKS platform with Kueue scheduling for a 1,000+ GPU NVIDIA fleet on
AWS: automated GPU failure handling, researcher self-service, per-experiment cost
metrics, and Terraform for everything. The build plan lives in the
"GPU Fleet Platform: Build Plan" doc; this directory is its implementation.

## Status: Phase 0 (Assess), weeks 1-4

| Phase | Weeks | Status |
|---|---|---|
| 0 Assess | 1-4 | **In progress** — see `docs/phase0/README.md` |
| 1 Pilot | 5-12 | Not started |
| 2 Harden | 13-20 | Not started |
| 3 Scale | 21-26 | Not started |

## Layout

```
config/
  fleet-defaults.yaml       planning defaults + targets; Phase 0 confirms/corrects each
  accounts.example.yaml     template for account IDs (real file is git-ignored)
docs/
  decisions/                numbered decision records (ADRs)
  phase0/                   assessment plan, interview kit, cause codes, baseline inputs
terraform/
  modules/inventory-readonly-role   read-only cross-account role for inventory
  live/phase0/              per-account deployment of that role
tools/fleetops/             Python CLI: check-config, inventory, triggers, baseline
```

Planned for later phases (not yet created): `terraform/modules/{vpc,eks,gpu-nodepool,fsx}`,
`cluster/kueue/`, `tools/submit/` (submit CLI + preflight), `controllers/remediation/`,
`observability/` dashboards.

## Quick start

```bash
cd tools/fleetops && pip install -e '.[dev]' && pytest && fleetops check-config
```
