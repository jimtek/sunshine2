# 0002. AWS account model

- Status: accepted on planning defaults (2026-11-06); revisit when Phase 0 data arrives
- Date: 2026-11-06
- Phase: 0

## Context

The fleet spans several AWS accounts today. The platform must separate
production research from partner work, and give platform engineers a place to
test upgrades and real-GPU smoke tests without risking production capacity.
EA central infrastructure owns identity, network connectivity, security
baselines and cost data feeds.

## Decision

Three workload accounts under the existing AWS Organization, each with its own
EKS cluster(s), managed by Terraform:

| Account | Holds | Access |
|---|---|---|
| `research` | Production training and interactive work; most reservations and Capacity Blocks | Researchers via the submit tool; platform team admin |
| `partner` | One namespace-or-cluster per external partner, per-partner storage | Partner roles, least privilege, no default internal data access, audit logging on |
| `platform-test` | Pilot pool, upgrade rehearsal, Phase 1 smoke tests | Platform team only; budget alert and auto-shutdown on stacks |

Cross-account: a read-only `FleetInventoryReadOnly` role in each account
(`terraform/modules/inventory-readonly-role`) for inventory and metrics.
Identity, networking (Transit Gateway / shared VPC attachments) and security
baselines come from central, per their ownership.

## Options considered

| Option | Strength | Weakness here | Verdict |
|---|---|---|---|
| Single account, namespaces only | Simplest; one capacity pool | Weak partner isolation; test changes risk production | Rejected |
| Three accounts (research, partner, platform-test) | Clear blast radius and billing; matches partner isolation needs | Reservations are per account; cross-account ops tooling | **Proposed** |
| Account per team | Strong cost isolation | Fragments reservations and Capacity Blocks; quota handled better by Kueue | Rejected |

## Consequences

- Capacity reservations must be bought in, or shared via AWS RAM to, the account that runs the jobs.
- The Capacity Block limit (256 instances) is per Organization, so all three accounts draw from one budget.
- Cost attribution uses job labels within accounts, not account boundaries.

## Revisit if

Central policy mandates its own account structure, a partner contract requires a
dedicated account per partner, or a second region is needed.
