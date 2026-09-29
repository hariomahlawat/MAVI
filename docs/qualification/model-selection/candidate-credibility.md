# Candidate Admissibility and Credibility (MSR method v1, revision M1)

**Status:** Proposed in slice S2c.2a (planning/protocol only). It becomes governing when its change passes independent review and exact-head CI and merges. That merge is the acceptance event. It is a revision of **MSR method v1** (`README.md` §14), not a new method and not a new source of architectural truth.
**Scope:** every Model Selection Event under MSR method v1, for every capability. S2c (`msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`) is its first use.
**Machine checks:** `tools/qualification/model_selection/credibility.py`, run with `python tools/qualification/model_selection_check.py`. The rules marked **[checked]** are enforced by that validator; the rest are review rules.
**What this revision does not do:** it selects, downloads, runs or benchmarks no model. It changes no ADR, no contract, no lifecycle state, no Model Pack, no Runtime Pack and no binding. It records no MAVI measurement and claims no bake-off result.

---

## 1. Why this gate exists

A high benchmark number is not credibility. A popular repository is not technical quality. MSR method v1 already separates the technical, engineering and licence assessments (§2). It does not yet say **which candidates are credible enough to enter serious evaluation**, or how to tell a genuinely confirmed result from one first-party number repeated by many websites.

**Normative rule (R-CRED).** An unverified community upload, or an obscure checkpoint whose only performance evidence is self-reported, **cannot become a MAVI implementation candidate on the strength of those claims**. It may be surveyed and recorded. It normally stays `reference-only` until its provenance and external evidence are enough for promotion (§7). A promotion is a recorded event, never a silent reclassification.

## 2. Three layers, never merged

Candidate selection has three distinct layers. Each is recorded separately, and none may be computed from another.

| Layer | Question | Where recorded | May it change the technical ranking? |
|---|---|---|---|
| **1. Credibility / admissibility** (this revision) | Is the artefact identifiable, traceable and externally supported enough to be taken seriously? | the event's **External Evidence Ledger** (§4) | **no** |
| **2. Independent technical evidence** | What do sources other than the authors report about it? | the ledger's evidence items and claims (class R, MSR method §6) | **no**: class R evidence never decides a gate |
| **3. Controlled MAVI bake-off** | How does it perform on MAVI data under the frozen protocol? | the MSR record §4–§6 (classes M-D, M-E) | this layer **is** the technical ranking |

- External reputation or popularity never determines the technical winner. The ranking comes only from layer 3, under MSR method §8.
- A high reported score never establishes credibility by itself.
- Credibility is **not a weighted criterion** and never enters the comparative score. The existing engineering criterion "implementation stability and maintenance status" (S2c plan §9.5) is scored by its own frozen rule. It may not reuse the credibility class as its score.
- Licence status is a fourth, separate axis (MSR method §2, §4). It is **not** in the ledger at all.

## 3. Candidate credibility classes

Each candidate in a ledger has exactly one class. The class is **computed** from the recorded evidence by the rule in §3.2. The declared class must equal the computed class **[checked]**, so two reviewers who record the same evidence reach the same class.

| Class | Meaning | Allowed technical dispositions (MSR method §4) |
|---|---|---|
| `established` | identity pinned to the original source; peer-reviewed or equivalent publication; independent technical confirmation; support from at least two independent producer groups | any pre-evaluation disposition except a `credibility` reason; **implementation-eligible** (§8) |
| `emerging` | identity pinned to the original source (or a documented official conversion); architecture documented; every claim traceable to its origin; independent support not yet sufficient | `SHORTLISTED` (evaluated in the bake-off), `NOT_SHORTLISTED` (technical), `DEFERRED`, `REFERENCE_ONLY` (evaluation permission or availability only); **not implementation-eligible** until promoted |
| `reference-only` | origin known, but provenance confidence Low, architecture undocumented or a claim untraceable | `DISCOVERED`, `REFERENCE_ONLY`, `NOT_SHORTLISTED` (technical), `DEFERRED`; **never `SHORTLISTED`** |
| `excluded-discovery` | the artefact cannot be traced to an identifiable original source, its publisher is unknown, no author group is known, or its bytes conflict with what the source publishes | `DISCOVERED` or `NOT_SHORTLISTED` with reason class `credibility`; retained in the ledger |
| `mavi-owned` | a MAVI-owned deterministic baseline (for example PC-B0, VC-B0); its provenance is a MAVI commit | as MSR method v1 |

A method candidate (an architecture trained by MAVI) is classified on its **backbone checkpoint** identity, its published method and the method's code revision. The heads MAVI trains are MAVI artefacts, identified by the training manifest (MSR method §5).

