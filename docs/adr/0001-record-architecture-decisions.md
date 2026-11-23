# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-11-23

## Context

FastStudio is an open-source library with a public API that users depend on.
Decisions about that API and about security need a durable, reviewable record.

## Decision

We record significant decisions as ADRs in `docs/adr/NNNN-title.md` using this
format (Status, Date, Context, Decision, Consequences). ADRs are immutable once
accepted; a change is a new ADR that supersedes the old one. Any rename or
removal of public API, new public extension point, or change to a security
control requires an ADR.

## Consequences

Slightly more process for structural changes; much easier review and
onboarding.
