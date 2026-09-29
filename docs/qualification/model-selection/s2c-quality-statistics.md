# S2c.2b-1 — Quality and statistical protocol

**Status:** Proposed — becomes governing for the S2c person/vehicle Model Selection Events only when this change merges.  
**Scope:** quality/statistical semantics only. Operational-performance accounting, Pareto axes, 500-camera projection and the final deterministic technical-selection rule are deliberately deferred to **S2c.2b-2**.  
**Authorities:** ADR-013/014 remain unchanged; the visual-attributes qualification plan governs, including R1/R2 and the additive R3 in this change; MSR method v1 + M1 remain governing for event/credibility history.  
**Machine contract:** `s2c-quality-statistics-contract.json`, checked by `tools/qualification/model_selection/quality_statistics.py`.

## 1. Why this slice exists

The accepted S2c plan contains two quality/statistics problems that must be removed before a bake-off protocol can be frozen:

1. human-unscorable ground truth is mixed with model abstention in the current AURC completion rule; and
2. crop-level calibration is implicitly carried through aggregation although pooling, quality filtering and abstention change the evaluated distribution.

It also uses “interval overlap = tie” and a support-size formula that can double-count abstention/coverage. This slice fixes those semantics without choosing a model and without introducing a new final ranking rule.

## 2. Frozen populations

Every attribute result is reported against candidate-independent populations. The same Track may contribute to different reports only under the definitions below; a report names its denominator explicitly.

| Id | Population | Meaning |
|---|---|---|
| **S** | human-scorable | adjudicated ground truth exists for the attribute |
| **U** | human-unscorable | humans cannot defensibly assign the attribute from the retained evidence |
| **I** | invalid-subject | retained evidence does not contain an applicable subject/evidence instance |
| **A** | all-assigned | every Track assigned to the evaluation, including execution failures |

**I-QS1.** Classification quality is computed on **S** only. U is never converted to a class, negative, false positive, false negative or successful abstention.  
**I-QS2.** Model abstention is an outcome on an otherwise scorable/applicable Track; it is not a ground-truth state.  
**I-QS3.** Execution failure/Unavailable remains in **A** and lowers all-assigned delivery coverage. It cannot disappear by becoming Unknown.  
**I-QS4.** Unsupported assertions are measured separately on **U** and **I**.

## 3. Metric families

### 3.1 Categorical colour

Primary operator-facing measurements are Track-level:

- per-value precision and recall;
- macro recall over the fixed required value set, with unsupported values remaining explicitly unsupported;
- useful coverage on S;
- confusion matrix with model abstentions shown separately;
- unsupported-assertion rate on U/I;
- all-assigned delivery coverage on A.

Macro-F1 and balanced accuracy remain diagnostics. No candidate may improve its apparent score by removing a difficult required value.

### 3.2 Presence

The product semantic remains **present or Unknown**, not symmetric present/absent publication.

Report:

- positive precision;
- positive recall, with abstention on a true positive counted as missed recall;
- false-positive rate on adjudicated scorable negatives;
- unsupported-assertion rate on U/I;
- all-assigned delivery coverage on A;
- PR curve/AP and F1 as diagnostics.

F1 is not a sole gate because it permits precision/recall compensation that does not match the product policy.

### 3.3 Abstention

No accuracy figure is valid without its retained-prediction denominator. The event protocol freezes:

- a useful-recall or useful-coverage lower bound;
- an absolute unsupported-assertion upper bound;
- the quality/risk requirement on retained predictions.

Risk–coverage/AURC may be retained as diagnostics but **must not fabricate predictions for U merely to reach nominal full coverage**.

## 4. Calibration after aggregation

**I-QS5.** Calibration is evaluated at the Track output **after** the complete aggregation, quality filtering and abstention procedure.

Crop scores may be calibration inputs, but a pooled score is not described as a calibrated Track probability unless Track-level calibration evidence supports that statement.

The protocol reports at minimum a proper score (Brier or NLL), a frozen reliability representation, and an operating-region overconfidence check. ECE may be reported only with its binning rule frozen; it is not sufficient alone.

## 5. Partition authority

The following data-access rule is normative:

| Parameter / decision | Permitted source |
|---|---|
| model weights / task heads | training |
| calibration coefficients | training-derived, group-disjoint held-out predictions or predeclared cross-fitting |
| choice among predeclared calibration methods | training-internal validation |
| confidence/presence thresholds | tuning |
| colour margin | tuning |
| admissibility threshold | tuning |
| crop evidence floor | tuning |
| pooling / aggregation parameter values | tuning, within the family frozen before candidate execution |
| candidate comparison | selection |
| final qualification | frozen test |

**I-QS6.** Selection may compare already-frozen executable configurations but may not fit or tune them.  
**I-QS7.** Frozen-test evidence cannot tune, rank, replace or rescue a candidate. A failed/inconclusive frozen qualification does not trigger adaptive evaluation of alternatives on the same exposed test.

R1 remains literal: calibration **fitting** belongs to training. R2’s “calibration checks” on tuning do not authorise fitting there.

## 6. Candidate-specific fairness

Identical numeric thresholds are not required across architectures because score scales differ. Fairness means the same:

- allowed method families;
- data access;
- objective;
- bounded search budget;
- freeze point.

Candidate-specific fitted calibration and tuning values are permitted only inside those common rules. Every tried configuration is retained by identity.

## 7. Statistical estimands and resampling

A protocol declares the population for each claim.

For unseen-site/general deployment claims, the default top-level independent unit is **site**. Cameras/date blocks remain nested within site; every Track’s crops stay together. A separate fixed-camera/future-time claim may use a predeclared temporal-block analysis but cannot be presented as unseen-site generalisation.