### 3.1 Provenance confidence

Computed **[checked]**:

| Confidence | Rule |
|---|---|
| **High** | the source repository and organisation are known; the revision is immutable (a 40- or 64-hex commit or hub revision, never a floating tag); every weight file has a SHA-256; and the publisher is the original author or organisation |
| **Medium** | as High, except that the publisher is a recognised framework maintainer who converted or re-hosted the original. The derivation is then pinned: source repository, source revision, source SHA-256, and a non-repetition evidence item documenting the conversion |
| **Low** | anything else: a third-party upload, an unpinned identity, a floating tag, a missing hash, or a recorded integrity conflict |

A candidate discovered by name but not yet pinned is therefore Low, and computes as `reference-only` until it is pinned. That is intended: discovery precedes pinning.

### 3.2 Classification rule

Computed on the evidence active at a date (recorded on or before it and not retracted by it). The rules are applied in order:

1. `mavi-baseline` kind → `mavi-owned`.
2. Integrity conflict recorded, repository unknown, publisher unknown or no author group known → `excluded-discovery`.
3. Provenance confidence Low, **or** architecture not documented by an active non-repetition evidence item, **or** no claim, **or** any claim whose origin is not an active non-repetition evidence item with a locator → `reference-only`.
4. `established` when **all** of these hold:
   - provenance confidence is High;
   - publication status is `peer-reviewed` (venue named), `preprint-established-group` (with its recorded basis) or `official-model-documentation`;
   - there is at least one active **independent technical** item (`independent-reproduction` or `independent-benchmark`). For a checkpoint candidate, that item has scope `exact-checkpoint` and names the same bytes (§4.3);
   - the active independent technical and adoption items come from **at least two distinct independent producer groups**.
5. Otherwise → `emerging`.

GitHub stars, downloads and citation counts are **popularity signals**. They are recorded (`popularitySignals`) for context and never counted by any rule **[checked: they are not read]**. Adoption counts only as a **named downstream use by an independent group**, never as a number.

## 4. External Evidence Ledger

One ledger per Model Selection Event: `docs/qualification/model-selection/<capabilityId>/<event-id>-evidence-ledger.json`, schema `mavi-external-evidence-ledger-v1`. The field-by-field template is `templates/external-evidence-ledger.md`. The ledger:
- covers exactly one event, one capability and one object class, and declares that event's sub-tasks **[checked]**;
- holds every candidate the event considered seriously, including every `excluded-discovery`, so a later reader can reconstruct why each was included or excluded;
- holds **external evidence only**. It has no field for a MAVI measurement, admits only the pre-evaluation dispositions `DISCOVERED`, `SHORTLISTED`, `NOT_SHORTLISTED`, `REFERENCE_ONLY` and `DEFERRED`, and rejects every unknown field **[checked]**. No ledger can claim that a candidate passed a MAVI bake-off;
- has **no licence field** **[checked]**. The licence axis lives in the MSR record §7 and in the decision summary (§8), where it cannot touch classification;
- contains no model weights, imagery or credentials. Sources are citations or URLs.

Each candidate entry records the fields the S2c.2a brief requires:

| Required content | Ledger field |
|---|---|
| candidate/model name; exact checkpoint identifier; checkpoint hash | `candidateName`; `identity.repository`, `identity.revision`, `identity.tag`, `identity.files[].path`, `identity.files[].sha256` |
| original source; repository/organisation; checkpoint provenance | `identity.repository`, `identity.organisation`, `identity.publisher`, `identity.derivation`, `identity.integrityConflict` |
| authors/institution | `authors.names`, `authors.groups` |
| publication and venue status | `publication.status`, `publication.venue`, `publication.reference`, `publication.basis` |
| architecture | `architecture.description`, `architecture.documentedBy` |
| claimed benchmark; origin of the claimed benchmark | `claims[]` with `originEvidenceId` |
| independently reported benchmark evidence; independent reproductions | `evidence[]` of type `independent-benchmark` / `independent-reproduction` |
| adoption/maturity evidence | `evidence[]` of type `adoption`; `popularitySignals` (never counted) |
| known caveats and public scrutiny | `caveats`; `evidence[]` of type `public-scrutiny` |
| provenance confidence; credibility classification | `classification.provenanceConfidence`, `classification.class` (both recomputed) |
| shortlist disposition; reason | `disposition.status`, `disposition.reasonClass`, `disposition.reason`, `disposition.revisitTrigger`, `disposition.decidedBy` |
| history of class changes | `classificationHistory[]` (§7) |

