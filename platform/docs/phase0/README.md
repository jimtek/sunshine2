# Phase 0: Assess (weeks 1-4)

Goal: replace planning defaults with measured facts, and agree scope, owners and
the account model.

**Exit gate:** scope, owners and account model agreed. Concretely: ADR 0002 and
ADR 0003 accepted, every section of `config/fleet-defaults.yaml` marked
`confirmed` or `corrected`, and the baseline report published.

## Status (2026-11-06)

Phase 1 started on planning defaults before the Phase 0 measurements, by
decision of the platform owner. ADRs 0002 and 0003 are accepted on those
defaults. The Phase 0 work below still runs in parallel; anything it finds
that fires a `revisit_if` trigger is fed back into Phase 1.

## Deliverables

| # | Deliverable | How | Output | Week |
|---|---|---|---|---|
| 1 | Fleet inventory by GPU type, region, account, reservation | `fleetops inventory` + `fleetops triggers` | `out/inventory.json`, `out/inventory-summary.csv` | 1 |
| 2 | Baseline: utilization, queue wait, job success, support load, cost | `baseline-measurements.yaml` → `fleetops baseline` | `baseline-report.md` | 1-3 |
| 3 | Researcher interview summary (workload mix, Slurm dependence) | `interview-guide.md`, `interview-summary.md` | interview summary | 2-3 |
| 4 | Decision records: account model, support ownership | ADR 0002, 0003 | accepted ADRs | 3-4 |
| 5 | Confirmed or corrected open-question defaults | edit `config/fleet-defaults.yaml` status fields | config PR | 4 |

## Week-by-week

- **Week 1:** deploy the read-only inventory role to each account; run the
  inventory; start collecting tickets with cause codes; book interviews.
- **Week 2:** pull CloudWatch / DCGM (where present) utilization and Cost and
  Usage Report data for a 30-day window; run interviews.
- **Week 3:** fill `baseline-measurements.yaml`; draft interview summary;
  review ADRs with central infrastructure.
- **Week 4:** set each default's status; reset Goals targets from the baseline;
  exit-gate review.

## Running the tools

```bash
cd platform/tools/fleetops
pip install -e '.[dev]'
fleetops check-config                       # validate defaults, list open assumptions
cp ../../config/accounts.example.yaml ../../config/accounts.yaml   # fill in IDs
fleetops inventory --accounts ../../config/accounts.yaml --out-dir out
fleetops triggers  --inventory out/inventory.json   # which defaults no longer hold
fleetops baseline  --measurements ../../docs/phase0/baseline-measurements.yaml \
                   --out ../../docs/phase0/baseline-report.md
```

## Where each baseline number comes from (no scheduler exists yet)

| Metric | Phase 0 source |
|---|---|
| Allocation ratio | Instance-hours of running GPU instances vs. reserved + owned instance-hours (inventory snapshots, CUR) |
| GPU utilization | DCGM exporter where installed; otherwise CloudWatch agent `nvidia_smi` metrics on a sample of nodes |
| Queue wait | Interviews and any existing job logs; mark as estimate |
| Job success rate | Existing job logs/launchers; else not-measured |
| Fault → quarantine / → case | Last 90 days of AWS support cases and incident notes |
| Tickets per researcher | Ticket tracker or channel export, coded with `support-cause-codes.yaml` |
| Cost attribution | Share of GPU spend in CUR with a team/project tag |
