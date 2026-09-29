# S2c.2b-1 — Quality and statistical protocol implementation record

**Baseline:** `main@db2b25a24d0f850c3841a9eabcb915f7c92eebfb` (PR #118 merge)  
**Slice:** S2c.2b-1 — quality/statistical protocol only  
**State:** implementation complete on branch; acceptance requires review, exact-head CI and merge.  
**Non-claim:** no candidate was selected, downloaded, trained, calibrated or benchmarked; no real Model Selection Event protocol was frozen; no F/G acceptance row changes.

## 1. Purpose

Freeze the candidate-independent quality/statistical semantics required before the S2c evaluation harness can be implemented. This slice incorporates the accepted design review input without absorbing S2c.2b-2 operational/Pareto/fleet decisions.

## 2. Authority reconciliation

- ADR-013/014: unchanged.
- Visual-attributes qualification plan: additive **R3** clarifies truth populations, abstention, calibration, partition firewall, paired cluster-aware comparison, insufficient-evidence handling and support arithmetic.
- MSR method v1 + M1: unchanged as generic method; README points to the S2c-specific b-1 protocol but b-1 is not a generic MSR revision.
- S2c plan: conflicting AURC/unscorable, interval-overlap tie and support-arithmetic text is superseded; historical weighted ordering is explicitly non-governing pending b-2.
- Event protocol/record templates: updated to carry S/U/I/A populations, denominators, post-aggregation calibration and comparison states.

## 3. Frozen b-1 invariants

1. Human-unscorable ground truth is not model abstention.
2. Classification quality uses human-scorable truth; unsupported assertions on U and on I are measured separately.
3. All-assigned delivery retains execution failures.
4. Track calibration is evaluated after aggregation/abstention.
5. Calibration fitting uses training-derived predictions only.
6. Tuning chooses operating parameters; selection performs no fit/tuning.
7. Frozen-test evidence cannot select or rescue an alternative.
8. Candidate comparison is paired and cluster-aware; Track crops stay together.
9. Practical/non-inferiority/equivalence margins are predeclared.
10. Interval overlap is not equivalence.
11. Insufficient support remains `insufficient evidence`.
12. Unconditional recall already includes abstention; coverage is not multiplied twice.
13. Owner numerical quality targets are not invented in this planning slice.
14. Operational, Pareto/frontier, finalist-ordering, fleet and final-selection rules remain b-2 scope (every subject in the contract's deferred list).

## 4. Machine contract

`docs/qualification/model-selection/s2c-quality-statistics-contract.json` is validated by:

`python tools/qualification/quality_statistics_check.py repository --repo .`

The validator is standard-library only. The **JSON contract is the canonical machine authority**. It owns:

- the exact 14 invariant identities, Boolean guards and human-readable invariant statements;
- the complete 13-entry partition-authority map and its human-readable statements;
- S/U/I/A semantics and denominators, with unsupported assertions measured **separately** for U and I;
- post-aggregation calibration and training-only fit authority;
- paired/site-aware statistical invariants, practical margins and comparison outcomes;
- execution-failure, insufficient-evidence, recall-support and no-adaptive-frozen-test-selection semantics;
- the gate form: owner targets frozen before selection, confidence-bound direction, **no numeric target defined by b-1**, and the exact ordered list of ten required gate forms (per-value precision; useful recall/coverage floor; FPR bound; separate unsupported-assertion bounds for U and for I; Track calibration tolerance; attribute/value support; independent-cluster support; required-slice floor; required-slice degradation limit);
- multiplicity rule predeclared; interval overlap is not a tie; non-significance is not non-inferiority; frozen test may neither tune nor select;
- the exact ordered fifteen-subject b-2 scope boundary (`deferredToS2c2b2`): operational performance, whole-job CPU/host gates, composition resource accounting, 10k-Track deadline mechanics, 500-camera projection, Pareto axes, directions and normalization, dominance semantics, disabled-attribute frontier treatment, non-dominated-set construction, sub-task finalist ordering, final technical selection, its MSR ranking representation, and reconciliation of the historical weighted ordering. An entry means only "deferred"; b-1 specifies no value for it.

The Markdown protocol no longer has an independent parser-defined authority surface. It contains one protected block between `S2C_B1_CONTRACT_PROJECTION` markers. That block is rendered deterministically from the JSON contract (partition statements, required gate forms, deferred b-2 subjects, invariant statements) and compared byte-for-byte during repository validation. `.gitattributes` pins the protocol file to LF so a Windows checkout carries the same bytes as Linux; without the pin, Git's CRLF conversion made the unmodified repository fail its own check on Windows. Arbitrary prose outside the protected projection is intentionally **not** parsed as machine authority; if narrative wording conflicts with the contract/projection, the contract governs.

Discriminating tests mutate contract semantics/types, remove, rename, duplicate or reorder every deferred subject and every required gate form, require all 13 partition rows, 10 gate forms, 15 deferred subjects and 14 invariant statements to be projected exactly once, pin the LF attribute, write every fixture as exact bytes, reject protected-block edits or marker drift, and explicitly prove that unrelated narrative outside the projection is outside the machine trust boundary.

## 5. Deliberately deferred to S2c.2b-2

- whole-job CPU/host performance gates;
- composition resource accounting;
- 10k-Track deadline/retry mechanics;
- 500-camera projection and claim boundaries;
- Pareto axes, directions, normalization, dominance semantics, treatment of disabled attributes and non-dominated-set construction;
- the sub-task finalist ordering used for composition generation;
- deterministic final technical selection, including selection from any non-dominated set, and its MSR representation;
- reconciliation/removal of the historical weighted-ordering table.

No S2c event may reach `PROTOCOL_FROZEN` until b-1 and b-2 are both governing.

## 6. Review checklist

Before merge:

- repository contract validator passes;
- qualification tests pass;
- `tools/verify_repo.py` passes;
- exact-head CI green;
- changed-file scope remains protocol/validator/docs only;
- no unresolved P1/P2;
- independent/Codex review attacks population conflation, partition leakage, calibration-after-aggregation and statistical tie/support semantics.

## 7. Residual owner inputs

These are intentionally unresolved policy/operational inputs, not defaults invented by this slice:

- per-attribute/value precision and useful-recall/coverage targets;
- unsupported-assertion/FPR/calibration tolerances;
- required robustness slices supported by the real corpus;
- practical/non-inferiority/equivalence margins;
- CPU host/co-resident workload and later b-2 fleet envelope.

## 8. Handover review (2026-09-29)

A fresh cold review of the whole change set and its authority chain was performed after the last Codex round on `e5a057f`. Findings and dispositions:

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| H1 | P1 | The Windows CPU job failed on `e5a057f`: `.gitattributes` pinned `*.json` but not the protocol Markdown, so a Windows checkout rewrote it to CRLF and the raw-byte projection check refused the unmodified repository | fixed: path-scoped `eol=lf` pin; test asserts the pin and that the committed file carries no CR |
| H2 | P2 | Contract protected only coarse `pareto-axes` / `final-technical-selection`; directions, normalization, dominance, disabled-attribute treatment and non-dominated-set construction were deferred only in prose; I14 understated the boundary | fixed: fifteen explicit deferred subjects, projected; I14 restated; remove/rename/duplicate/reorder mutations for every subject |
| H3 | P2 | Plan §9.5a ranked sub-tasks and built a "winner tuple (best …)" with no governing ordering once the weighted score became historical | fixed: `sub-task-finalist-ordering` deferred to b-2; §9.5a cites it |
| H4 | P2 | Gate form only partly machine-checked (two of ten required forms); FPR, calibration tolerance, support, independent-cluster and required-slice forms were prose only | fixed: `gates.requiredGateForms` exact ordered list, `numericTargetsDefinedByB1: false`, projected |
| H5 | P2 | R3 item 2 and plan SG6/§10.4 stated one combined U/I unsupported-assertion bound, contradicting I02 (separate measurement) | fixed: separate U and I bounds in R3, plan, protocol narrative and gate forms |
| H6 | P2 | Plan residuals: §6 accuracy expectation used the removed "precision–coverage frontier" procedure; §9.0 ended composition in a "Pareto frontier"; PO-B0 "must beat on AURC/AP"; §9.5 said gates "decide the technical ranking"; §9.6 "technical ranking with its sensitivity check" | fixed: each aligned with b-1 gates and the b-2 ordering |
| H7 | P2 | MSR README §5.1 generic "owner chooses a frontier composition" had no S2c override, conflicting with the plan's deterministic b-2 selection | fixed: S2c note that steps 4–5 are instantiated only by b-2 |
| H8 | P2 | Tests wrote fixtures with `write_text`, which emits CRLF on Windows, so several tamper tests failed or passed for the wrong reason there | fixed: fixtures written and read as exact bytes |
| H9 | P3 | `frozenTestMayTune`, `multiplicityRulePredeclared` and `nonSignificanceMeansNonInferiority` were prose-only statistics/firewall rules | fixed: strict Boolean contract fields with stable refusal codes |
| H10 | P1 | Second cold review of `267cfdf`: plan §14/§14.1 and the SG4/SG7a/SG7b rows still stated b-2 operational rules as governing. These were the retry-budget formula and ≈0.266 s/crop figure, the host class and CPU-mandatory SG4, the workload model/host envelope/projection script "Frozen at S2c.2", the concrete projection outputs, N ≥ 2 validation with a tolerance "frozen at S2c.2", and batch caps "fixed in S2c.2". Each contradicted the contract's `deferredToS2c2b2` | fixed: §14 opens with a governing-status note separating the measurement requirements (governing) from the operational rules (S2c.2b-2). The old figures, formula and choices are retained as historical/provisional context. SG4/SG7a/SG7b, §5 latency, the gate classes, S2c.9, U9 and constraint B now defer the rules to b-2. Docs-only; the contract is unchanged |
| H11 | P2 | `capability-roadmap.md` §9 item 4 still named S2c.2a the current slice, contradicting its own table (PR #118 merged). The implementation roadmap and the acceptance-register status header carried the same stale state | fixed: S2c.2a merged (PR #118); S2c.2b-1 current and in review (PR #119, not merged); S2c.2b-2, the S2c.2 freeze and S2c.3 onward OPEN; no register row change |

Validator source mutation (15 mutants: every new check, the projection sections, raw-byte reading, the duplicate-member hook and I14) — all killed.

