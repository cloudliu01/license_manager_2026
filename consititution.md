# License Manager Constitution (Concise v2.1)

## 1. Mission

Build a reliable, operable, auditable control plane for FlexLM-style license operations that improves visibility and control, supports offline client work, and remains maintainable in real infrastructure.

## 2. What this is

A distributed **control + observability** system for humans operating license services. Not a license enforcement engine, not a wrapper script.

## 3. Non-negotiable invariants

1. **Client-authoritative config**
   A config change is real only when the client applies it and reports the new effective state. Server stores snapshots/history/proposals.

2. **One active server per client**
   Each client binds to one `server_id`. No split-brain control.

3. **Explicit authority boundaries**
   GUIs propose; server arbitrates policy/audit; agent executes and reports. No implicit privileges or “helpful” overrides.

4. **Deterministic + auditable operations**
   Every action is traceable (who/what/when/inputs/result/system state at time).

5. **Offline capability without deception**
   Clients may operate offline, but the system must clearly surface degraded global truth and reconcile reliably.

6. **Idempotency and safety over speed**
   Retried operations must be safe; correctness beats performance.

7. **Observability before automation**
   Automated actions require explainability, traceability, and failure detection.

8. **Failure is first-class**
   Represent partial success, uncertainty, missing vs zero data, transient vs permanent failures. No silent failure.

9. **Portable without fragility**
   Unpack-and-run releases (no installer) must still fail loudly and diagnostically when misconfigured.

10. **Evolve without erasing history**
    Upgrades must preserve auditability and historical meaning; new interpretations don’t delete old facts.

## 4. Design values

Prefer boring, proven approaches; minimize coupling across components; optimize for operator understanding and predictable control.
