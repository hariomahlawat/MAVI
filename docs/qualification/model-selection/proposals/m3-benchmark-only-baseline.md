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
  existing check and outcome rule is unchanged. The one global obligation is that repository verification now
  always needs full Git history (`candidate-credibility.md` §7), so the Task-17 job checks out full history too.

## 2. Definitions

- **Benchmark-only baseline component (BOB):** a third-party candidate whose computed M1 class is **`reference-only`**,
  with disposition `BENCHMARK_BASELINE` in an `msr-v1-m3` ledger. It is executed and measured solely to define frozen
  comparative baselines or gates. Example: OC5, Tesseract.
- **Composition group:** the two component events (for PR-2 the plate detector and the recogniser) whose frozen
  ledgers carry one identical `compositionUniverse`; its canonical SHA-256 is the group id.
- **Derived gate-only baseline composition:** exactly one BOB plus one ordinary partner component (for example
  PD_BASE) from the other group event. The partner is resolved mechanically from a frozen finite universe by a frozen
  rule. The composition is measured only as the frozen `baseline` hard gate for every ordinary composition.
- **Ordinary composition set U:** derived from the frozen universe and the committed component rankings (rule 4a),
  sealed before protected D.
- **Baseline seal:** the committed Stage-2 record of the group's gate-only composition and U, status `RESOLVED` or
  `STOPPED` (rule 4a).
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
     data file, each with its declared `kind`, SHA-256 and size;
   - `configurationSha256` (invocation/configuration);
   - `adapterSha256` (adapter/preprocessing);
   - `evaluationPermissions`, bound **per exact artefact** (review P3): one decision for the executables, one for the
     runtime libraries/dependencies (when there are any) and one for the model/trained data. Each lists the exact
     SHA-256 values it covers, with decision-maker, date and primary-source hash, and covers exactly the manifest
     files of its kind (model data: the pinned identity files plus every `data` file). A single vague "all"
     permission is refused, and so is a data file filed as an executable.
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
4. **NEW: two-stage gate-only composition identity inside a composition group** (addendum 2026-10-14; authority
   redesign 2026-10-16).
   - **The composition group.** Every `msr-v1-m3` event is one of exactly two component events whose frozen ledgers
     carry one identical `compositionUniverse` (owner decision O3 for its tie rule): per event the ranking layer, `k`,
     the ranking gate ids and a machine ranking rule (`lexicographic-v1` over named metrics); for the group the
     composition gate ids (always including `baseline`) and the MPID; `includePackageableBaselines: true`. The group
     holds exactly one BOB with exactly one gate-only composition.
   - **Stage 1, frozen before scoring**, in the BOB's ledger entry (`compositions[]`) and the protocol: the partner
     event (the other group member), the finite partner universe (`eligiblePartners`, exact identity hashes),
     `excludedPartners` (every other shortlisted candidate of the partner event, with identity and recorded reason, so
     the universe is the partner shortlist exactly), the derivation rule
     (`highest-ranked-partner-passing-every-layer-a-gate`) and the gate scope (`all-ordinary-compositions`). The
     partner's ranking gates and ranking rule are its entry in `compositionUniverse`.
   - **Stage 2, after layers A/B and strictly before any protected D data is read:** each event commits its component
     ranking; PD_BASE and the ordinary composition set U are derived mechanically and written as the committed seal
     (rule 4a).
   - **No choice:** no owner discretion, substitution or late addition, and no author-listed composition set.
   - **What stays fixed:** the component identity (rule 2) and the universe are fully pinned before freeze. Only the
     partner and U are derived, from inputs frozen before freeze and rankings committed before the seal.
