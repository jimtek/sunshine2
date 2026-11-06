# 0001. Record architecture decisions

- Status: accepted
- Date: 2026-11-06
- Phase: 0

## Context

The platform will make several hard-to-reverse choices (account model, scheduler,
capacity strategy) on planning defaults that Phase 0 may overturn. Without a
written record, the reasoning is lost when people or defaults change.

## Decision

Every major choice gets a numbered decision record in `docs/decisions/`, using
`0000-template.md`. Each record names the signal that would reopen it. A record
is changed only by superseding it with a new one.

## Consequences

- Decisions are reviewable in pull requests alongside the code they shape.
- `config/fleet-defaults.yaml` links to the record behind each default.
