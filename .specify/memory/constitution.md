<!--
Sync Impact Report:
- Version change: Template -> 2.1.0
- Modified Principles: Defined 10 Non-negotiable invariants from user input (v2.1).
- Added sections: Mission & Scope, Design Values.
- Templates requiring updates: .opencode/command/speckit.constitution.md (✅ updated path ref).
- Follow-up TODOs: RATIFICATION_DATE set to today as default for v2.1 import.
-->
# License Manager Constitution

## Non-negotiable Invariants

### 1. Client-authoritative config
A config change is real only when the client applies it and reports the new effective state. Server stores snapshots/history/proposals.

### 2. One active server per client
Each client binds to one `server_id`. No split-brain control.

### 3. Explicit authority boundaries
GUIs propose; server arbitrates policy/audit; agent executes and reports. No implicit privileges or “helpful” overrides.

### 4. Deterministic + auditable operations
Every action is traceable (who/what/when/inputs/result/system state at time).

### 5. Offline capability without deception
Clients may operate offline, but the system must clearly surface degraded global truth and reconcile reliably.

### 6. Idempotency and safety over speed
Retried operations must be safe; correctness beats performance.

### 7. Observability before automation
Automated actions require explainability, traceability, and failure detection.

### 8. Failure is first-class
Represent partial success, uncertainty, missing vs zero data, transient vs permanent failures. No silent failure.

### 9. Portable without fragility
Unpack-and-run releases (no installer) must still fail loudly and diagnostically when misconfigured.

### 10. Evolve without erasing history
Upgrades must preserve auditability and historical meaning; new interpretations don’t delete old facts.

## Mission & Scope

### Mission
Build a reliable, operable, auditable control plane for FlexLM-style license operations that improves visibility and control, supports offline client work, and remains maintainable in real infrastructure.

### What this is
A distributed **control + observability** system for humans operating license services. Not a license enforcement engine, not a wrapper script.

## Design Values

Prefer boring, proven approaches; minimize coupling across components; optimize for operator understanding and predictable control.

## Governance

### Authority
This Constitution supersedes all other documentation and practices. In conflicts between code and constitution, the constitution must be followed or amended.

### Amendments
Amendments require:
1.  Clear rationale.
2.  Documentation of changes (Sync Impact Report).
3.  Approval by project maintainers.
4.  Migration plan for existing systems if invariants are changed.

### Compliance
All architectural decisions, PRs, and features must be verified against these Non-negotiable Invariants.

**Version**: 2.1.0 | **Ratified**: 2026-01-27 | **Last Amended**: 2026-01-27