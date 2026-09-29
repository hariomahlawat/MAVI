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
2. Classification quality uses human-scorable truth; unsupported assertions on U/I are measured separately.
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
14. Operational/Pareto/fleet/final-ordering rules remain b-2 scope.

## 4. Machine contract

`docs/qualification/model-selection/s2c-quality-statistics-contract.json` is validated by:

`python tools/qualification/quality_statistics_check.py repository --repo .`

The validator is standard-library only and checks:

- exact S/U/I/A semantics and denominators;
- training/tuning/selection/frozen-test authority;
- post-aggregation calibration;
- paired/site-aware statistical invariants;
- practical margins and comparison outcomes;
- absolute unsupported-assertion/useful-coverage gate form;
- b-2 scope boundary.

Discriminating tests mutate each critical rule and require fail-closed refusal.

## 5. Deliberately deferred to S2c.2b-2

- whole-job CPU/host performance gates;
- composition resource accounting;
- 10k-Track deadline/retry mechanics;
- 500-camera projection and claim boundaries;
- Pareto axes;
- deterministic final technical selection;
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
