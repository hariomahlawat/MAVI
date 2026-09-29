# <event-id> — Selection protocol (template)

> Copy to `<capabilityId>/<event-id>-protocol.md` and commit it at `PROTOCOL_FROZEN`, **before any candidate sees MAVI evaluation data** (methodology §3.2). Once its SHA-256 is recorded in the event record, the file is immutable. Any change is a numbered protocol revision recorded in the record, and it voids every result the change could bias.

**Event:** `<event-id>` · **Capability:** `<capabilityId>` · **Qualification protocol instantiated:** `<path>` @ `<commit>` (this file may not weaken it)
**Frozen at:** `<commit>` · **Frozen by:** `<owner>` · **Reviewed by:** `<independent reviewer>`

## 1. Task and scope
Task definitions and attribute/value vocabulary: reference the schema id, version and SHA. Record operating envelope, exclusions, and why each excluded dimension (methodology §7) does not apply.

## 2. Candidates
| Id | Role | Exact identity (repository, revision, file, SHA-256, or method: backbone identity + training recipe) | Preprocessing hash | Evaluation permitted (human, date) | Reason for inclusion |
|---|---|---|---|---|---|

Also record the not-shortlisted candidates, each with its **technical** reason (or, for an `excluded-discovery`, its credibility reason), and the reference-only candidates with their snapshotted reported evidence.

**External Evidence Ledger (MSR method revision M1).** Copy `<event-id>-evidence-ledger.json` unchanged to `<event-id>-evidence-ledger-frozen.json` and record the copy's canonical SHA-256 here (the repository check requires this file to contain it). From then on the working ledger may only grow. Every `SHORTLISTED` candidate there has computed class `established`, `emerging` (with a recorded basis and second reviewer) or `mavi-owned`, pinned bytes, and snapshotted evidence (`../candidate-credibility.md` §4.3). The independent reviewer confirms the §9 review obligations before freeze. A candidate promoted after freeze enters only through a numbered protocol revision or a new event (§7 there).

## 3. Data
Corpus manifest hash; partition manifest hash; partitions each step may read (training / tuning / selection); the frozen test sealed and **not readable**; near-duplicate and leakage checks.

## 4. Measurements
For S2c person/vehicle events, instantiate `../s2c-quality-statistics.md` and cite the SHA of `../s2c-quality-statistics-contract.json`. Record the four candidate-independent populations (S human-scorable, U human-unscorable, I invalid-subject, A all-assigned), and name the denominator of every metric.

Metrics per attribute kind; required operating-point gates and diagnostics; strata; levels (crop / Representative-only / Track, with Track primary); post-aggregation calibration evidence; unsupported-assertion and all-assigned delivery measurements. Engineering probes are specified separately by the event.

**Baselines.** For each attribute, the exact baseline and how it is scored under every primary metric, including its tie rule and whether it can be packaged or serves only as a statistical floor.

**Predeclared aggregation references.** The pooling or aggregation rules evaluated beside the frozen family's default, and the tuning-partition rule that picks among them. Nothing may be added after results.

**System-scale method (methodology §7.1).**
- the scale target;
- the workload model (Tracks per camera per minute distribution, crops/Track) and its version;
- the measured quantities and how each is measured;
- the projection script;
- the validation load to execute;
- the scale gate's pass rule against the declared host envelope.

## 5. Gates (pass/fail; each names its measurement and evidence class)
| Gate | Kind (technical / engineering / qualification) | Rule | Measurement |
|---|---|---|---|

## 6. Technical decision rule
The event cites the governing S2c.2b-1 quality/statistical contract and the S2c.2b-2 operational/multi-objective rule. No S2c event may reach `PROTOCOL_FROZEN` until both are complete.

For quality/statistical comparison record:
- the owner-approved gate table (precision/recall or useful-coverage, false-positive/unsupported-assertion, calibration, support and required-slice limits);
- confidence-bound direction for each gate;
- practical-difference, non-inferiority and equivalence margins;
- how a metric with several attribute/value requirements is decided;
- MPID/replacement bars where applicable.

Any comparative score is optional under MSR method §8 and may not replace these gates. The final Pareto/ordering rule belongs to S2c.2b-2 and must be frozen before selection data are read.

## 7. Statistics (methodology §8.1 + qualification-plan R3)
- estimand and top-level independent unit for each claim (default site for unseen-site claims);
- cluster hierarchy, keeping every Track's crops together;
- paired resampling algorithm: replicates, interval level and seeds;
- predicted-positive support for precision and ground-truth-positive support for recall, with clustering/design-effect assumptions;
- training-pilot simulation used to establish independent-cluster sufficiency;
- practical-difference, non-inferiority/equivalence and multiplicity rules;
- undefined-denominator handling;
- exact wording for `inconclusive` and `insufficient evidence`.

Interval overlap alone is not a tie/equivalence rule.

## 7a. Composition rule (multi-component capabilities; methodology §5.1)
- per-sub-task finalist cap `K`;
- composition generation rule (winner tuple, shared-backbone tuples, capped additional tuples by rank sum);
- the Pareto axes;
- the measurements taken per composition.

## 7b. Licence review scope
- the declared deployment profile(s) and their delivery route;
- the rights the profile exercises (methodology §2.1, §5).

## 8. Report format
The tables the record must contain (methodology §9) and the result artefacts to retain, by hash.
