# MSR method revision M3: benchmark-only baseline component and derived gate-only composition (supersedes draft "M1-A1")

**Status: PROPOSED.** It becomes governing only when merged after a fresh, independent, whole-head re-review and
exact-head CI (README §14). Until then, `README.md` and `candidate-credibility.md` (M1) govern as merged on `main`.
This branch already carries the governing-text changes and the validator implementation (§6), so the re-review
assesses the complete revision.

**Name.** The rejected draft was "M1-A1". This is **M3**, the next numbered revision after M2 (README §14: revisions are
additive and numbered). No other M3 exists in the repository.

**Origin.** Stage-4 PR-2, owner decisions 2026-10-14 (the redesign, the baseline-identity addendum, and the decisions on
the re-review of this revision):
- the plan's Tesseract baseline (OC5) computes as `reference-only` under M1;
- M1 forbids shortlisting `reference-only`;
- plan §4.5 defines a hard D gate against one Tesseract baseline composition, PD_BASE + OC5.

The revision is general. Nothing in it is plate-specific.

## 1. Scope (owner items 3 and 10)

- **Prospective only.** M3 is an additive MSR-v1/M1 revision for events not yet at `PROTOCOL_FROZEN` when M3 is
  accepted. It is not retroactive. Stage-4 PR-2 can adopt it only because PR-2 is still `PLANNED` and unfrozen.
- **Decision v1 only.** It applies to non-S2c events on decision summary **v1**.
- **Decision v2 unchanged.** `mavi-model-selection-decision-v2` stays governed by M2/S2c rules. M3 does not change it:
  - an M3 role is refused in M2 ledgers;
  - an M3 role is refused for S2c capabilities;
  - a v2 decision on a ledger holding the role is refused.

  The shared code path is proven unchanged by tests (§7).
- **Events without a benchmark-only baseline** behave exactly as before: no M3 field is accepted on them, and every
  existing check and outcome rule is unchanged.

## 2. Definitions

- **Benchmark-only baseline component (BOB):** a third-party candidate whose computed M1 class is **`reference-only`**,
  with disposition `BENCHMARK_BASELINE` in an `msr-v1-m3` ledger. It is executed and measured solely to define frozen
  comparative baselines or gates. Example: OC5, Tesseract.
- **Derived gate-only baseline composition:** exactly one BOB plus one ordinary partner component (for example
  PD_BASE). The partner is resolved mechanically from a frozen finite universe by a frozen rule. The composition is
  measured only as the frozen comparison for the compositions its protocol names.
- **Baseline seal:** the committed Stage-2 record of one gate-only composition, status `RESOLVED` or `STOPPED`
  (rule 4a).
- **Implementation candidate / O2:** as README §4. Unchanged.

## 3. Rules

Each rule is marked **NEW** (an M3 normative rule) or **RESTATED** (an existing M1/MSR rule repeated for clarity, not new
policy). A rule that restates an M1 rule and adds an M3 consequence is split, so every new consequence is marked NEW.

1. **NEW: class restriction.**
   - `BENCHMARK_BASELINE` is allowed only for computed class `reference-only`.
   - It is refused for `established`, `emerging`, `excluded-discovery` and `mavi-owned`. Those keep their ordinary
     routes, so no candidate can be demoted by role to escape the selection rules.
   - It needs reason class `technical`, a stated purpose and the protocol section that freezes it.
2. **NEW: immutable component identity before freeze** (owner item 2). The ledger entry carries:
   - provenance High with every file pinned at an immutable revision: model/trained-data SHA-256;
   - `hostManifests`: one per declared target profile, listing every executable/native binary, runtime library and
     data file, with SHA-256 and size;
   - `configurationSha256` (invocation/configuration);
   - `adapterSha256` (adapter/preprocessing);
   - `evaluationPermissions`, bound **per exact artefact** (review P3): one decision for the executables, one for the
     runtime libraries/dependencies (when there are any) and one for the model/trained data. Each lists the exact
     SHA-256 values it covers, with decision-maker, date and primary-source hash. Together they cover exactly the
     pinned identity files and every host-manifest file. A single vague "all" permission is refused.
