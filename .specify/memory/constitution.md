<!--
Sync Impact Report
- Version change: 1.2.0 -> 2.0.0
- Modified principles:
  - I. Headless Server First -> I. Control Plane, Not a Tool
  - II. Strict Separation of Concerns -> II. Single Source of Truth
  - III. Canonical Parsing Lives on the Server -> III. Observability Before Automation
  - IV. Protocol Before Implementation -> IV. Determinism Over Cleverness
  - V. Simulator-Driven Development -> V. Explicit Authority Boundaries
  - VI. Risk-Weighted Testing -> VI. Humans Are Part of the System
  - VII. Portability Is a Deployment Property -> VII. Evolution Without Invalidating History
  - VIII. Configuration Is Explicit and Typed -> VIII. Failure Is a First-Class Outcome
  - IX. Visibility Is Not Authority -> IX. Infrastructure Reality Awareness
  - X. Storage Is Tiered by Intent -> X. Boring Is a Feature
  - XI. Embedded Database Is Optional -> XI. Portability Without Fragility
  - (new) -> XII. No Irreversible Decisions Without Escape Hatches
  - (new) -> XIII. The Constitution Is Above the Spec
- Added sections: None
- Removed sections: None
- Templates requiring updates:
  - ✅ updated: .specify/templates/plan-template.md
  - ✅ updated: .specify/templates/spec-template.md
  - ✅ updated: .specify/templates/tasks-template.md
- Follow-up TODOs:
  - TODO(RATIFICATION_DATE): original adoption date not recorded
-->
# License Manager Constitution

## Purpose

This project builds a **license management control plane** that coordinates state
across machines, arbitrates intent and authority, and presents a system-level view
of license operations. It optimizes for global correctness, auditability, and
operator understanding over host-local convenience.

## Core Principles

### I. Control Plane, Not a Tool

The system is a control plane, not a script, wrapper, or helper tool.

* It MUST coordinate state across machines.
* It MUST arbitrate intent and authority.
* It MUST produce a system-level view, not host-local views.
* It MUST favor global correctness over local convenience.

Rationale: A control plane guarantees correctness across the fleet, not on one host.

### II. Single Source of Truth

At any moment, there is exactly one authoritative view of:

* License state
* Control intent
* Operational history

Replication, caching, and mirroring are allowed, but authority is never duplicated.

Rationale: Consistency and auditability require a single authority boundary.

### III. Observability Before Automation

The system MUST explain itself before it is allowed to act.

* Every action MUST be traceable.
* Every derived state MUST be explainable.
* Every automated decision MUST be reconstructible.

Rationale: Automation without observability is a defect.

### IV. Determinism Over Cleverness

When forced to choose, the system MUST prefer deterministic, explainable behavior
over clever optimization.

* Behavior MUST be replayable and auditable.
* Optimizations MUST NOT reduce explainability or reproducibility.

Rationale: A slower system that can be replayed and audited is superior to a faster
one that cannot.

### V. Explicit Authority Boundaries

No component may:

* Silently assume authority.
* Act on inferred intent.
* Escalate privileges implicitly.

Authority MUST be explicitly granted, explicitly exercised, and explicitly recorded.

Rationale: Authority is only legitimate when it is explicit and auditable.

### VI. Humans Are Part of the System

This system supports human operators; it does not replace them.

* Humans MUST initiate intent.
* Humans MUST arbitrate ambiguity.
* Humans MUST be able to override automation when necessary.

Rationale: Operator understanding is a primary system requirement.

### VII. Evolution Without Invalidating History

The system MUST evolve without rewriting its past.

* New interpretations MUST NOT erase old facts.
* Schema evolution MUST preserve meaning.
* Historical records MUST remain queryable.

Rationale: Progress cannot depend on destroying history.

### VIII. Failure Is a First-Class Outcome

Failure is a valid, representable state.

* Partial failure MUST be representable.
* Uncertainty MUST be representable.
* Absence of data MUST be distinguishable from negative data.
* Silence is never an acceptable failure mode.

Rationale: Systems that cannot represent failure cannot be trusted.

### IX. Infrastructure Reality Awareness

The system MUST respect real-world constraints:

* Heterogeneous hosts
* Imperfect networks
* Clock skew
* Human error
* Legacy software

Rationale: Designs that assume a clean environment are non-compliant with reality.

### X. Boring Is a Feature

The project intentionally favors boring technologies, protocols, and deployment
models. Novelty is acceptable only when it demonstrably reduces long-term
operational risk.

Rationale: Boring choices reduce operational surprise and maintenance risk.

### XI. Portability Without Fragility

Portability MUST NOT be achieved by hiding complexity, suppressing errors, or
weakening guarantees.

* Errors MUST be surfaced loudly and explicitly.
* Portability MUST preserve correctness guarantees.

Rationale: A system that works everywhere but fails silently is worse than one
that fails loudly in fewer places.

### XII. No Irreversible Decisions Without Escape Hatches

Any decision that affects data durability, control authority, or upgrade paths
MUST include a documented rollback or escape mechanism. Irreversibility requires
explicit justification.

Rationale: Safe evolution requires defined exits from risky decisions.

### XIII. The Constitution Is Above the Spec

Specs may evolve rapidly and implementations may change, but no change may violate
this constitution without explicitly revising it.

Rationale: The constitution is the highest authority in project governance.

## Explicit Non-Goals

* Replacing vendor license servers
* Enforcing license usage
* Hiding operational complexity to appear portable
* Silent automation without traceability

## Governance

- This constitution supersedes all other project practices and templates.
- Amendments MUST be proposed in a tracked change with rationale and impact analysis.
- Breaking governance or principle changes MUST include a migration plan.
- Versioning follows semantic versioning (MAJOR, MINOR, PATCH) with explicit rationale.
- Plans and specs MUST include a constitution compliance check and document any
  approved exceptions or waivers.
- Reviews MUST block changes that violate principles unless a written, time-bound
  waiver is approved and recorded.

**Version**: 2.0.0 | **Ratified**: TODO(RATIFICATION_DATE): original adoption date not recorded | **Last Amended**: 2026-01-27
