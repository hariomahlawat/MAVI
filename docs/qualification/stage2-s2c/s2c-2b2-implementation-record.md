# S2c.2b-2 — Operational implementation record

Authoritative baseline: `main@8b6614721ff3d0fe7a77cde66ce6051defcceb74` (PR #121). Branch: `feature/s2c-2b2-operational-protocol`. Status: implementation and independent cold review complete; exact-head CI and external review remain merge gates. No Stage-2 acceptance is claimed.

## Implementation and authority

The strict b-2 contract and deterministic Markdown projection consume b-1 statistical authority without changing populations, partitions, margins, support, gates or paired outcomes. Pure helpers derive E after MPID, F against every original E comparator, fallback-aware J, exact joint T, per-capability M1/profile-admissible K and recomputed T_impl. Credibility never changes T or T_r. S2c uses M2/decision-v2; unrelated events retain v1.

Canonical quality results, frozen evidence and per-experiment protocols are retained independently of active projections. Joint versions and indexes have a recomputed linear predecessor chain. Event decision versions carry their own sequence and predecessor hash. Historical evidence resolves from repository files; licence/snapshot updates preserve the original raw technical evidence and technical-stage bytes.

Clarification I1 is the sole governing-plan repair: a pending implementation-stage licence determination must be able to resolve without rewriting an immutable version or reopening statistical selection. The first implementation version extends technical; subsequent implementation-only versions extend implementation, with unchanged frozen/technical inputs, monotone dates and append-only snapshots. This makes pending-to-resolved progression coherent with retention.

The bounded replay models the production FIFO/claim/deadline/lease semantics and Phase-C row lock, ownership fence, timestamp sample, commit and acknowledgement separately. `completedAtUtc` is the platform timestamp sampled inside the Phase-C transaction; `publicationCommittedAtUtc` requires server/harness instrumentation and is not client acknowledgement. Phase A and READY also require instrumentation. The E2 helper observes the existing AttributeRunner/inferencer seam and real platform client; synthetic clients are test-only.

Resolved host profiles and frozen workload envelopes bind the 500-camera projection. Retained engineering source records supply startup, whole-job service scenarios, resource peaks, deployment footprint and server transaction times. Recomputed reports expose latency, deadline/SLA misses, retries, waiting jobs/Tracks, backlog and drain. Lower and upper demand scenarios both must satisfy operational admission. This is a workload/hardware-specific projection, not 500-camera qualification.

## Cold review closure

| Prior finding | Repair and discriminating evidence |
|---|---|
| CLOSED/null erased an available implementation | Refuse null with nonempty T_impl; closed-availability mutation killed |
| Both predecessor events could be deleted and successors renamed | Embedded event version and exact predecessor hash; both-coordinate deletion refused |
| Changed raw engineering inputs could preserve H and pass | Original raw pair records must remain byte-identical; changed RAM with fresh source refs refused |
| v2 bypassed M1 active bindings | Validate event location, frozen ledger, record hashes, active snapshot and append-only working ledger; backdated additions refused |
| Phase-C lock absent from replay | Fence/sample/lock event; claim/sweep skip it through commit; lock-removal mutation killed |
| Decisions could predate freeze | Experiment/date boundary plus monotone retained event/snapshot chronology |
| Operational inputs/outputs were incomplete | Resolved host/envelope, source records, cold/resource/footprint constraints and recomputed projection reports |

The final independent read-only review found no remaining substantiated P1/P2. The duplicate template section number was corrected (P3).

## Validation

- Full affected credibility/b-1/S2c suite: **376 passed**; S2c subset: **119 passed**.
- Full qualification suite: **1,251 passed, 3 skipped**.
- `python tools/verify_repo.py`: **passed**.
- Contract/repository CLIs, schema acceptance/recomputation, Python compilation and `git diff --check`: **passed**.
- Five targeted mutations killed: all-comparator protection, emerging eligibility, exact-pair membership, Phase-C locking and closed implementation availability. Mutation copies were isolated from the repository.
- Broader vision suite and normal CI gates are reported on the PR; no unobserved build result is claimed. This environment has no .NET SDK, and no .NET/runtime/API/UI code changed.

## Review and scope boundary

Human review remains responsible for representative engineering workloads/hardware, scientific grounding and provenance of measured leaf evidence and b-1 outcomes, confidence-envelope calibration, legal clearance and freeze-before-first-read attestation until the execution harness supplies that record. Canonical hashes detect mismatches against retained references; they do not authenticate authors or detect coordinated replacement of all evidence roots. E3 execution/validation remains a later gate and cannot rescue or tune selection.

No real model was selected, downloaded, trained or benchmarked. No frozen-test evidence was consumed, no acceptance row was promoted, and no unrelated runtime/API/UI work was introduced. The architecture-closure principle is recorded in the MSR README §14.2; it adds no machinery or scope.

## PR #122 P1 retained-chain continuity repair

Review of `ca27c94ddee12ecb8d78bd7295f9916ac871f85d` exposed repeated technical event decisions switching to an unrelated, individually valid joint chain with the same event IDs. The merged plan's retained linear-chain authority requires continuity from repository artefacts. The shared event-predecessor guard now permits an unchanged joint hash or the immediate retained successor with the same event-pair identity, next version and exact predecessor hash. It applies across states so qualification cannot bypass an unrecorded technical revision. Existing canonical, M2, state, reopening and technical-evidence checks remain intact.

Thirteen new cases cover unchanged references, legitimate technical/reopening/implementation progression, unrelated chains, stored malicious event histories, backward references, skipped revisions and fabricated forks/predecessors. Against the exact prior production head, six regression cases failed as expected and seven passed; the repaired targeted suite passed **389 tests**. The existing exact-pair unit test isolates its deliberately synthetic, hash-inconsistent joint from lineage validation; retained-chain tests exercise real files and indexes without that mock.

Repair validation also passed the full qualification suite (**1,264 passed, 3 skipped**), `tools/verify_repo.py`, Python compilation and `git diff --check`.

Independent cold review found two transition variants of the same P1, both repaired by the shared guard, and no remaining P1/P2 in the repair. Architecture closure in README §14.2 is unchanged. Exact-head CI and unresolved external review threads remain merge gates.