3. **NEW: no selection role.** A BOB, and any gate-only composition containing it, is never:
   - shortlisted (it keeps its `BENCHMARK_BASELINE` disposition);
   - a candidate, a top-K entry, a component finalist, an ordinary composition candidate or a component of one;
   - a ranked row, a ranked composition or a Pareto/frontier/non-dominated member;
   - the technical winner, the strongest evaluated technical candidate or composition, the highest task-quality
     candidate, the strongest reported candidate or the strongest cleared candidate;
   - the incumbent, the implementation candidate or a component of the implementation;
   - the subject of `BASELINE_SELECTED`.

   It gets no credibility promotion from MAVI measurements (rule 7a). Its measurements are reported separately as
   "benchmark-only baseline — not a selectable candidate". Every exclusion is machine-checked on a mandatory decision
   block (rule 9), never on an optional author-provided field.
4. **NEW: two-stage gate-only composition identity** (addendum 2026-10-14).
   - **Stage 1, frozen before scoring**, in the BOB's ledger entry (`compositions[]`) and the protocol:
     - the partner event (`partnerEventId`);
     - the finite partner universe (`eligiblePartners`), with exact identity hashes;
     - the pre-gate layer's gate ids (`layerAGateIds`) and gate-set hash;
     - the partner ranking/tie-break rule hash;
     - the derivation rule, as an enumerated machine rule: `highest-ranked-partner-passing-every-layer-a-gate`;
     - the gate scope, as an enumerated machine rule: `all-ordinary-compositions` (every ordinary composition of the
       event is gated by the resolved baseline).
   - **Stage 2, after the pre-gate layer and strictly before any protected D data is read:** the partner is resolved
     mechanically from the committed Layer-A result and written as the committed baseline seal (rule 4a).
   - **No choice:** no owner discretion, substitution or late addition. A partner from another event must be
     shortlisted there with the frozen identity; a partner from the same event must be shortlisted in this ledger.
   - **What stays fixed:** the component identity (rule 2) is fully pinned before freeze. Only the partner choice is
     derived, from a universe frozen before freeze.
4a. **NEW: the committed pre-D seal** (owner decision 3, P1-2; owner decision 4, P2-1).
   - Two canonical-JSON files sit beside the event's MSR files:
     - `<event-id>-layer-a-<compositionId>.json`, `mavi-model-selection-layer-a-result-v1`: per eligible partner, its
       exact identity, every frozen Layer-A gate result and its rank key under the frozen rule;
     - `<event-id>-baseline-seal-<compositionId>.json`, `mavi-model-selection-baseline-seal-v1`.
   - A **RESOLVED** seal holds: event id; capability id; protocol SHA-256 and frozen-ledger SHA-256 (the freeze
     identity); eligible-universe hash; Stage-1 rule hash; the resolved partner (PD_BASE) id and exact identity hash;
     the benchmark component (OC5) exact identity hash; the Layer-A result hash; the Layer-A gate-set hash; the
     ranking/tie-break rule hash; the partner event id and its frozen-ledger hash; the gate scope; the derived
     composition hash; status `RESOLVED`; `protectedDState: NOT_STARTED`; and `recordedAt`/`recordedBy` for audit.
   - It holds **no self-hash**. Its identity is its canonical SHA-256. It is valid only if it equals, field for field,
     what the frozen rule re-derives from the frozen ledger, the protocol hash, the partner event's frozen ledger and
     the committed Layer-A result. Re-sealing to another partner therefore needs a different Layer-A result.
   - **Ordering is proven by hashes, not by timestamps.** The event record carries the seal hash. Every protected D
     manifest and result, the BOB's decision row and every ordinary composition's D result carry it, so none of them
     can exist before the seal. Once any of them exists, a changed seal no longer matches what it recorded and is
     refused. That makes the resolution immutable once D has started.
   - **Harness obligation** (README §14.3): before reading protected D data, call `require_committed_baseline_seal`,
     which verifies the committed, unmodified, record-cited, RESOLVED seal against its frozen inputs. Record the seal
     hash and the seal's Git commit in every protected D manifest and result. Check each with
     `verify_d_manifest_binding` before scoring.
5. **NEW: outcome invariance** (owner decision 1, P2-4). A benchmark-only baseline has zero influence on the event
   outcome. Every BOB row and gate-only composition is removed from every domain before the outcome is derived; the
   ordinary M1 outcome rules then apply unchanged:
   - `INCUMBENT_RETAINED` and `SELECTED_FOR_PACKAGING` stay valid wherever ordinary M1 produces them;
   - `BASELINE_SELECTED` refers only to the ordinary, packageable (`mavi-owned`) M1 baseline, never a BOB;
   - `NO_QUALIFIABLE_CANDIDATE` follows only where ordinary M1 yields it. M3 adds no rule such as "no
     implementation-eligible candidate means `NO_QUALIFIABLE_CANDIDATE`".

   This replaces the earlier draft's "with no ranked candidate past the gates the outcome is
   `NO_QUALIFIABLE_CANDIDATE`", which made the outcome depend on whether a BOB was present.
