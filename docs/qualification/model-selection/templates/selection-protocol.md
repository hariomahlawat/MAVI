# <event-id> — Selection protocol (template)

> Copy to `<capabilityId>/<event-id>-protocol.md` and commit it at `PROTOCOL_FROZEN`, **before any candidate sees MAVI evaluation data** (methodology §3.2). Once its SHA-256 is recorded in the event record, the file is immutable. Any change is a numbered protocol revision recorded in the record, and it voids every result the change could bias.

**Event:** `<event-id>` · **Capability:** `<capabilityId>` · **Qualification protocol instantiated:** `<path>` @ `<commit>` (this file may not weaken it)
**Frozen at:** `<commit>` · **Frozen by:** `<owner>` · **Reviewed by:** `<independent reviewer>`

## 1. Task and scope
Task definitions and attribute/value vocabulary: reference the schema id, version and SHA. Record operating envelope, exclusions, and why each excluded dimension (methodology §7) does not apply.

## 2. Candidates
| Id | Role | Exact identity (repository, revision, file, SHA-256, or method: backbone identity + training recipe) | Preprocessing hash | Evaluation permitted (human, date) | Reason for inclusion |
|---|---|---|---|---|---|

Also record the not-shortlisted candidates, each with its **technical** reason, and the reference-only candidates with their snapshotted reported evidence.

## 3. Data
Corpus manifest hash; partition manifest hash; partitions each step may read (training / tuning / selection); the frozen test sealed and **not readable**; near-duplicate and leakage checks.

## 4. Measurements
Metrics per attribute kind; primary metric(s), which are threshold-free; strata; levels (crop / Representative-only / Track); engineering probes (latency p50/p95, memory, load time, determinism, offline run, pack size); host class; thread count; precision; batch caps.

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

## 6. Comparative scoring (ordering aid only)
Required fields:
- criteria and weights;
- the rule converting each measurement into a criterion score;
- how per-attribute scores are combined within a sub-task and across sub-tasks;
- how a gate with several primary/co-primary metrics is decided (per attribute? all or any? multiplicity handling);
- how a criterion that cannot be measured for every candidate is handled (dropped for all, weight redistributed, recorded);
- tie rule (a difference within the interval scores as a tie);
- the sensitivity perturbation to report;
- MPID and the extension bar;
- the replacement bar against the incumbent (upgrade events).

## 7. Statistics (methodology §8.1)
- cluster hierarchy (site → camera → Track);
- hierarchical paired bootstrap: replicates, interval level, seeds;
- design-effect inputs (`ρ` from the pilot, or the declared conservative value);
- DEFF-inflated support rules for precision (predicted positives) and recall (ground-truth positives);
- the calibration simulation and the frozen minimum number of top-level clusters, overall and per stratum;
- the downgrade wording used when a comparison is under-supported.

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