4a. **NEW: the committed component rankings and the pre-D seal** (owner decisions 3 and 4; authority redesign).
   - `<event-id>-component-ranking.json` (`mavi-model-selection-component-ranking-v1`), per group event: the frozen
     shortlist exactly, each row with its identity, every frozen ranking-gate result, its **metrics** and
     `measurementSha256`. The rank key is derived by the validator from the metrics; an authored key is refused. Top-K
     is the first `k` passing candidates; a tie across the `k` boundary is a STOP (owner decision O3).
   - `<bob-event-id>-baseline-seal-<compositionId>.json` (`mavi-model-selection-baseline-seal-v1`). A **RESOLVED**
     seal holds the event and capability ids; the protocol and frozen-ledger hashes; the Stage-1 rule and
     eligible-universe hashes; the partner's ranking-gate and ranking-rule hashes; the BOB's exact identity hash; the
     partner event id and frozen-ledger hash; the universe hash; both component-ranking hashes; the resolved partner
     and its identity hash; the derived composition hash; the hash of U; the gate scope; `protectedDState:
     NOT_STARTED`; and `recordedAt`/`recordedBy`. It holds no self-hash and is valid only if it equals, field for
     field, the re-derivation.
   - **U** is the cartesian product over the two events of (top-K ∪ packageable `mavi-baseline` candidates), tuples
     ordered by event id, ids derived as `C-<candidate>--<candidate>` (candidate ids never contain `--`, so an id
     decodes to one tuple). A BOB is never in U.
   - **Chronology and publication (the clock is the protected default branch, not local Git).** Freeze ≺ rankings ≺
     seal, strictly by ancestry; the seal is merged to `main`; protected D opens only through `open_protected_d`,
     which verifies the protected default branch (owner decision O2) and the live anchor on the canonical repository
     (README §14.3 step 5); every D manifest and decision records `anchorCommit`, re-verified in repository mode.
   - Each ranking and the seal are cited on exactly one structured record line equal to the file; the files are
     add-only and the record lines append-only over the whole reachable history (`candidate-credibility.md` §7).
5. **NEW: outcome rule** (owner decision 1, P2-4; restated by the redesign). A BOB is never a candidate and never
   appears in any candidate, ranked, derived or outcome field; every BOB row and the gate-only composition are removed
   from every domain, and the ordinary M1 outcome rules apply unchanged to the composition-derived rows. The BOB
   influences the outcome only through the plan-mandated `baseline` hard gate on end-to-end compositions (plan §4.5),
   which is never compensated:
   - `INCUMBENT_RETAINED` and `SELECTED_FOR_PACKAGING` stay valid wherever ordinary M1 produces them on those rows;
   - `BASELINE_SELECTED` refers only to the ordinary, packageable (`mavi-owned`) M1 baseline, never a BOB;
   - a STOPPED group has no decision and no outcome, and an abandoned group (O4) has none either (rule 9);
   - `NO_QUALIFIABLE_CANDIDATE` follows only where ordinary M1 yields it. M3 adds no rule such as "no
     implementation-eligible candidate means `NO_QUALIFIABLE_CANDIDATE`".

   This replaces the earlier "adding or removing a BOB never changes the M1 verdict" statement: with the composition
   gate now bound to every ordinary row (P1-1), a BOB whose baseline composition is strong can fail candidates
   through that gate, which is exactly the plan's intent.
6. **NEW: immutability after freeze.** The BOB set, every field of each BOB, `compositionUniverse` and `supersedes`
   are fixed. A byte or configuration change needs a new frozen identity through a new event. The rankings, the seal
   and the D manifests are immutable once written (rule 4a); an M3 event's frozen ledger and protocol are never
   revised in place (rule 9).
7. **RESTATED: credibility** (M1 I4, §2, §8).
   - (a) MAVI measurements never enter the ledger and never change a credibility class.
   - (b) Implementation eligibility still requires `established` (or `mavi-owned`) on the decision date. The
     emerging-measurement exception and the ban on promotion from MAVI bake-off results are unchanged.
7c. **NEW: consequence for a BOB.** A BOB promoted out of `reference-only` by later external evidence is refused
   (rule 1). It must leave the role through a new event.