6. **NEW: immutability after freeze.** The BOB set and every field of each BOB (identity, manifests, configuration,
   adapter, permissions, disposition, Stage-1 rules) are fixed, as for shortlisted candidates. A byte or configuration
   change needs a new frozen identity through a protocol revision or a new event. A seal is immutable once written
   (rule 4a).
7. **RESTATED: credibility** (M1 I4, §2, §8).
   - (a) MAVI measurements never enter the ledger and never change a credibility class.
   - (b) Implementation eligibility still requires `established` (or `mavi-owned`) on the decision date. The
     emerging-measurement exception and the ban on promotion from MAVI bake-off results are unchanged.
7c. **NEW: consequence for a BOB.** A BOB promoted out of `reference-only` by later external evidence is refused
   (rule 1). It must leave the role through a protocol revision or a new event.
8. **RESTATED: timing.** Method amendments apply only to events not yet at `PROTOCOL_FROZEN` (README §14).
9. **NEW: STOPPED baseline resolution and the mandatory decision block** (owner decisions 2 and 6, P2-5 and P2-3).
   - When the deterministic Stage-2 resolution cannot produce a valid baseline, a **STOPPED** seal is committed
     instead. That covers: no eligible partner passing every frozen Layer-A gate; a missing or inconsistent partner
     event or universe; identities that do not reconcile; an ambiguous (tied) derivation; resolution after protected
     D access; any other failed frozen prerequisite.
   - A STOPPED seal records the exact stop reason (an enumerated code), a detail text and the evidence hashes. It
     names no partner and no composition, so it cannot name a replacement baseline. It permits no D execution, holds
     no ranked D result, and is immutable once written. A later protocol revision re-freezes the gate-only
     composition under a new composition id; the STOPPED seal stays as history, cited by the record.
   - A STOPPED seal does **not** fix the event state or outcome. The governing event protocol does. For Stage-4 PR-2,
     N9 applies: a pre-D stop returns to, or stays at, `PLANNED` for owner action, and no `NO_QUALIFIABLE_CANDIDATE`
     is fabricated. If the owner later closes the event, the ordinary M1 outcome rules (rule 5) decide the outcome.
   - A decision summary v1 on an event with a BOB carries the mandatory block `benchmarkOnlyBaselines`: the seals (by
     hash and status), the one event-level D start, the incumbent, top-K, component finalists, every ordinary
     composition candidate with its hard-gate results and seal hashes, the ranked compositions, the frontier and the
     strongest evaluated composition. With a STOPPED seal it records no D start and no composition result.

## 4. Governing clauses modified (owner item 7)

| Clause | Change | New / restated |
|---|---|---|
| README title | "revisions M1/M2/M3" | — |
| README §2 carve-out | evaluation permission of a BOB is a precondition to its measurement, recorded per artefact; it never makes a BOB a candidate | NEW (rule 2) |
| README §3.2 `PROTOCOL_FROZEN` | the protocol names each BOB identity and Stage-1 rule; Stage 2 commits the seal before protected D data is read | NEW (rules 2, 4, 4a) |
| README §3.2 outcomes | the outcome is the ordinary M1 outcome with every BOB removed; `BASELINE_SELECTED` never refers to a BOB | NEW (rule 5) |
| README §4 role list, disposition diagram | `benchmark-only-baseline`, `BENCHMARK_BASELINE` | NEW |
| README §5.1 steps 1-5 | a packageable baseline may be a finalist; a BOB never; gate-only compositions are never generated, ranked, on a frontier or chosen | NEW (rule 3) |
| README §9 outputs | a separate "Benchmark-only baselines" row; never in any other field | NEW |
| README §11 | seals are immutable files, never edited after D | NEW (rules 4a, 6) |
| README §14 table, §14.3 | M3 row in the table; the summary and the harness obligation | — |
| M1 §3 class table | `reference-only` admits `BENCHMARK_BASELINE` | NEW |
| M1 §4 | admitted dispositions include `BENCHMARK_BASELINE`; licence-phrase normalisation | NEW |
| M1 §4.4 | eligibility, identity, per-artefact permissions, Stage-1 rule; restatements marked | NEW + RESTATED |
| M1 §7 | BOB freeze; seals immutable | NEW |
| M1 §8 | evaluated set = frozen shortlist + frozen BOBs; BOB rows; mandatory M3 block; seal verification; outcome invariance | NEW |
| M1 §9 | review obligations that remain | NEW |
| M1 §11 | I1 and I6 amended; I13 to I15 added | NEW |
| templates `external-evidence-ledger.md` | disposition enum, `benchmarkBaseline` block, decision M3 block, Layer-A and seal files | NEW |
| templates `selection-protocol.md` §4 | Baselines: Stage-1 freeze, Stage-2 seal, STOPPED | NEW |
| templates `selection-record.md` §2 | a separate benchmark-only table with seal hashes | NEW |
| `credibility.py`, `baseline_seal.py`, schemas | §6 | NEW |