**I-QS8.** Candidate comparisons are paired on identical evaluation units.  
**I-QS9.** Inferential support requires both attribute/value support and sufficient independent clusters. Total Track count cannot substitute for cluster support.

The event protocol freezes:

- cluster hierarchy;
- resampling algorithm;
- interval level;
- replicate count and seed;
- practical-difference / non-inferiority / equivalence margins;
- multiplicity rule for simultaneous decision claims;
- behaviour for replicates with undefined denominators.

A training-pilot simulation may establish the minimum independent-cluster support, but it must vary plausible prevalence, cluster imbalance, dependence, abstention and effect size; a cluster-label swap alone is not sufficient validation of interval behaviour.

## 8. Comparison outcomes

For a higher-is-better metric with paired difference Δ = A − B:

- **superior:** the frozen confidence rule supports Δ > 0 and the effect meets the practical-importance rule;
- **non-inferior:** the lower bound exceeds −δ;
- **equivalent:** the frozen equivalence interval lies inside [−δ,+δ];
- **inconclusive:** none of the above is established;
- **insufficient evidence:** support/cluster requirements are not met.

**I-QS10.** Overlapping confidence intervals are not proof of equivalence. A non-significant degradation is not proof of non-inferiority.  
**I-QS11.** “Insufficient evidence” is preserved as an outcome; it is never converted into a pass, tie or owner-selected statistical winner.

## 9. Support arithmetic

Precision support is driven by predicted-positive support at the frozen operating point; recall support is driven by ground-truth positives. Planning calculations may use prevalence and a design effect, but every symbol/denominator is defined.

If recall is defined unconditionally over all true positives, it already includes abstention. **Coverage is not multiplied into the denominator a second time.**

Required values that cannot reach support remain **insufficient evidence**; they are not silently removed from a passing macro result.

## 10. Quality gates before selection

S2c.2b-1 freezes the *form* of the gates, not owner policy numbers. Before selection results are read, each event protocol must carry an owner-approved table containing, as applicable:

- per-value precision requirement;
- minimum useful recall / useful coverage;
- maximum false-positive rate;
- maximum unsupported-assertion rate;
- Track-level calibration tolerance;
- minimum attribute/value support and independent-cluster support;
- required robustness slices and maximum permitted degradation.

The gate uses the predeclared confidence-bound direction, not the point estimate alone.

No universal 90/95/99 percent target is invented by this method.

## 11. Robustness

Required robustness slices are limited to strata the real corpus can support. A mandatory slice has both an absolute quality floor and a maximum degradation rule. Unsupported slices are reported as limitations, never fabricated from synthetic labels.

The protocol distinguishes pooled quality from claims about low-light, occlusion, scale, site and time. A pooled pass cannot hide a required-slice failure.

## 12. What remains for S2c.2b-2

This slice deliberately does **not** freeze:

- the final Pareto axes;
- the deterministic selection from a non-dominated set;
- whole-job CPU/host gates;
- composition resource accounting;
- the 10k-Track deadline mechanics;
- the 500-camera projection;
- final technical ranking representation in the MSR.

The current weighted-score text in the S2c plan is therefore **not frozen by b-1**. S2c.2b-2 must reconcile it before any selection result is read. No event reaches `PROTOCOL_FROZEN` until both b-1 and b-2 are complete.

## 13. Frozen invariant registry

The following tagged clauses are the **canonical machine-checked expression** of the 14 b-1 invariants. Each `INV-B1-xx` line is exact normative text: changing its wording, appending an exception, deleting it or duplicating its tag invalidates repository validation.

**INV-B1-01:** Human-unscorable ground truth is not model abstention.  
**INV-B1-02:** Classification quality uses human-scorable truth; unsupported assertions on U and I are measured separately.  
**INV-B1-03:** All-assigned delivery retains execution failures.  
**INV-B1-04:** Track calibration is evaluated after aggregation and abstention.  
**INV-B1-05:** Calibration fitting uses training-derived predictions only; tuning, selection and frozen-test data cannot fit calibration coefficients.  
**INV-B1-06:** Tuning chooses operating parameters; selection compares frozen configurations and performs no fitting or tuning.  
**INV-B1-07:** Frozen-test evidence cannot tune, rank, replace or rescue a candidate, and a failed or inconclusive frozen qualification cannot trigger adaptive alternative selection on the same exposed test.  
**INV-B1-08:** Candidate comparison is paired and cluster-aware, and every Track's crops stay together.  
**INV-B1-09:** Practical-difference, non-inferiority and equivalence margins are predeclared before selection.  
**INV-B1-10:** Interval overlap is not equivalence, and non-significance is not non-inferiority.  
**INV-B1-11:** Insufficient attribute/value support or independent-cluster support remains insufficient evidence and cannot become a pass, tie or statistical winner.  
**INV-B1-12:** Unconditional recall already includes abstention, so coverage is not multiplied into recall-support arithmetic a second time.  
**INV-B1-13:** S2c.2b-1 does not invent owner numerical quality targets; it freezes only the form and authority of those gates.  
**INV-B1-14:** Whole-job CPU/host gates, composition resource accounting, 10k-Track deadline mechanics, 500-camera projection, Pareto axes and deterministic final technical ordering remain S2c.2b-2 scope.

## 14. Required retained evidence

Later S2c.3/S2c.4 artefacts retain, by hash:

- exact metric implementation and configuration;
- per-Track outcome population (S/U/I/A), ground truth and model outcome;
- per-crop scores/contribution reasons and Track aggregate;
- calibration method/data identity;
- thresholds/margins/pooling identity;
- numerators/denominators and undefined cases;
- cluster hierarchy and statistical seeds;
- comparison margins and interval outputs;
- every insufficient-evidence result.

This slice produces no MAVI measurement and closes no F/G acceptance row.