### 4.1 First-party claims and independent evidence are different things

Each evidence item has a `type` and a `producer` (a group token and its relation to the authors: `author`, `author-affiliated` or `independent`).

| Type | Meaning | Producer | Counted for |
|---|---|---|---|
| `first-party-claim` | the authors' own paper table, README, model card or release note | `author` or `author-affiliated` | traceability only |
| `repetition` | any other page that restates a figure (blog, aggregator, model hub card, survey, "papers with code" style listing) | any | **nothing**; it must name what it `repeats` |
| `independent-reproduction` | an independent group ran the exact checkpoint, or the method, and reported **its own measurement** | `independent`, with its `independenceBasis` | independent technical evidence |
| `independent-benchmark` | an official benchmark server or recognised leaderboard that computes the score itself on held-out labels | `independent` | independent technical evidence (scope `method`) |
| `adoption` | a named downstream use by an independent group: framework integration, a published system built on it | `independent` | the distinct-group count only |
| `public-scrutiny` | issue history, errata, failed reproductions, integrity reports | any | context; a failed reproduction goes in `caveats` too |

**[checked]**:
- a first-party claim must come from an author group; an independent item must come from a group outside `authors.groups` and state its independence basis;
- an independent item may not cite the same source document as any first-party item;
- producer groups are counted once however many items they contribute.

### 4.2 Benchmark laundering

Laundering is a first-party number that appears to be confirmed because many pages repeat it. The ledger defeats it by construction **[checked]**:
- a restatement is typed `repetition` and must point (`repeats`) to the item it copies. Chains are followed to their root, and a cycle is refused;
- a claim's `originEvidenceId` must be the root: a non-repetition item. A claim whose "origin" is a repetition is refused;
- repetitions count toward nothing. Five websites repeating one README figure are one first-party claim, and the candidate stays at most `emerging`.

The residual risk is a human mislabelling a repetition as a reproduction. The validator narrows it: a reproduction must be from an independent group, must not reuse a first-party source document, and (for exact scope) must name the exact bytes. The independent reviewer checks every item typed `independent-*` against its source (§9).

### 4.3 Exact artefact identity

A candidate is its bytes, not its name (MSR method §5).
- `identity.files[].sha256` is the SHA-256 of the exact bytes MAVI would evaluate. `UNKNOWN` is allowed only while `DISCOVERED`, `REFERENCE_ONLY`, `DEFERRED` or `NOT_SHORTLISTED`.
- **`SHORTLISTED` requires** **[checked]**:
  - an immutable revision and every weight file hashed;
  - provenance High or Medium;
  - for a method candidate, the method code revision;
  - every claim's origin snapshotted by retrieved-document SHA-256 (MSR method §6: R rows relied on are snapshotted at `PROTOCOL_FROZEN`).
- An `exact-checkpoint` evidence item must name the same bytes (a SHA-256 in `identity.files`, or the same repository and revision). Otherwise it is evidence about a different artefact and the ledger is refused **[checked]**.
- **Once pinned, bytes never change under the same entry.** A different checkpoint, even under the same name, is a new candidate entry with a new id **[checked]** (§7). Two entries may not share a weight-file hash **[checked]**.
- Later evaluation binds the same bytes: every evaluated artefact in the decision summary must equal the ledger identity **[checked]** (§8). The rest of the artefact binding (preprocessing as data with its hash, runtime requirements, licence documents with their retrieved-bytes hashes) is recorded in the MSR candidate card (MSR method §5) and the frozen protocol.

## 5. Person and vehicle stay separate

- Each event has its own ledger. `msr-person-attributes-2026-01` covers `person` with sub-tasks `T-PC` and `T-PO`. `msr-vehicle-attributes-2026-01` covers `vehicle` with `T-VC`.
- Every claim names its sub-task and object class, which must belong to its own ledger **[checked]**. A person benchmark cannot support a vehicle candidate.
- A family that appears in both events (for example a shared backbone) has one entry **in each ledger**, classified separately on the evidence relevant there. There is no combined person-and-vehicle ranking, and no classification carries across events.
- The person event may still select a **composition** (MSR method §5.1). Each component is classified in the person ledger on its own.

## 6. Licence and deployment stay separate

Discovery and credibility are **licence-blind**. A technically strong candidate is never excluded, demoted or left unclassified because of its licence. The ledger has no licence field.

The licence/deployment axis is recorded afterwards in the MSR record §7 (MSR method §2, §4, §5). The rights listed there are assessed **separately**:
- code licence and weights licence;
- the right to evaluate;
- the right to run operationally;
- modification and fine-tuning;
- derivative models;
- redistribution, including bundling the weights in a MAVI Model Pack or offline kit;
- end-use restrictions;
- training-data and provenance concerns.