Unchanged:
- the M1 classification rule;
- the shortlist rule for other classes;
- implementation eligibility;
- the licence axis (only the plate-domain phrase detection is hardened, §6);
- the technical ranking of ranked candidates;
- the M1 outcome rules;
- decision v2 and all M2/S2c rules.

## 5. Trade-off (owner wording)

The amendment permits execution of an otherwise non-shortlistable reference-only artefact solely to establish a
comparative benchmark gate, at the cost of adding a special non-candidate measurement role. It does not weaken
credibility requirements for candidate selection or implementation.

- **Cost:** one more disposition; pinned per-profile manifests and per-artefact permissions; two committed files per
  gate-only composition (Layer-A result and seal); a mandatory decision block; a harness obligation before D.
- **Gain:** a plan-mandated comparison floor can be measured honestly, without being misrepresented as a credible,
  selectable candidate, and its identity cannot be changed after D without a hard refusal.

## 6. Machine checks (implemented: `tools/qualification/model_selection/credibility.py` and `baseline_seal.py`)

| Check | Code(s) |
|---|---|
| class restriction | `benchmark_baseline_class` |
| M3 ledgers only; not S2c | `benchmark_baseline_requires_m3`, `m3_scope_unsupported` |
| pinned High provenance | `benchmark_baseline_requires_pinned_provenance` |
| identity block | `benchmark_baseline_host_manifest_required`, `benchmark_baseline_manifest_not_sorted_unique`, `benchmark_baseline_block_without_role` |
| per-artefact permissions | `benchmark_baseline_permission_required`, `benchmark_baseline_permission_kind_duplicate`, `benchmark_baseline_permission_not_sorted_unique`, `benchmark_baseline_permission_not_bound` |
| Stage-1 rule | `eligible_partners_not_sorted_unique`, `benchmark_baseline_cannot_be_its_own_partner`, `layer_a_gates_not_sorted_unique`, `duplicate_composition_id`, `gate_only_composition_id_collides`; enumerated `derivationRule` and `gateScope` |
| partner universe | `baseline_partner_not_in_partner_shortlist`, `baseline_partner_event_mismatch`, `baseline_partner_event_missing` |
| immutability after freeze | `benchmark_baselines_changed_after_freeze`, `frozen_benchmark_baseline_field_changed` |
| Layer-A result | `layer_a_result_not_for_this_composition`, `layer_a_partner_outside_frozen_universe`, `layer_a_identity_mismatch`, `layer_a_gates_mismatch`, `layer_a_rank_key_malformed`, `layer_a_rank_ambiguous`, `layer_a_result_inconsistent_with_frozen_universe`, `baseline_ranking_rule_mismatch` |
| seal (RESOLVED) | `baseline_seal_differs_from_frozen_inputs`, `baseline_seal_partner_not_derived`, `baseline_seal_not_derivable`, `baseline_seal_d_state_contradicted`, `baseline_resolved_before_freeze` |
| seal (STOPPED) | `baseline_stop_evidence_required`, `baseline_stop_reason_contradicted`; no partner field (`unknown_field`) |
| repository mode | `baseline_seal_not_canonical`, `layer_a_result_not_canonical`, `baseline_seal_not_recorded`, `baseline_artefact_without_frozen_composition` |
| harness API | `baseline_seal_missing`, `baseline_seal_not_committed`, `baseline_seal_stopped_no_d`, `d_manifest_baseline_seal_mismatch`, `baseline_seal_git_unavailable` |
| evaluated set = shortlist + BOBs | `evaluated_set_differs_from_shortlist` |
| unscored BOB rows on the pinned bytes | `benchmark_baseline_row_scored`, `benchmark_baseline_host_manifest_mismatch`, `benchmark_baseline_host_profiles_differ_from_target_profiles`, `benchmark_baseline_row_seal_mismatch`, `evaluated_artefact_differs_from_ledger`, `host_manifests_only_for_benchmark_baseline` |
| derivations, implementation, incumbent | `benchmark_baseline_in_derived_output` (and exclusion from every `_maximal` domain and from the licence map) |
| mandatory M3 block | `missing_field`, `m3_decision_requires_baseline_evidence`, `gate_only_composition_unresolved`, `gate_only_composition_resolved_twice`, `gate_only_composition_not_frozen`, `decision_baseline_seal_mismatch` |
| D start | `baseline_resolved_after_d_started`, `d_started_after_decision`, `baseline_stopped_d_started`, `baseline_stopped_no_d_result` |
| top-K, finalists, frontier, ranked compositions | `benchmark_baseline_in_ranked_set`, `ranked_set_member_not_evaluated`, `ranked_set_not_unique`, `ranked_compositions_not_derived`, `strongest_composition_not_derived`, `frontier_member_not_passing`, `incumbent_not_evaluated` |
| composition candidates and the hard-gate mapping | `benchmark_baseline_in_composition_candidate`, `composition_component_not_in_partner_shortlist`, `composition_component_identity_mismatch`, `composition_component_event_not_declared`, `composition_component_not_evaluated`, `composition_components_invalid`, `composition_hard_gate_mapping_invalid`, `composition_failed_hard_gate_ranked`, `d_result_baseline_seal_mismatch`, `composition_id_collides` |
| outcome | none: the ordinary M1 outcome rules, with every BOB removed (rule 5) |
| decision v2 | `m3_v2_unsupported` |