8. **RESTATED: timing.** Method amendments apply only to events not yet at `PROTOCOL_FROZEN` (README §14).
9. **NEW: STOPPED, revision, abandonment and the mandatory decision block** (owner decisions O1, O4, O6; the single
   normative statement of STOPPED and supersession is README §14.3, which this rule does not repeat).
   - When the deterministic Stage-2 resolution cannot produce a valid baseline, a **STOPPED** seal is committed: no
     eligible partner passing every ranking gate; a missing or inconsistent partner event, universe or ranking;
     identities that do not reconcile; a partner tie; a tie across a top-K boundary; resolution after protected D
     access; any other failed frozen prerequisite. It records an enumerated reason, a detail and the evidence hashes;
     it cannot record a supplied (committed) input as absent, and with every input supplied its reason must be the
     derived one; a protected-D-access stop records `protectedDAccessedAt`. It names no partner, no composition and
     no U.
   - A STOPPED group is terminal: no protected D, no decision of any kind, no outcome; revision is by new events that
     `supersede` the stopped ones and remain M3 with the baseline gate (README §14.3).
   - If the baseline D result cannot be evaluated after protected D opened, no technical decision is recorded and the
     group moves to `ABANDONED` by an identical record line in every group event that cites a committed D result
     (README §14.3).
   - Each group event's decision summary v1 carries the identical mandatory block `compositionAuthority`
     (`candidate-credibility.md` §8): the derived set U with recomputed gates and scores, the ranking, the frontier,
     the strongest and the implementation composition, top-K and finalists as diagnostics, the seal by hash and S0,
     the anchor and the D start.

## 4. Governing clauses modified (owner item 7)

| Clause | Change | New / restated |
|---|---|---|
| README title | "revisions M1/M2/M3" | — |
| README §2 carve-out | evaluation permission of a BOB is a precondition to its measurement, recorded per artefact; it never makes a BOB a candidate | NEW (rule 2) |
| README §3.2 `PROTOCOL_FROZEN`, `EVALUATING` | the protocol names the composition universe, the BOB identity and its Stage-1 rule; rankings, then the seal, are committed, published and anchored before protected D; STOPPED is terminal (§14.3) | NEW (rules 2, 4, 4a, 9) |
| README §3.2 outcomes | the outcome is the ordinary M1 outcome over the composition-derived rows with every BOB removed; `BASELINE_SELECTED` never refers to a BOB; STOPPED and abandoned groups have no outcome | NEW (rule 5) |
| README §4 role list, disposition diagram | `benchmark-only-baseline`, `BENCHMARK_BASELINE` | NEW |
| README §5.1 steps 1-5 | a packageable baseline may be a finalist; a BOB never; the ordinary composition set is derived and sealed; gate-only compositions are never generated, ranked, on a frontier or chosen | NEW (rules 3, 4a) |
| README §9 outputs | a separate "Benchmark-only baselines" row; never in any other field | NEW |
| README §11 | rankings, seals and D manifests are immutable; M3 frozen files are never revised in place | NEW (rules 4a, 6, 9) |
| README §14 table, §14.3 | M3 row in the table; the authority flow, the single STOPPED/supersession/abandonment rule and the harness obligation | — |
| M1 §3 class table | `reference-only` admits `BENCHMARK_BASELINE` | NEW |
| M1 §4 | admitted dispositions include `BENCHMARK_BASELINE`; licence-phrase normalisation | NEW |
| M1 §4.4 | eligibility, identity, manifest hygiene, per-artefact permissions, the composition group, Stage-1 rule, R1; restatements marked | NEW + RESTATED |
| M1 §7 | BOB and universe freeze; the full-history requirement and the sticky audit, stated once | NEW |
| M1 §8 | evaluated set = frozen shortlist + frozen BOBs; BOB rows; group artefacts; mandatory `compositionAuthority` block; composition-derived rows; outcome rule | NEW |
| M1 §9 | review obligations that remain | NEW |
| M1 §11 | I1 and I6 amended; I13 to I15 added | NEW |
| templates `external-evidence-ledger.md` | disposition enum, `compositionUniverse`, `benchmarkBaseline` block, decision M3 block, ranking, seal and D-manifest files | NEW |
| templates `selection-protocol.md` §4 | Baselines: universe and Stage-1 freeze, rankings, seal, publication, STOPPED, abandonment | NEW |
| templates `selection-record.md` §2 | a separate benchmark-only table with seal hashes | NEW |
| `credibility.py`, `m3_universe.py`, `baseline_seal.py`, `m3_authority.py`, `m3_git.py`, schemas | §6 | NEW |

