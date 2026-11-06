# 0003. Support ownership and on-call

- Status: accepted on planning defaults (2026-11-06); revisit when Phase 0 data arrives
- Date: 2026-11-06
- Phase: 0

## Context

No scheduler or support process exists today. The plan assumes three
engineers with business-hours on-call. Support load is a tracked outcome
(tickets per researcher, down 50% in 6 months), so every ticket must be
counted and coded.

## Decision

- **Owner:** the GPU platform team owns researcher support for GPU clusters,
  scheduling, job failures and fleet observability. Central infrastructure owns
  identity, network, security baselines and cost data feeds; tickets in those
  areas are routed to them with a named contact.
- **Channel:** one support channel. Every request becomes a ticket with a cause
  code from `docs/phase0/support-cause-codes.yaml`.
- **On-call:** one primary engineer per week, business hours (09:00-18:00 local,
  weekdays). Response targets: P1 (fleet or large run down) 30 min,
  P2 (team blocked) 4 business hours, P3 (question) 1 business day.
- **After hours:** automation quarantines faulty nodes; large-run windows booked
  in advance get scheduled cover.
- **Feedback loop:** monthly cause-code review. A cause seen three times gets a
  named fix: a preflight check, a tool change or a doc.
- **Resilience:** runbooks from day one; a second engineer on the rota by Phase 2.

## Consequences

- Ticket counts and cause codes from Phase 0 become the support-load baseline.
- Overnight response is not promised; researchers plan large runs with the team.

## Revisit if

The team is smaller than three, or research deadlines need overnight response.