**Licence-phrase detection (M1 validator amendment, owner decision 9).** The plate-domain phrase exemption now runs on
NFKC/case-folded text with combining marks and invisible format characters removed and Unicode dashes and spaces
folded. It exempts the phrase only when "license/licence" is the noun modifier of "plate": a preceding licensing prefix
(`sub`, `re`, `cross`, `un`, `co`, `non`, ...) or verb context (`to`, `may`, `not`, `we`, `and`, ...) keeps it refused.
The remainder is folded through a small Cyrillic/Greek confusable table before "licen" is searched.

**Not machine-checked (review rules, M1 §9):**
- that the Layer-A rank keys were computed by the frozen ranking rule from the Layer-A measurements. The validator
  checks the derivation from the keys; the harness that writes the Layer-A result is bound by the rule hash;
- that the Layer-A result was committed before the seal and the seal before protected D data was read, beyond what the
  hash chain proves (rule 4a). The harness check (`require_committed_baseline_seal`) proves it at D time; a later
  coordinated rewrite of the Layer-A result, the seal, the record, the decision and every D manifest is a Git-review
  item, as for every M1 frozen file;
- that the Git commit cited by a D manifest predates the D run;
- whether the host manifests cover every library actually loaded;
- licence paraphrases and confusables outside the folded table.

## 7. Tests

`tools/qualification/tests/test_model_selection_m3.py` has positive and adversarial tests for every rule above,
including:
- the four refused classes; each missing or malformed identity, permission or Stage-1 field;
- every post-freeze mutation;
- every derived-output field, ranked set, composition-candidate intrusion and hard-gate mapping defect;
- the reviewer's re-seal attack (seal PD-A, bind D, reseal to PD-B with a recomputed hash), in decision, repository and
  Git-bound harness form;
- every seal field (P2-1), every Layer-A reconciliation defect, every STOPPED reason;
- outcome invariance: adding or removing an otherwise identical BOB (resolved or stopped) never changes the M1
  verdict for thirteen ordinary M1 decisions, valid and invalid;
- a decision v2 refusal, plus proof that a BOB-free v2 call reaches the unchanged v2 path;
- the published JSON schemas accept the derived seals and Layer-A results.

It also checks that no committed ledger or decision JSON differs from `origin/main`. The licence-term tests
(`test_model_selection_credibility.py`) cover the prefix, spaced, hyphenated, plural, zero-width, fullwidth and Unicode
dash forms.
