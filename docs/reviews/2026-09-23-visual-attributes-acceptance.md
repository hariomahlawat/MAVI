# Visual Attributes — Stage-2 Acceptance Register

**Status:** Open — created at architecture-planning start  
**Date opened:** 2026-09-23  
**Baseline:** `main@ca23adf55b0b4a14faf58e12d048a3c90221557c`

This file is intentionally created before implementation so acceptance evidence is accumulated, not reconstructed after the fact.

## Current verdict

**NOT STARTED.**

No Stage-2 implementation acceptance item is PASS yet.

## Governing documents

- `docs/superpowers/plans/2026-09-23-visual-attributes.md`
- `docs/decisions/ADR-013-modular-post-track-intelligence-and-evidence.md`
- `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`
- capability roadmap / implementation roadmap
- ADR-005 / ADR-006 / ADR-007 / ADR-009 / ADR-012

## Acceptance gate

| # | Requirement | Status |
|---|---|---|
| 1 | ADR-013 independently reviewed and accepted | OPEN |
| 2 | Track Evidence Set semantics and hard bounds frozen | OPEN |
| 3 | Evidence selector deterministic/versioned and tested | OPEN |
| 4 | Attribute lifecycle independent of ProcessingRun success | OPEN |
| 5 | Re-analysis possible without detector/tracker rerun when required sealed evidence exists | OPEN |
| 6 | Attribute schema/versioning frozen | OPEN |
| 7 | Every exposed attribute evidence-linked | OPEN |
| 8 | Producer/model/runtime provenance complete | OPEN |
| 9 | Unknown/unavailable/pending/failed semantics proven | OPEN |
| 10 | Historical/supersession semantics proven | OPEN |
| 11 | Strict bounded post-Track worker contract proven | OPEN |
| 12 | Stale attempt / retry / cancellation / failure isolation proven | OPEN |
| 13 | Search canonicalization/fingerprint/snapshot semantics proven | OPEN |
| 14 | PostgreSQL plan/query-count/latency evidence passes | OPEN |
| 15 | No demonstrated N+1/unbounded evidence-I/O path | OPEN |
| 16 | Frozen model corpus and thresholds meet gates for each exposed attribute | OPEN |
| 17 | CPU Development model/runtime qualification passes | OPEN |
| 18 | CUDA Development evidence recorded where applicable without Production claim | OPEN |
| 19 | Offline Binary Kit and disconnected execution pass | OPEN |
| 20 | Real-video Search → Investigation → Evidence Review workflow passes | OPEN |
| 21 | Accessibility and visual QA pass with no open P1/P2 | OPEN |
| 22 | Security/privacy review has no open P1/P2 | OPEN |
| 23 | Relevant suites and exact-head CI green | OPEN |
| 24 | Documentation reconciled to measured reality | OPEN |
| 25 | Independent cold review has no open P1/P2 | OPEN |
| 26 | No unresolved material review thread | OPEN |
| 27 | Post-merge critical verification on `main` green | OPEN |

## Evidence log

Populate each entry with:
- exact commit SHA;
- environment/runtime/model identities;
- command/workflow/run number;
- result;
- retained artefact hash where applicable;
- limitation or non-claim.

Nothing unexecuted is marked PASS.