Unchanged:
- the M1 classification rule;
- the shortlist rule for other classes;
- implementation eligibility;
- the licence axis (only the plate-domain phrase detection is hardened, §6);
- the technical ranking of ranked candidates;
- the M1 outcome rules (they now read composition-derived rows for M3 group events, rule 5);
- decision v2 and all M2/S2c rules.

## 5. Trade-off (owner wording)

The amendment permits execution of an otherwise non-shortlistable reference-only artefact solely to establish a
comparative benchmark gate, at the cost of adding a special non-candidate measurement role. It does not weaken
credibility requirements for candidate selection or implementation.

- **Cost:** one more disposition; pinned per-profile manifests and per-artefact permissions; a frozen composition
  universe shared by both events; two component rankings, one seal and one D manifest per run, each committed in
  order; a mandatory decision block; full Git history for repository verification; a network check against the
  canonical repository and its ruleset before protected D (Development qualification only).
- **Gain:** a plan-mandated comparison floor can be measured honestly, without being misrepresented as a credible,
  selectable candidate, and its identity cannot be changed after D without a hard refusal.

## 6. Machine checks (implemented: `credibility.py`, `m3_universe.py`, `baseline_seal.py`, `m3_authority.py`, `m3_git.py`)

| Check | Code(s) |
|---|---|
| class restriction | `benchmark_baseline_class` |
| M3 ledgers only; not S2c | `benchmark_baseline_requires_m3`, `m3_scope_unsupported` |
| pinned High provenance | `benchmark_baseline_requires_pinned_provenance` |
| identity block and manifest hygiene | `benchmark_baseline_host_manifest_required`, `benchmark_baseline_manifest_not_sorted_unique`, `benchmark_baseline_block_without_role`, `benchmark_baseline_profile_without_executable`, `benchmark_baseline_hash_kind_conflict`, `benchmark_baseline_identity_file_not_data`, `benchmark_baseline_identity_file_not_in_manifest` |
| per-artefact permissions | `benchmark_baseline_permission_required`, `benchmark_baseline_permission_kind_duplicate`, `benchmark_baseline_permission_not_sorted_unique`, `benchmark_baseline_permission_not_bound` |
| composition group | `m3_requires_composition_universe`, `composition_universe_requires_m3`, `composition_universe_events_invalid`, `composition_universe_excludes_own_event`, `composition_universe_subtask_outside_event`, `composition_universe_k_invalid`, `ranking_gates_not_sorted_unique`, `ranking_rule_keys_invalid`, `composition_gates_invalid`, `composition_universe_mpid_invalid`, `composition_universe_must_include_packageable_baselines`, `composition_universe_requires_one_baseline`, `composition_universe_differs_between_events`, `m3_group_member_missing` |
| Stage-1 rule and partner | `eligible_partners_not_sorted_unique`, `benchmark_baseline_cannot_be_its_own_partner`, `excluded_partners_not_sorted_unique_disjoint`, `duplicate_composition_id`, `gate_only_composition_id_collides`, `benchmark_baseline_without_gate`, `baseline_partner_event_not_in_group`, `baseline_partner_not_in_partner_shortlist`, `baseline_partner_universe_not_the_shortlist`, `baseline_partner_event_mismatch`, `benchmark_baseline_bytes_as_partner`, `gate_scope_listed_compositions_disabled`; inside the seal derivation `baseline_partner_event_missing`, `baseline_partner_not_in_group`, `partner_rank_ambiguous` become STOP reasons |
| R1 (owner decision O7) | `benchmark_baseline_bytes_in_ordinary_candidate` |
| immutability after freeze | `benchmark_baselines_changed_after_freeze`, `frozen_benchmark_baseline_field_changed`, `frozen_ledger_scope_changed` (universe, supersedes) |
| component ranking | `component_ranking_not_for_this_event`, `component_ranking_universe_mismatch`, `component_ranking_rule_mismatch`, `component_ranking_candidate_not_shortlisted`, `component_ranking_identity_mismatch`, `component_ranking_gates_mismatch`, `component_ranking_metrics_mismatch`, `component_ranking_not_the_shortlist`, `component_rank_ambiguous`, `component_ranking_not_canonical`, `component_ranking_not_recorded`, `component_ranking_cited_twice`, `component_ranking_cited_without_file`, `component_ranking_without_universe` |
| seal (RESOLVED) | `baseline_seal_differs_from_frozen_inputs`, `baseline_seal_partner_not_derived`, `baseline_seal_not_derivable`, `baseline_seal_d_state_contradicted`, `baseline_resolved_before_freeze`, `baseline_seal_composition_mismatch` |
| seal (STOPPED) | `baseline_stop_evidence_required`, `baseline_stop_reason_contradicted`; no partner, composition or U field (`unknown_field`) |
| repository files | `baseline_seal_not_canonical`, `baseline_seal_not_recorded`, `baseline_seal_cited_twice`, `baseline_seal_cited_without_file`, `baseline_artefact_without_frozen_composition`, `legacy_layer_a_artefact`, `d_manifest_location_mismatch`, `m3_artefact_without_group`, `m3_artefact_name_invalid`, `m3_artefact_location_mismatch` |
| history (A1-A6) | `model_selection_history_unavailable` (absent, shallow, grafts), `m3_event_erased`, `m3_frozen_file_rewritten`, `baseline_artefact_rewritten_in_history`, `baseline_artefact_deleted_in_history`, `m3_record_line_removed`, `artefact_first_add_ambiguous`, `artefact_not_committed`, `git_command_failed`, `git_object_missing` |
| chronology (D1) | `m3_chronology_violated`, `m3_chronology_unproven`, `baseline_seal_not_committed` |
| pre-D gate (B, D2, O2) | `d_not_authorised`, `composition_group_unknown`, `protected_default_branch_unverified`, `protected_default_branch_unverifiable`, `anchor_unavailable`, `seal_not_published`, `anchor_not_in_head`, `group_state_differs_from_anchor`, `group_state_not_clean` |
| D manifests and recorded anchors (D3) | `d_manifest_not_canonical`, `d_artefact_group_mismatch`, `d_artefact_universe_mismatch`, `d_manifest_baseline_seal_mismatch`, `baseline_stopped_no_d_result`, `anchor_precedes_seal`, `anchor_not_in_head`, `d_artefact_not_after_anchor`, `anchor_unverifiable` |
| STOPPED and revision (O1, O6) | `baseline_stopped_decision_refused`, `stopped_event_not_superseded`, `supersedes_target_missing`, `supersedes_frozen_ledger_mismatch`, `supersedes_target_not_stopped`, `supersedes_target_has_d_or_decision`, `superseded_record_line_missing`, `superseded_line_without_superseding_event`, `event_superseded_twice`, `supersedes_event_invalid`, `supersedes_seals_invalid` |
| abandonment (O4) | `baseline_d_unavailable`, `abandonment_reason_not_allowed`, `abandonment_without_protected_d`, `group_abandonment_incomplete`, `event_abandoned_decision_refused` |
| evaluated set and BOB rows | `evaluated_set_differs_from_shortlist`, `benchmark_baseline_row_scored`, `benchmark_baseline_host_manifest_mismatch`, `benchmark_baseline_host_profiles_differ_from_target_profiles`, `benchmark_baseline_row_seal_mismatch`, `evaluated_artefact_differs_from_ledger`, `host_manifests_only_for_benchmark_baseline` |
| decision block (C2-C6) | `missing_field`, `m3_decision_requires_group_authority`, `gate_only_composition_unresolved`, `decision_baseline_seal_mismatch`, `decision_baseline_composition_mismatch`, `baseline_resolved_after_d_started`, `d_started_after_decision`, `composition_set_differs_from_sealed_universe`, `composition_components_not_derived`, `composition_hard_gate_mapping_invalid`, `composition_baseline_gate_not_derived`, `composition_technical_gates_not_derived`, `composition_score_not_derived`, `d_result_baseline_seal_mismatch`, `benchmark_baseline_in_composition_candidate`, `ranked_set_not_unique`, `benchmark_baseline_in_ranked_set`, `ranked_compositions_not_derived`, `frontier_member_not_ranked_composition`, `strongest_composition_not_derived`, `incumbent_not_evaluated`, `top_k_not_derived`, `component_finalists_not_derived`, `implementation_composition_not_ranked`, `benchmark_baseline_in_derived_output` |
| rows and implementation (C4, C5) | `row_technical_gates_not_composition_derived`, `row_score_not_composition_derived`, `implementation_composition_required`, `implementation_composition_without_implementation`, `implementation_not_composition_component` |
| group decisions | `composition_authority_differs_between_group_events`, `composition_authority_rewritten`, `decision_without_d_manifest` |
| decision v2 | `m3_v2_unsupported` |

