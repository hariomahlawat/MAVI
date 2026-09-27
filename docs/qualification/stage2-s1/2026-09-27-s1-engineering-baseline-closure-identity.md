# Decision note: S1 engineering baseline and formal closure identity

- **Date:** 2026-09-27
- **Scope:** Stage-2 S1 Track Evidence Set closure position and its relationship to S2a Component Binding v2.
- **Changes nothing executable.** `tools/qualification/s1_evidence.py`, `s1_memory.py`, the acceptance register statuses, harnesses and workflows are untouched by this note.

## Decision

`c176b048e278f7097d49254efc47d89917f687c0` is the frozen S1 engineering baseline and may retain historical S1 qualification evidence indefinitely. S1 remains formally OPEN. Once S2a behavior-bearing changes merge, the existing S1 checker will not permit a later `s1Closed: true` claim based solely on the `c176b048` evidence. Any eventual formal closure on a later `main` must follow the checker's then-current invalidation rules, or the qualification architecture must first be deliberately redesigned and reviewed.

## What the checker actually requires (so the decision is precise)

`tools/qualification/s1_evidence.py` accepts a closure record whose `mergeSha` differs from the `measuredSha`, descends from it and is an ancestor of `main` (`verify_git_diff`, `:2529-2554`), with successful post-merge workflows on that `mergeSha` (`:2491-2499`, `POST_MERGE_WORKFLOWS` `:255-259`). It computes `changedPaths` between the two SHAs, maps them through `invalidated_units(...)` (`BEHAVIOR_BEARING_SURFACE` `:59-82`, `INVALIDATION_MAP` `:112-131`; a behavior-bearing path the map does not name invalidates **every** unit, `:1090-1091`) and raises `closure_rerun_required` for any PASS unit that was invalidated and not re-measured on the closure SHA.

Two consequences follow:

1. **A closure whose `mergeSha` is a pre-S2a `main` commit remains available** — for example a docs-only merge such as S2a.0 — provided the diff from `c176b048` stays outside the surface and the post-merge workflows succeeded on that SHA. This note does not exercise that option; it only records that the checker allows it.
2. **A closure whose `mergeSha` includes any S2a behavior-bearing path is impossible from the `c176b048` evidence alone.** S2a's paths and the units they invalidate under the current map:
   - `src/vision/mavi_vision/runtime/**`, `src/vision/config/components/**`, `config/acceptance/**`, `tools/vision/**`, `tools/setup/**`, `tools/qualification/**` (behavior-bearing and **unmapped** → all seven units);
   - `src/vision/runtime/**`, `models/**`, `config/dependencies/**` → B1, B6, DISCONNECTED;
   - `src/vision/mavi_vision/common/**`, `src/vision/mavi_vision/worker/**`, `contracts/**` → B3, B4, B5, B6, DISCONNECTED;
   - `src/platform/**` → B3, B4, B5, DISCONNECTED;
   - `src/vision/config/pipelines/**` → B1, B2, B3, B5, B6, DISCONNECTED (S2a does not change it).

**Therefore the first S2a PR that touches this surface — S2a.1, which adds `mavi_vision/runtime/{capabilities,binding,model_pack_identity}.py`, `config/acceptance/capability-gate-sets-v1.json` and `tools/vision/migrate_component_binding_v1.py` — is the point after which formal S1 closure on a later `main` using only pre-S2a evidence is no longer possible under the current checker.** S2a.3 is the *behavioural* cut-over (the first PR that changes what the worker and platform do); the checker consequence arrives at S2a.1 because the checker looks at paths, not runtime behaviour. Both PR bodies state this.

## What this note does not do

- It does not claim B1–B6 or DISCONNECTED PASS. The register rows stay OPEN.
- It does not weaken, waive or special-case `s1_evidence.py`.
- It does not redefine the `c176b048` evidence as a formal closure of a future `main`.
- It does not authorise re-running S1 units on `c176b048` merely to populate metadata; the B2 `runtimeVariant` omission stands as recorded: the eleven B2 workloads completed on the Windows host, but they are **not a register PASS** and the formal derived package stays OPEN because `derive` fails closed on the null variant (`s1_memory.py:1010-1011`).

## What the frozen baseline is for

- **Historical engineering evidence.** The Windows B3-A, B3-B and crash-matrix runs and the eleven B2 workloads were executed on this exact SHA on the Windows host. Their outputs are held **outside this repository** (no evidence package for `c176b048` is committed; nothing in the repo verifies them yet) until an evidence package is assembled and checked by the unmodified checker against this identity. Until then they are engineering observations, not register results.
- **Regression comparison.** S2a's C7 proof records and replays real clips at `c176b048` and at the S2a.3 head; the only permitted differences are the provenance identity fields (S2a plan §9). Later slices compare against the same baseline.
- **Recovery.** The baseline is recoverable by SHA; a tag `baseline/s1-engineering-c176b048` is recommended (created by the repository owner; not part of this documentation change).

## Consequence for the S1 exit gate

The Stage-2 S1 exit gate ("B1–B6 PASS", acceptance register §B) is unchanged. Under the current checker it can be satisfied on a post-S2a `main` only by re-measuring the invalidated units on that `main`. Reducing that cost requires the qualification-architecture redesign recorded in the S2a plan §15 (immutable measured identity, per-unit retained results, resumable campaigns, rigorously defined dependency-scoped invalidation, and the distinction between engineering regression, scaling characterization, boundary proof and formal release qualification). That redesign is a separate reviewed slice, not part of S2a, and until it is accepted the current rules govern.

## Lesson carried forward (tooling principle, no code change here)

`s1_memory.py` learns `runtimeVariant` from `MAVI_RUNTIME_VARIANT` (`:665`) and rejects a null only at `derive` (`:1010-1011`), after hours of measurement. All future qualification tooling must validate required identity before the expensive run starts, fail immediately when it is absent or inconsistent, prefer host/runtime-derived identity (as the .NET harnesses do in `S1QualificationSupport.RuntimeVariant()`), and never discover a mandatory provenance omission after execution. Any change to `s1_memory.py` itself is a separate, narrowly scoped PR with its own tests.