MAVI is non-commercial, so commercial-use permission is not required on its own (MSR method §2.1). "Free to use" is never read as "redistributable". A candidate may be usable when the operator obtains the weights separately, even when MAVI may not bundle them. The profile's delivery route decides whether redistribution is exercised. The standard term is **"cleared for the declared MAVI deployment profile `<profile id>`"**.

Evaluation permission remains MSR method §2's one carve-out. A candidate MAVI may not lawfully run becomes `REFERENCE_ONLY` with reason class `evaluation-permission`. Its credibility class is still computed and recorded.

The record keeps the five outputs apart (MSR method §9). The decision summary makes the derived ones impossible to assert falsely **[checked]**:

| Output | Derived from |
|---|---|
| strongest reported / reference candidate | class R evidence; any ledger candidate, marked "not reproduced by MAVI" |
| highest task-quality evaluated candidate | maximum task-quality score over **every** evaluated candidate |
| strongest evaluated technical candidate | maximum comparative score over the evaluated candidates that passed the technical gates. **Licence and credibility are not read** |
| strongest candidate cleared for `<profile>` | the maximum comparative score among gate-passing candidates whose licence status for that profile is `CLEARED` |
| implementation candidate or composition | owner choice under §8 |

A technically strongest candidate that is not cleared stays recorded as the strongest evaluated technical candidate, and the gap to the strongest cleared one is reported.

## 7. Classification history and promotion

