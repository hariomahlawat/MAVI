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
| Id | Role | Candidate (family) | Exact identity | Technical disposition | Licence/deployment status (per profile) | Survey/source ref |
|---|---|---|---|---|---|---|

One **candidate card** per serious candidate, holding every field of methodology §5. It is filled at `PROTOCOL_FROZEN` and extended with measurements.

## 3. Reported evidence (class R; snapshotted)
| Candidate | Figure | Dataset/split | Source (table/section) | Date | Retrieved (date, SHA-256) |
|---|---|---|---|---|---|

## 4. MAVI measurements (classes M-D, M-E)
Quality per attribute, level and stratum, with hierarchical-bootstrap intervals (methodology §8.1) and the cluster count behind each. Engineering measurements per host class. Every row: harness commit, configuration hash, partition hash, result artefact SHA-256.

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
Comparative scores under the frozen rule; ties; sensitivity check; cluster-sufficiency status of each comparison (methodology §8.1).

### 6.1 Compositions (multi-component capabilities; methodology §5.1)
| Composition | Exact tuple (components, shared backbone/region) | Combined quality | CPU latency / throughput | RAM / VRAM | Load time | Pack size | Runtime Pack impact | Scale projection | Failure domain | Frontier / dominated |
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
| Implementation candidate or composition (owner decision, rationale, date) | |
| Standard sentence used? If not, why the implementation choice differs from the strongest cleared candidate | |
| Deltas: task-quality vs technical; technical vs cleared; cleared vs implementation (quality and resources) | |
| Alternatives (ranked; composition frontier) | |
| Rejected / deferred / reference-only / not shortlisted (reasons, revisit triggers) | |
| Owner decisions (MPID, targets, licence pursuit, ties, insufficient-cluster choices) | |
| Assumptions and unresolved risks | |
| Upgrade deltas vs incumbent (upgrade events) | improved / regressed / resources / scale projection / dependencies / qualification / migration |

## 9. Resulting identities (by reference, when created)
Model Pack id; Runtime Pack id per variant; binding; pipeline profile and identity; qualification record id.

## 10. Closure
Closing commit and outcome. The record's own SHA-256 (LF-normalised) is **not** written here, because a file cannot contain its own hash. It goes into the index (`../README.md` §13), the addenda header, and the qualification record's `<capabilityId>-model-selection` evidence.
