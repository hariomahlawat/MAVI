# MSR method revision M3: benchmark-only baseline component and derived gate-only composition (supersedes draft "M1-A1")

**Status: PROPOSED.** It becomes governing only when merged after a fresh, independent, whole-head re-review and
exact-head CI (README §14). Until then, `README.md` and `candidate-credibility.md` (M1) govern as merged on `main`.
This branch already carries the governing-text changes and the validator implementation (§6), so the re-review
assesses the complete revision.

**Name.** The rejected draft was "M1-A1". This is **M3**, the next numbered revision after M2 (README §14: revisions are
additive and numbered). No other M3 exists in the repository.

**Origin.** Stage-4 PR-2, owner decisions 2026-10-14 (the redesign and the baseline-identity addendum):
- the plan's Tesseract baseline (OC5) computes as `reference-only` under M1;
- M1 forbids shortlisting `reference-only`;
- plan §4.5 defines a hard D gate against one Tesseract baseline composition, PD_BASE + OC5.

The revision is general. Nothing in it is plate-specific.

## 1. Scope (owner item 3)

- **Prospective only.** M3 is an additive MSR-v1/M1 revision for events not yet at `PROTOCOL_FROZEN` when M3 is accepted. It is not retroactive.
- **Decision v1 only.** It applies to non-S2c events on decision summary **v1**. PR-2 plates (still `PLANNED`) may adopt it once accepted.
- **Decision v2 unchanged.** `mavi-model-selection-decision-v2` stays governed by M2/S2c rules. M3 does not change it:
  - an M3 role is refused in M2 ledgers;
  - an M3 role is refused for S2c capabilities;
  - a v2 decision on a ledger holding the role is refused.

  The shared code path is proven unchanged by tests (§7).

## 2. Definitions

- **Benchmark-only baseline component (BOB):** a third-party candidate whose computed M1 class is **`reference-only`**, with disposition `BENCHMARK_BASELINE` in an `msr-v1-m3` ledger. It is executed and measured solely to define frozen comparative baselines or gates. Example: OC5, Tesseract.
- **Derived gate-only baseline composition:** exactly one BOB plus one ordinary partner component (for example PD_BASE). The partner is resolved mechanically from a frozen finite universe by a frozen rule. The composition is measured only as the frozen comparison for the compositions its protocol names.
- **Implementation candidate / O2:** as README §4. Unchanged.

## 3. Rules

Each rule is marked **NEW** (an M3 normative rule) or **RESTATED** (an existing M1/MSR rule repeated for clarity, not new policy).

1. **NEW: class restriction.**
   - `BENCHMARK_BASELINE` is allowed only for computed class `reference-only`.
   - It is refused for `established`, `emerging`, `excluded-discovery` and `mavi-owned`. Those keep their ordinary routes, so no candidate can be demoted by role to escape the selection rules.
   - It needs reason class `technical`, a stated purpose and the protocol section that freezes it.
2. **NEW: immutable component identity before freeze** (owner item 2). The ledger entry carries:
   - provenance High with every file pinned at an immutable revision: model/trained-data SHA-256;
   - `hostManifests`: per host profile, every executable/native binary and runtime library, with SHA-256 and size;
   - `configurationSha256` (invocation/configuration);
   - `adapterSha256` (adapter/preprocessing);
   - `evaluationPermissions`: per artefact, decision-maker, date and primary-source hash.
3. **NEW: no selection role.** A BOB, and any gate-only composition containing it:
   - is never a shortlist candidate, top-K entry, component finalist, composition candidate, ranked row or frontier member;
   - is never highest task-quality, strongest technical, strongest reported or strongest cleared;
   - is never an incumbent, a technical winner, an implementation candidate or a component.

   Its measurements are reported separately as "benchmark-only baseline — not a selectable candidate".
