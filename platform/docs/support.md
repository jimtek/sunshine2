# Researcher support

Owner and process: ADR 0003.

- **Channel:** one support channel; every request becomes a ticket with a
  cause code from `phase0/support-cause-codes.yaml`.
- **On-call:** business hours, weekdays 09:00-18:00. Response targets:
  P1 (fleet or large run down) 30 min, P2 (team blocked) 4 business hours,
  P3 (question) 1 business day.
- **Office hours:** weekly, 30 minutes; top questions go into `getting-started.md`.
- **Monthly review:** any cause code seen 3+ times gets a named fix: a preflight
  check, a tool change or a doc.

Before asking, run `gpu preflight` and `gpu status`, and include their output.