Every class the entry has ever held is an entry in `classificationHistory`:
- the date;
- `from` (the previous class, or null for the first entry) and `to`;
- the reason;
- the evidence ids relied on;
- `recordedBy` and `reviewedBy`, who must be different people;
- the identity hash (`identitySha256`: the canonical SHA-256 of the entry's `identity` block);
- the pinned weight hashes (`checkpointSha256s`, empty until pinned).

**[checked]**:
- entries are chronological and chain (`from` equals the previous `to`);
- every cited evidence item exists and was recorded no later than the entry;
- an entry whose `to` is `established` must be justified by the evidence active on its date. A promotion can never be backdated ahead of its evidence;
- the last entry equals the computed current class **and** the current identity hash. Adding evidence that changes the class, or editing the identity, therefore fails until a history entry records it;
- once `checkpointSha256s` is non-empty, it never changes in a later entry, and it equals the current weight hashes. A changed checkpoint needs a new candidate entry.

**Promoting an important new entrant.** A candidate first recorded as `reference-only` or `emerging` is promoted only when new evidence meets §3.2 and a history entry records it. The route depends on the event state:
- **before `PROTOCOL_FROZEN`**: it may be shortlisted in that event;
- **after `PROTOCOL_FROZEN`**: it enters only through a numbered protocol revision, which voids the results it could bias (MSR method §3.1), or through a new event (MSR method §12);
- a candidate that appears after the event closes is carried into the next event's discovery with its last class (MSR method §12 step 3).

Demotion follows the same rule, for example after a retraction or an integrity conflict. Evidence is never deleted: a retracted item keeps its record with `retracted: {at, reason}`.

## 8. Implementation eligibility

MSR method §4 is extended. The implementation candidate, and each component of an implementation composition, must be:
- evaluated in the bake-off and past every technical gate;
- `CLEARED` for **each** named target profile;
- **`established`** (or `mavi-owned`), with a history entry reaching `established` dated on or before the decision. An `emerging` candidate that won the bake-off stays recorded at its rank (§6). It needs a recorded promotion before it can be implemented;
- bound to the exact evaluated bytes, the ledger hash and the protocol hash of **one** event.

These are checked in the machine-readable **decision summary** (`mavi-model-selection-decision-v1`, `<event-id>-decision.json`). It is written at `TECHNICAL_DECISION_RECORDED` or later (S2c.4 onward), never in S2c.2a. Its checks **[checked]**:
- every `SHORTLISTED` ledger candidate is in the evaluated set, and every evaluated candidate was shortlisted. A strong candidate with an inconvenient licence cannot be quietly dropped;
- each evaluated artefact equals the ledger identity: the same weight hashes for a checkpoint, the backbone hashes included for a method, a MAVI commit for a baseline;
- the decision cites the ledger's canonical SHA-256;
- the derived outputs of §6 are recomputed;
- an implementation is named only at `QUALIFICATION_PENDING` or `CLOSED`, and outcomes are consistent with the state.

The markdown MSR record remains the human-readable decision record. The summary is a checked projection of MSR method §9, not a second authority.

## 9. Review obligations (not machine-checkable)

The independent reviewer named in the event's frozen protocol confirms, before `PROTOCOL_FROZEN`:
- each `independent-*` item really is an independent measurement, and not a repetition mislabelled. For each, the reviewer opens the source;
- the venue and "established group" bases, and the author-group tokens (affiliations cannot be proven by a validator);
- that discovery covered the survey's sources plus a dated re-survey. No candidate is left out because it was inconvenient: an unlisted strong candidate is a review finding;
- the frozen protocol records the ledger's SHA-256 (template `selection-protocol.md` §2).

## 10. 500-camera standing requirement

Scale to up to 500 cameras remains a permanent selection constraint (MSR method §7.1, S2c plan §14.1). Credibility and reported accuracy say nothing about it. Reported runtime figures (parameters, claimed latency) may be recorded as claims, but they are class R and decide nothing. The bake-off decides from MAVI measurements (M-E) and the reproducible projection:
- inference cost;
- memory;
- CPU and GPU characteristics;
- throughput and batching;
- operational scaling;
- offline deployment constraints.

Nothing in this revision, and no ledger, claims 500-camera qualification.

## 11. Invariants

| # | Invariant | Enforced by |
|---|---|---|
| I1 | A candidate cannot enter the shortlist without known provenance: `SHORTLISTED` needs class `established`/`emerging` (or `mavi-owned`), provenance High/Medium and pinned bytes | validator |
| I2 | First-party repetition cannot masquerade as independent evidence | validator (repetition typing, root tracing, producer independence, distinct sources, distinct groups) |
| I3 | The credibility class is computed from recorded evidence, never asserted | validator |
| I4 | Credibility classification cannot alter measured MAVI technical results | the ledger holds no MAVI result; the decision summary ranks by recorded scores and never reads credibility |
| I5 | Licence status cannot rewrite the technical ranking, and discovery is licence-blind | no licence field in the ledger; the strongest-technical output ignores licence; the strongest-cleared output is derived |
| I6 | A technically strongest but deployment-ineligible candidate remains recorded | the evaluated set equals the shortlist; strongest technical derived without licence |
| I7 | The implementation candidate traces to one closed-or-closing MSR event and exact artefacts | decision summary: event id, ledger hash, evaluated bytes equal ledger bytes |
| I8 | Class changes leave an auditable reason, and promotions cannot precede their evidence | history rules (§7) |
| I9 | An emerging candidate cannot become the implementation candidate without a recorded promotion | implementation eligibility (§8) |
| I10 | A name cannot keep its entry while its bytes change | identity hash and pinned-hash history (§7); no shared weight hash across entries |
| I11 | Person and vehicle evidence cannot be conflated | one ledger per event; claim sub-task and object class checks |
| I12 | No S2c.2a artefact claims a MAVI bake-off result | pre-evaluation dispositions only; strict fields; no decision summary exists in S2c.2a |

## 12. Loopholes considered

| Attack | Outcome |
|---|---|
| Promote an unknown model with five websites copying one README figure | five `repetition` items that collapse to one first-party origin; 0 independent groups, so at most `emerging` |
| Type those websites as `independent-reproduction` instead | each must be from a non-author group with a basis and a source distinct from the first-party one. For exact scope it must name the pinned bytes; the reviewer checks each (§9). Residual human trust, P3 |
| Drop the strongest technical candidate because its licence is inconvenient | its shortlist entry forces it into the evaluated set; the strongest-technical output is recomputed without licence |
| Present licence clearance as technical superiority | "strongest cleared" is a separate derived field; the standard sentence of MSR method §9 applies only when it coincides |
| Shortlist a model with unknown checkpoint provenance | Low confidence makes it `reference-only`, and `SHORTLISTED` is refused |
| Implement an `emerging` model quietly | implementation requires `established` with a dated history entry |
| Backdate a promotion | a promotion must be justified by the evidence active on its date |
| Keep the name, swap the checkpoint | the identity hash in the last history entry and the pinned-hash rule refuse it; a new entry is required |
| Use person benchmarks for a vehicle candidate | claim object class and sub-task are checked against the ledger |
| Make a candidate `reference-only` on credibility grounds when its evidence says `emerging` | credibility-reason `REFERENCE_ONLY` needs computed class `reference-only` |
| Hide a demotion by deleting evidence | evidence is retracted with a date and reason, never removed; the last history entry must match the recomputed class |
| Count stars or downloads | popularity signals are never read |
| One group posting three reproductions | distinct producer groups are counted once |