4. **NEW: two-stage gate-only composition identity** (addendum 2026-10-14).
   - **Stage 1, frozen before scoring** (in the BOB's `compositions` and the protocol):
     - the finite partner universe, with exact identity hashes;
     - the pre-gate layer and its gate-set hash;
     - the partner ranking/tie-break rule and its hash;
     - the derivation rule (for PR-2: the highest-ranked detector passing every frozen Layer-A gate);
     - exactly which compositions the resolved baseline gates.
   - **Stage 2, after the pre-gate layer and strictly before any protected D data is read:** the partner is resolved mechanically and sealed in a resolution record. The record holds:
     - the partner id and identity hash;
     - the ranking-rule hash;
     - the Layer-A result hash;
     - `resolvedAt` before `dExecutionStartedAt`;
     - a record hash.
   - **No choice:** no owner discretion, substitution or late addition.
   - **Stops:** no qualifying partner, or an ambiguous or inconsistent derivation, stops the event. There is then no baseline and no ranking.
   - **What stays fixed:** the component identity (rule 2) is fully pinned before freeze. Only the partner choice is derived, from a universe frozen before freeze.
5. **NEW: outcome.** `BASELINE_SELECTED` can never follow from a BOB. With no ranked candidate past the gates, the outcome is `NO_QUALIFIABLE_CANDIDATE`.
6. **NEW: immutability after freeze.** The BOB set and every field of each BOB (identity, manifests, configuration, adapter, permissions, Stage-1 rules) are fixed, as for shortlisted candidates. A byte or configuration change needs a new frozen identity through a protocol revision or a new event.
7. **RESTATED: credibility.**
   - MAVI measurements never enter the ledger and never change a credibility class (M1 I4, §2).
   - Implementation eligibility still requires `established` (or `mavi-owned`) on the decision date (M1 §8).
   - The emerging-measurement exception and the ban on promotion from MAVI bake-off results are unchanged.
   - New consequence: a BOB promoted out of `reference-only` by later external evidence is refused (rule 1). It must leave the role through a protocol revision or a new event.
8. **RESTATED: timing.** Method amendments apply only to events not yet at `PROTOCOL_FROZEN` (README §14).

## 4. Governing clauses modified (owner item 7)

| Clause | Change | New / restated |
|---|---|---|
| README title | "revisions M1/M2/M3" | — |
| README §3.2 outcomes | a BOB can never produce `BASELINE_SELECTED`; otherwise `NO_QUALIFIABLE_CANDIDATE` | NEW (rule 5) |
| README §4 role list | adds `benchmark-only-baseline` | NEW |
| README §4 disposition diagram | adds `BENCHMARK_BASELINE` | NEW |
| README §5.1 step 2 | "never enter a **ranked** tuple"; a gate-only baseline composition is measured only as the frozen comparison, never a composition candidate, frontier member, finalist or ranked row | NEW (rules 3, 4) |
| README §9 outputs | a separate "Benchmark-only baselines" row; never in any other field | NEW |
| README §14 table, §14.3 | M3 row and summary (§14.2 architecture closure keeps its number) | — |
| M1 §3 class table | `reference-only` admits `BENCHMARK_BASELINE` | NEW |
| M1 §4 | the admitted dispositions include `BENCHMARK_BASELINE` | NEW |
| M1 §4.4 (new) | eligibility, entry block, freeze; restatements marked | NEW + RESTATED |
| M1 §8 | evaluated set = frozen shortlist + frozen BOBs; BOB rows; derivation exclusion; resolution records; `rankedSets` | NEW |
| M1 §9 | review obligations for what v1 cannot represent | NEW |
| M1 §11 | I1 and I6 amended; I13 and I14 added | NEW |
| templates `external-evidence-ledger.md` | disposition enum, `benchmarkBaseline` block, decision row fields, resolution records, `rankedSets` | NEW |
| templates `selection-protocol.md` §4 | Baselines: Stage-1 freeze and Stage-2 resolution | NEW |
| templates `selection-record.md` §2 | a separate benchmark-only table | NEW |
| `credibility.py` | §6 | NEW |

Unchanged:
- the M1 classification rule;
- the shortlist rule for other classes;
- implementation eligibility;
- the licence axis;
- the technical ranking of ranked candidates;
- decision v2 and all M2/S2c rules.

## 5. Trade-off (owner wording)

The amendment permits execution of an otherwise non-shortlistable reference-only artefact solely to establish a
comparative benchmark gate, at the cost of adding a special non-candidate measurement role. It does not weaken
credibility requirements for candidate selection or implementation.

- **Cost:** one more disposition, the pinned per-host manifests, a two-stage resolution record, and review items for what decision v1 cannot represent.
- **Gain:** a plan-mandated comparison floor can be measured honestly, without being misrepresented as a credible, selectable candidate.

## 6. Machine checks (implemented: `tools/qualification/model_selection/credibility.py`)

| Check | Code(s) |
|---|---|
| class restriction | `benchmark_baseline_class` |
| M3 ledgers only; not S2c | `benchmark_baseline_requires_m3`, `m3_scope_unsupported` |
| pinned High provenance | `benchmark_baseline_requires_pinned_provenance` |
| identity block (manifests, configuration, adapter, permissions, Stage-1 rules) | `benchmark_baseline_host_manifest_required`, `benchmark_baseline_manifest_not_sorted_unique`, `benchmark_baseline_permission_required`, `eligible_partners_not_sorted_unique`, `benchmark_baseline_cannot_be_its_own_partner`, `duplicate_composition_id`, `gate_only_composition_id_collides`, `benchmark_baseline_block_without_role` |
| immutability after freeze | `benchmark_baselines_changed_after_freeze`, `frozen_benchmark_baseline_field_changed` |
| evaluated set = shortlist + BOBs | `evaluated_set_differs_from_shortlist` |
| unscored BOB rows on the pinned bytes | `benchmark_baseline_row_scored`, `benchmark_baseline_host_manifest_mismatch`, `evaluated_artefact_differs_from_ledger`, `host_manifests_only_for_benchmark_baseline` |
| derivations, implementation | `benchmark_baseline_in_derived_output` (and exclusion from every `_maximal` domain and from the licence map) |
| top-K / finalists / frontiers | `benchmark_baseline_in_ranked_set`, `ranked_set_member_not_evaluated` (`rankedSets`) |
| outcome | `m3_outcome_requires_no_qualifiable_candidate` |
| Stage-2 resolution | `gate_only_composition_not_frozen`, `baseline_partner_not_in_frozen_universe`, `baseline_ranking_rule_mismatch`, `baseline_resolved_before_freeze`, `baseline_resolved_after_d_started`, `baseline_resolution_record_altered`, `gate_only_composition_unresolved`, `gate_only_composition_resolved_twice` |
| decision v2 | `m3_v2_unsupported` |

**Not machine-checked by this validator (review rules, M1 §9):**
- the partner's Layer-A ordering. It is re-derived and sealed by the event harness: for PR-2, `resolve_baseline` / `verify_resolution` in `tools/benchmarks/capabilities/plates/evaluator.py` on the harness branch;
- ranked compositions, which decision v1 does not represent;
- whether the host manifests cover every library actually loaded.

## 7. Tests

`tools/qualification/tests/test_model_selection_m3.py` has positive and adversarial tests for every rule above. It covers:
- the four refused classes;
- each missing or malformed identity field;
- every post-freeze mutation;
- every derived-output field;
- ranked sets;
- the outcome rule;
- each resolution failure;
- composition-id collisions;
- MAVI-evidence self-promotion;
- a decision v2 refusal, plus proof that a BOB-free v2 call reaches the unchanged v2 path.

It also checks that no committed ledger or decision JSON differs from `origin/main`.

The licence-term tests (`test_model_selection_credibility.py`) add unsupported separators and Unicode look-alikes.