**Licence-phrase detection (M1 validator amendment, owner decisions 9 and final round).** The plate domain term is
exempt only when the entire normalised field value is exactly "license plate", "license plates", "licence plate" or
"licence plates" (NFKC, case folding, combining marks and format characters removed, dashes and whitespace folded).
No positional or neighbouring-word inference is made; every other value containing "licen" (after a Cyrillic, Greek
and Armenian look-alike fold) is refused. Exact identifiers are exempted only through the ledger's typed
`identifierExemptions`, declared before freeze and fixed after it (`candidate-credibility.md` §4.5).

**Not machine-checked (review rules, M1 §9):**
- that the component-ranking metrics and gate results, and each composition's D-score and non-baseline gate results,
  are what the harness measured. They are bound by `measurementSha256` and `dResultSha256` to create-only harness
  outputs outside Git and sit in commits that strictly precede the published seal; recomputing them from raw outputs
  stays a review item;
- that no protected D data was read before `open_protected_d` returned, and that every protected D run committed its
  D manifest. Git proves the order of the seal, the anchor and the D manifests, not the moment D data was read;
- whether the host manifests cover every library actually loaded, and whether the BOB's own manifest classifies its
  files correctly (a file it mislabels as a runtime library could be shared by an ordinary candidate, O7);
