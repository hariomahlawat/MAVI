# <event-id> — Model Selection Record (template)

> Copy to `<capabilityId>/<event-id>.md`. Follow `../README.md` (MSR method v1). The record is editable until `CLOSED`, then immutable; later facts go to `<event-id>-addenda.md`. Every number carries its evidence class (R, M-D, M-E or M-Q). Unknown is written `UNKNOWN` and unconfirmed is written `UNVERIFIED`; nothing is left blank.

## 0. Event
| Field | Value |
|---|---|
| Event id / capability | |
| State / outcome | `PLANNED` / — |
| Originating stage or trigger | |
| Owner / independent reviewer | |
| Governing documents | ADRs, qualification plan, implementation plan, register (by path) |
| Protocol | `<event-id>-protocol.md` SHA-256 (from `PROTOCOL_FROZEN`) |
| Incumbent | Model Pack id + qualification record id, or "none", or "selection history unrecorded (pre-methodology)" |
| Baseline | |
| Discovery sources | survey path and date; searches re-run at freeze |
| Frozen-test access count | |

## 1. Task definition
Reference the schema; summarise the operating envelope.

## 2. Candidate ledger
| Id | Role | Candidate (family) | Exact identity | Credibility class (M1) | Technical disposition | Licence/deployment status (per profile) | Survey/source ref |
|---|---|---|---|---|---|---|---|

The credibility class and all external evidence come from the event's External Evidence Ledger, `<event-id>-evidence-ledger.json` (`../candidate-credibility.md`; template `templates/external-evidence-ledger.md`). This table restates the class; the ledger is authoritative for it, and the credibility class never enters §6.

One **candidate card** per serious candidate, holding every field of methodology §5. It is filled at `PROTOCOL_FROZEN` and extended with measurements.

## 3. Reported evidence (class R; snapshotted)
| Candidate | Figure | Dataset/split | Source (table/section) | Date | Retrieved (date, SHA-256) |
|---|---|---|---|---|---|

## 4. MAVI measurements (classes M-D, M-E)
For S2c, quality tables name the S/U/I/A population and denominator for every row; report per-value quality, abstention/useful coverage, unsupported assertions, all-assigned delivery, post-aggregation calibration, required slices, support and independent-cluster status. Comparative rows record the frozen practical/non-inferiority/equivalence rule and may be `inconclusive` or `insufficient evidence`. Engineering measurements per host class remain separate. Every row: harness commit, configuration hash, partition hash, result artefact SHA-256.

### 4.1 System-scale projection (methodology §7.1; class M-E projected)
Per finalist or composition:
- measured quantities: service time, crops/Track, per-worker throughput, memory, workers per host, load/startup, recovery, footprint;
- workload model version;
- projected workers/hosts, queue depth and backlog drain at the scale target;
- load actually executed to validate the projection;
- limitations.

## 5. Gates
| Candidate | Gate | Result | Measurement ref |
|---|---|---|---|

## 6. Technical ranking
For S2c, the final ordering is populated only under the S2c.2b-2 rule. S2c.2b-1 quality/statistical results record gate outcomes, paired comparison status (superior / non-inferior / equivalent / inconclusive / insufficient evidence), practical margins and cluster sufficiency; interval overlap alone is not a tie. S2c refuses weighted winner logic; report E/F/J, the unchanged quality outcome, exact joint H_lo/H_up, admission, H* and the complete T. Optional scores apply only to non-S2c events.

### 6.1 Compositions (multi-component capabilities; methodology §5.1)
For S2c, the decision-status column uses the S2c.2b-2 representation. Frontier and dominated labels are written only if S2c.2b-2 defines them (methodology §8.2).

| Composition | Exact tuple (components, shared backbone/region) | Combined quality | CPU latency / throughput | RAM / VRAM | Load time | Pack size | Runtime Pack impact | Scale projection | Failure domain | Decision status (frontier / dominated only where the governing rule defines them) |
|---|---|---|---|---|---|---|---|---|---|---|

## 7. Licence / deployment qualification (separate)
Per candidate, or per component of a composition, and per declared target profile:
- primary sources (licence text hash, card hash);
- the rights inventory (methodology §5): evaluate / run operationally / modify / derivatives / redistribute weights / redistribute derived weights / attribution / end-use / data;
- the profile's delivery route (local acquisition, or inclusion in a kit);
- status (methodology §4);
- human determination (who, date);
- obligations.

**Not used in §6.**

## 8. Decision (methodology §9)
| Output | Value |
|---|---|
| Strongest reported / reference candidate (class R; not reproduced by MAVI) | |
| Highest task-quality evaluated candidate | |
| Strongest evaluated technical candidate | |
| Strongest candidate cleared for `<profile id>` (per profile) | |
| Implementation candidate or composition (owner decision, rationale, date; each component `established` or `mavi-owned` with its promotion date, M1 §8) | |
| Standard sentence used? If not, why the implementation choice differs from the strongest cleared candidate | |
| Deltas: task-quality vs technical; technical vs cleared; cleared vs implementation (quality and resources) | |
| Alternatives (ranked under the governing rule; for S2c, the S2c.2b-2 representation, and a composition frontier only if S2c.2b-2 defines one) | |
| Rejected / deferred / reference-only / not shortlisted (reasons, revisit triggers) | |
| Owner decisions (MPID, targets, licence pursuit; for unstable, inconclusive or insufficient-evidence comparisons: collect more evidence, defer, abandon, open a later event, or handle the capability operationally, never a statistical winner, methodology §8.2) | |
| Assumptions and unresolved risks | |
| Upgrade deltas vs incumbent (upgrade events) | improved / regressed / resources / scale projection / dependencies / qualification / migration |

The §8 outputs are also written as the checked decision summary `<event-id>-decision.json` (M1 §8). The summary must validate against the ledger it cites by hash.

## 9. Resulting identities (by reference, when created)
Model Pack id; Runtime Pack id per variant; binding; pipeline profile and identity; qualification record id.

## 10. Closure
Closing commit and outcome. The record's own SHA-256 (LF-normalised) is **not** written here, because a file cannot contain its own hash. It goes into the index (`../README.md` §13), the addenda header, and the qualification record's `<capabilityId>-model-selection` evidence.


## 11. S2c M2 artefact/state ledger

| Artefact | Retained path | Canonical SHA-256 | Supersedes / stage |
|---|---|---|---|
| Frozen experiment and evidence | s2c-evidence/<sha>.json | | frozen |
| Person/vehicle quality result | <event>-quality-result.json (numbered correction files retained) | | quality |
| Joint version | s2c-joint/<eventPairId>-joint-<stage>-v<N>.json | | immediate retained predecessor |
| Joint index | s2c-joint/<eventPairId>-joint-index.json | | active is last entry |
| Event decisions | <event>-decision-v<N>.json, active <event>-decision.json | | same pair/version/state in both events |

At TECHNICAL_DECISION_RECORDED: T exists; snapshot/profile/implementation outputs and implementationPair are null. At QUALIFICATION_PENDING: record decision snapshots, every unit/profile licence status, credibility-blind C_r/T_r/C_all, component classes, K_person/K_vehicle, C_impl and recomputed T_impl; implementationPair may remain null. At CLOSED: exact chosen pair and coordinate-derived outcomes, or null with disabled capability. NO_QUALIFIABLE_CANDIDATE cannot close while required licence determinations remain pending. Preserve emerging technical winners and fallback quality-outcome reasons. Record owner rationale/date separately from statistical outcomes.