- that the harness calls `open_protected_d` with the canonical repository (the remote is a parameter for tests);
- licence paraphrases and confusables outside the folded table (accepted residual R4).

Closed by the redesign: R3 (history rewrite) by the live anchor, the recorded anchors and the owner-activated ruleset;
R1 (ordinary candidate sharing BOB bytes) except runtime-library dependencies, by owner decision O7; P1-1 (author-listed
composition set and component-level authority) by the derived, sealed U and composition-derived rows; P1-2 (current-tree
audit) by the sticky history domain; P2-1 to P2-5 by the one group predicate, typed Git errors, the anchor and the
new-event revision route.

**Owner action (O2).** The `mavi` ruleset must be active for `~DEFAULT_BRANCH` with `deletion` and `non_fast_forward`
and no bypass actors. `open_protected_d` verifies it through the GitHub API before every D and refuses otherwise, so no
real protected D can open before the owner activates it.

## 7. Tests

`tools/qualification/tests/test_model_selection_m3.py` has positive and adversarial tests for every rule above, and
every cold-review probe of the frozen head is a permanent test:
- `probe_gate` 1-5: all compositions failing the baseline gate leave no winner, finalist, frontier or implementation;
  an empty or selective composition list; an implementation from a failed composition; a frontier of individual
  candidates;
- `probe_vanish` (resolved with D, and stopped): erasing every M3 artefact under a BOB-free revision;
- `probe_repo` A (gate and repository refuse with the same code), B1 (STOPPED then revision in place; the new-event
  route), C1 (orphan rewrite; ruleset variants), E1 (injected Git failure; missing object);
- `probe_manifest`: profile without an executable, pinned model missing from a manifest, identity file retyped, one hash
  under two kinds, and the declared residual (a BOB's runtime library retyped as its executable);
- the history attacks of the convergence review in every shape (direct, inside a merge resolution, on a merged side
  branch), first add by ancestry, replace objects ignored, grafts and shallow clones refused, Git environment
  redirection ignored;
- chronology, the live anchor (unpublished seal, forged local `origin/main`, offline, ambiguous remote, unclean or
  unpublished group state), recorded anchors, supersession, abandonment, and the published schemas.

`probe_licence` is unchanged (residual R4). Non-M3 repository tests commit their synthetic tree first, because
repository verification now always needs full history; their verdicts are unchanged.
