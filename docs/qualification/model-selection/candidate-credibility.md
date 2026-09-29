# Candidate Admissibility and Credibility (MSR method v1, revision M1)

**Status:** Proposed in slice S2c.2a (planning/protocol only). It becomes governing when its change passes independent review and exact-head CI and merges; that merge is the acceptance event. It is a revision of **MSR method v1** (`README.md` §14), not a new method and not a new source of architectural truth.
**Scope:** every Model Selection Event under MSR method v1, for every capability. S2c (`msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`) is its first use.
**Machine checks:** `tools/qualification/model_selection/credibility.py`, run as `python tools/qualification/model_selection_check.py`. The repository test suite validates every committed ledger, frozen ledger and decision summary. Rules marked **[checked]** are enforced by the validator; the rest are review rules (§9).
**What this revision does not do:** it selects, downloads, runs or benchmarks no model. It changes no ADR, contract, lifecycle state, Model Pack, Runtime Pack or binding, and it writes no ledger for a real event. It records no MAVI measurement and claims no bake-off result.

---

## 1. Why this gate exists

A high benchmark number is not credibility, and a popular repository is not technical quality. MSR method v1 already separates the technical, engineering and licence assessments (§2). It does not yet say **which candidates are credible enough to enter serious evaluation**, or how to tell a genuinely confirmed result from one first-party number repeated by many websites.

**Normative rule (R-CRED).** An unverified community upload, or an obscure checkpoint whose only performance evidence is self-reported, **cannot become a MAVI implementation candidate on the strength of those claims**. Such a candidate may be surveyed and recorded.
- A candidate whose provenance is not pinned to its original source is `reference-only` and cannot be shortlisted **[checked]**.
- An `emerging` candidate (pinned provenance, but no independent confirmation) is **normally held as `REFERENCE_ONLY`** for credibility **[checked: that disposition is allowed]**.
- Shortlisting an `emerging` candidate for measurement is an exception. It requires a recorded basis and a second reviewer **[checked]**. Even then, it never becomes the implementation candidate without a recorded promotion to `established` (§8) **[checked]**.
- Promotion is a recorded event, never a silent reclassification (§7).

## 2. Three layers, never merged

| Layer | Question | Where recorded | May it change the technical ranking? |
|---|---|---|---|
| **1. Credibility / admissibility** (this revision) | Is the artefact identifiable, traceable and externally supported enough to take seriously? | the event's **External Evidence Ledger** (§4) | **no** |
| **2. Independent technical evidence** | What do sources other than the authors report about it? | the ledger's evidence items and claims (class R, MSR method §6) | **no**; class R evidence never decides a gate |
| **3. Controlled MAVI bake-off** | How does it perform on MAVI data under the frozen protocol? | MSR record §4–§6 (classes M-D, M-E) and the decision summary (§8) | this layer **is** the technical ranking |

- Layer 3 never feeds layer 1. A MAVI measurement is never external evidence. The ledger refuses:
  - evidence produced by the reserved group `mavi` or any `mavi-…` group;
  - sources that are repository paths or qualification/model-selection documents, or that name MAVI;
  - claims on a MAVI dataset **[checked]**.

  A candidate therefore cannot promote itself with its own bake-off result.
- External reputation or popularity never determines the technical winner. The ranking comes only from layer 3, under MSR method §8.
- A high reported score never establishes credibility by itself.
- Credibility is **not a weighted criterion** and never enters the comparative score. The engineering criterion "implementation stability and maintenance status" (S2c plan §9.5) is scored by its own frozen rule, and it may not reuse the credibility class.
- Licence status is a separate axis (MSR method §2, §4) and is **not in the ledger at all** **[checked]**.

## 3. Candidate credibility classes

Each ledger candidate has exactly one class. It is **computed** from the recorded evidence by §3.2, and the declared class must equal the computed class **[checked]**. Two reviewers who record the same evidence therefore reach the same class.

| Class | Meaning | Allowed dispositions (MSR method §4) |
|---|---|---|
| `established` | pinned to the original source; recognised publication; independent technical confirmation; support from at least two independent producer groups | any pre-evaluation disposition. Never with a `credibility` reason. **Implementation-eligible** (§8) |
| `emerging` | pinned provenance (original source, or a documented official conversion); architecture documented first-party; every claim traceable; independent support insufficient | **default `REFERENCE_ONLY` (credibility)**. `SHORTLISTED` only with `emergingShortlistBasis` and a second reviewer. Also `NOT_SHORTLISTED` (technical) or `DEFERRED`. **Not implementation-eligible** until promoted |
| `reference-only` | origin known, but provenance confidence Low, architecture undocumented, or a claim untraceable | `DISCOVERED`, `REFERENCE_ONLY`, `NOT_SHORTLISTED` (technical), `DEFERRED`. **Never `SHORTLISTED`** |
| `excluded-discovery` | no identifiable original source, unknown publisher, no author group, or an integrity conflict (the bytes conflict with what the source publishes) | `DISCOVERED` or `NOT_SHORTLISTED` with reason class `credibility`; retained in the ledger |
| `mavi-owned` | a MAVI-owned deterministic baseline (for example PC-B0, VC-B0), identified by a MAVI commit | as MSR method v1. It may be shortlisted before its code exists, because the commit is bound at evaluation (§8) |

A **method candidate** (an architecture MAVI trains or fits) is classified on its backbone checkpoint identity, its published method and its code revision. The artefacts MAVI trains are declared in the decision summary with their training-manifest hash (§8).

A **checkpoint used for several sub-tasks** is one entry listing those sub-tasks (for example VTFPAR++ as PC-9/PO-8). Method entries that share one backbone with separate heads (MSR method §5.1, S2c plan §9.5a; for example PC-1 and PO-1 on one SigLIP 2 tower) may share its weight hashes, but only with an **identical** identity block. Any other sharing of weight bytes between entries is refused **[checked]**.

### 3.1 Provenance confidence

Computed **[checked]**:

| Confidence | Rule |
|---|---|
| **High** | source repository and organisation known; immutable revision (40- or 64-hex commit or hub revision, never a floating tag); every weight file hashed; publisher is the original author or organisation |
| **Medium** | as High, except that the publisher is a recognised framework maintainer who converted or re-hosted the original, with the derivation pinned: source repository, source revision, source SHA-256, and a non-repetition item documenting the conversion |
| **Low** | anything else: a third-party upload, an unpinned identity, a floating tag, a missing hash, or an integrity conflict recorded on or before the date considered |

A candidate discovered by name but not yet pinned is Low, and so computes as `reference-only` until it is pinned. Discovery precedes pinning.

### 3.2 Classification rule

The rule is computed on the evidence active at a date: recorded on or before that date and not retracted by it. Steps, in order:

1. `mavi-baseline` kind → `mavi-owned`.
2. Integrity conflict recorded by the date, repository unknown, publisher unknown or no author group known → `excluded-discovery`.
3. Any of the following → `reference-only`:
   - provenance confidence Low;
   - architecture not documented by an active `first-party-claim`;
   - no task-quality claim;
   - any claim whose origin is not an active `first-party-claim`, `independent-reproduction` or `independent-benchmark`.
4. `established` when **all** of these hold:
   - provenance confidence High;
   - publication status `peer-reviewed` (venue named), `preprint-established-group` (basis recorded) or `official-model-documentation`;
   - at least one active **independent technical** item (`independent-reproduction` or `independent-benchmark`), for this ledger's object class and one of the candidate's sub-tasks. For a checkpoint candidate the item has scope `exact-checkpoint` and names the same bytes (§4.3);
   - the active independent technical and adoption items come from **at least two distinct independent producer groups**.
5. Otherwise → `emerging`.

GitHub stars, downloads and citation counts are **popularity signals**: recorded for context and never read by any rule **[checked]**. Adoption counts only as a **named downstream use by an independent group**, never as a number.

## 4. External Evidence Ledger

There is one ledger per Model Selection Event: `docs/qualification/model-selection/<capabilityId>/<event-id>-evidence-ledger.json`, schema `mavi-external-evidence-ledger-v1`. The field-by-field template is `templates/external-evidence-ledger.md`. The ledger:
- covers exactly one event, one capability and one object class. For the S2c capabilities the object class and sub-tasks are fixed: `person-attributes` → `person` with `T-PC`, `T-PO`; `vehicle-attributes` → `vehicle` with `T-VC` **[checked]**;
- holds every candidate the event considered seriously, including every `excluded-discovery`, so a later reader can reconstruct each inclusion and exclusion;
- holds **external evidence only**:
  - it has no field for a MAVI measurement and refuses MAVI-produced evidence (§2);
  - it admits only the pre-evaluation dispositions `DISCOVERED`, `SHORTLISTED`, `NOT_SHORTLISTED`, `REFERENCE_ONLY` and `DEFERRED`;
  - it refuses every unknown field **[checked]**.

  No ledger can claim that a candidate passed a MAVI bake-off;
- has **no licence field** **[checked]**. A licence reason for `NOT_SHORTLISTED` or `DEFERRED` is refused even in free text **[checked]**. The licence axis lives in the MSR record §7 and the decision summary (§8);
- contains no weights, imagery or credentials. Sources are citations or URLs;
- uses no future date, and records no evidence before it was retrieved **[checked]**. The dates themselves are attested by the recorder and anchored by Git history (§9).

Each candidate entry records every field the S2c.2a brief requires:

| Required content | Ledger field |
|---|---|
| candidate/model name; exact checkpoint identifier; checkpoint hash | `candidateName`; `identity.repository`, `identity.revision`, `identity.tag`, `identity.files[].path`, `identity.files[].sha256` |
| original source; repository/organisation; checkpoint provenance | `identity.repository`, `identity.organisation`, `identity.publisher`, `identity.derivation`, `identity.integrityConflict` |
| authors/institution | `authors.names`, `authors.groups`, `authors.affiliatedGroups` |
| publication and venue status | `publication.status`, `publication.venue`, `publication.reference`, `publication.basis` |
| architecture | `architecture.description`, `architecture.documentedBy` |
| claimed benchmark; origin of the claimed benchmark | `claims[]` with `originEvidenceId` |
| independently reported benchmark evidence; independent reproductions | `evidence[]` of type `independent-benchmark` / `independent-reproduction` |
| adoption/maturity evidence | `evidence[]` of type `adoption`; `popularitySignals` (never counted) |
| known caveats and public scrutiny | `caveats`; `evidence[]` of type `public-scrutiny` |
| provenance confidence; credibility classification | `classification.provenanceConfidence`, `classification.class` (both recomputed) |
| shortlist disposition; reason | `disposition.status`, `reasonClass`, `reason`, `revisitTrigger`, `decidedBy`, and for an emerging shortlist `emergingShortlistBasis` and `reviewedBy` |
| history of class changes | `classificationHistory[]` (§7) |

### 4.1 First-party claims and independent evidence are different things

Each evidence item has a `type` and a `producer`: a group token, and its relation to the authors (`author`, `author-affiliated` or `independent`).

| Type | Meaning | Producer | Counted for |
|---|---|---|---|
| `first-party-claim` | the authors' own paper table, README, model card or release note | `author` or `author-affiliated` | traceability; architecture documentation |
| `repetition` | any other page restating a figure: blog, aggregator, model-hub card, survey, leaderboard-style listing | any | **nothing**; it must name what it `repeats` |
| `independent-reproduction` | an independent group ran the exact checkpoint, or the method, and reported **its own measurement** | `independent`, with `independenceBasis` | independent technical evidence |
| `independent-benchmark` | an official benchmark server or recognised leaderboard that computes the score itself on held-out labels | `independent` | independent technical evidence (scope `method`) |
| `adoption` | a named downstream use by an independent group, such as a framework integration or a published system built on it | `independent` | the distinct-group count only |
| `public-scrutiny` | issue history, errata, failed reproductions, integrity reports | any | context. A failed reproduction also goes in `caveats` |

**[checked]**:
- an `author` producer is in `authors.groups`, and an `author-affiliated` producer is in `authors.affiliatedGroups`. The two lists are disjoint;
- an `independent` producer is in neither list;
- a first-party claim is never `independent`;
- independent technical items name their sub-task and object class, which must be the candidate's and the ledger's;
- producer groups are counted once however many items they contribute.

### 4.2 Benchmark laundering

Laundering makes a first-party number look confirmed because many pages repeat it. The ledger defeats it by construction **[checked]**:
- **Repetitions are typed and traced.** A restatement is typed `repetition` and must point (`repeats`) at the item it copies. Chains are followed to their root, and a cycle is refused.
- **Claims cite their root.** A claim's `originEvidenceId` must be the root: a first-party claim or an independent technical item, never a repetition or a scrutiny page.
- **Repetitions count for nothing.** Five websites repeating one README figure are one first-party claim, and the candidate stays at most `emerging`.
- **Re-typing a page does not help.** An independent item must be a distinct document: its source, normalised for scheme, `www.`, query, fragment, case and trailing slash, and its retrieved-document SHA-256 must differ from those of **every other item in the entry**, whatever its type. A repeating page re-typed as a "reproduction", or one page cited under two groups, is refused.

The residual risk is a human mislabelling a genuinely different page (for example a blog that copies a figure without saying so) as a reproduction. The reviewer opens every `independent-*` source (§9).

### 4.3 Exact artefact identity

A candidate is its bytes, not its name (MSR method §5).
- **Pinning.** `identity.files[].sha256` is the SHA-256 of the exact bytes MAVI would evaluate. `UNKNOWN` is allowed only while the candidate is not `SHORTLISTED`.
- **`SHORTLISTED` requires** **[checked]**:
  - an immutable revision with every weight file hashed;
  - provenance High or Medium;
  - for a method candidate, an immutable method-code revision;
  - every claim origin and every active independent item snapshotted by its retrieved-document SHA-256 (MSR method §6).
- **Exact-scope evidence.** An `exact-checkpoint` item names **all** the pinned weight hashes, or the same repository and immutable revision. Otherwise it is evidence about a different artefact and the ledger is refused **[checked]**.
- **Fixed bytes per entry.** Once pinned, bytes never change under the same entry: a different checkpoint, even under the same name, is a new candidate entry with a new id **[checked]** (§7).
- **Evaluation binds the same bytes.** Each evaluated artefact set in the decision summary equals the ledger identity, plus the MAVI-trained artefacts declared with their training-manifest hashes **[checked]** (§8).
- **Other bindings.** Preprocessing (as data, with its hash), runtime requirements and licence documents (with retrieved-bytes hashes) are recorded in the MSR candidate card (MSR method §5) and the frozen protocol.

## 5. Person and vehicle stay separate

- Each event has its own ledger, and each known capability's object class and sub-tasks are fixed (§4) **[checked]**.
- Every claim and every independent technical item names its sub-task and object class, which must belong to its own ledger and candidate **[checked]**. A person benchmark cannot support a vehicle candidate.
- A family that appears in both events has one entry **in each ledger**, classified separately on the evidence relevant there. There is no combined ranking, and no classification carries across events.
- The person event may select a **composition** (MSR method §5.1). Each component is classified in the person ledger, and each must be implementation-eligible (§8).

## 6. Licence and deployment stay separate

Discovery and credibility are **licence-blind**. A technically strong candidate is never excluded, demoted or left unclassified because of its licence.

The licence/deployment axis is recorded afterwards in the MSR record §7 (MSR method §2, §4, §5). The rights assessed there are separate:
- code licence;
- weights licence;
- evaluation;
- operational running;
- modification and fine-tuning;
- derivative models;
- redistribution, including bundling in a MAVI Model Pack or offline kit;
- end-use restrictions;
- training-data and provenance concerns.

MAVI is non-commercial, so commercial-use permission is not required on its own (MSR method §2.1). "Free to use" is never read as "redistributable". A candidate may be usable when the operator obtains the weights separately, even where MAVI may not bundle them; the profile's delivery route decides whether redistribution is exercised. The standard term is **"cleared for the declared MAVI deployment profile `<profile id>`"**.

Evaluation permission remains MSR method §2's one carve-out. A candidate MAVI may not lawfully run is `REFERENCE_ONLY` with reason class `evaluation-permission`, and its credibility class is still computed. Under M1, an `excluded-discovery` is `NOT_SHORTLISTED` on credibility grounds whatever its evaluation permission (README §2).

The five outputs stay apart (MSR method §9). The decision summary makes the derived ones impossible to assert falsely **[checked]**:

| Output | How it is established |
|---|---|
| strongest reported / reference candidate | a recorded judgement over class R evidence. It must resolve to a ledger claim and carry the label "reported, not reproduced by MAVI" **[checked]**. It is not derived, because reported figures on different datasets are not comparable numbers |
| highest task-quality evaluated candidate | derived: maximum task-quality score over **every** evaluated candidate |
| strongest evaluated technical candidate | derived: maximum comparative score over the evaluated candidates that passed the technical gates. **Licence and credibility are not read** |
| strongest candidate cleared for `<profile>` | derived: maximum comparative score among gate-passing candidates `CLEARED` for that profile |
| implementation candidate or composition | owner choice under §8 |

A technically strongest candidate that is not cleared, or not `established`, stays recorded as the strongest evaluated technical candidate. The gap to the implementation candidate is reported.

## 7. Classification history, freezing and promotion

Every class the entry has held is an entry in `classificationHistory`, with:
- `at`, `from`, `to` and the reason;
- the evidence ids relied on;
- `recordedBy` and `reviewedBy`: different people, compared case- and whitespace-insensitively;
- the identity hash (`identitySha256`: the canonical SHA-256 of the entry's `identity` block);
- the pinned weight hashes (`checkpointSha256s`, empty until pinned).

**[checked]**:
- entries are chronological and chain: `from` equals the previous `to`;
- cited evidence exists and was recorded no later than the entry;
- no entry claims a higher class than the evidence active on its date supports, so a promotion cannot be backdated ahead of its evidence;
- an entry reaching `established` is supported by the evidence **it cites**;
- an `emerging` or `established` entry has pinned bytes;
- the last entry equals the computed current class and the current identity hash. New evidence that changes the class, or an identity edit, fails until a history entry records it;
- once `checkpointSha256s` is non-empty it never changes, and it equals the current weight hashes.

**Freezing makes the ledger append-only.** At `PROTOCOL_FROZEN` the ledger is copied to `<event-id>-evidence-ledger-frozen.json`, and the frozen protocol records the copy's canonical SHA-256. The repository check requires that citation **[checked]**. From then on, the working ledger must be an append-only evolution of the frozen copy **[checked]**:
- every frozen candidate, evidence item, claim and history entry is kept unchanged. An evidence item may only gain `retracted`;
- the shortlist and the identity of every shortlisted candidate are fixed.

A changed shortlist needs a numbered protocol revision, which voids the results it could bias (MSR method §3.1) and freezes a new copy. Before freezing, ledger edits are ordinary reviewed Git changes. `python tools/qualification/model_selection_check.py evolution <old> <new>` checks two versions on request.

**Promoting an important new entrant.** A `reference-only` or `emerging` candidate is promoted only when new evidence meets §3.2, and a history entry records it.
- Before `PROTOCOL_FROZEN`, it may then be shortlisted in that event.
- After `PROTOCOL_FROZEN`, it enters only through a numbered protocol revision, or through a new event (MSR method §12).
- A candidate that appears after the event closes is carried into the next event's discovery with its last class (MSR method §12 step 3).

Demotion follows the same rule, for example after a retraction or an integrity conflict. Evidence is never deleted: a retracted item keeps its record with `retracted: {at, reason}`, and an integrity conflict carries its date.

## 8. Implementation eligibility and the decision summary

MSR method §4 is extended. The implementation candidate, and each component of an implementation composition, must be **[checked]**:
- evaluated in the bake-off and past every technical gate;
- `CLEARED` for **each** named target profile;
- **`established`** (or `mavi-owned`) now, **and** in the history entry in force on the decision date. An `emerging` winner stays recorded at its rank (§6), and it needs a recorded promotion before it can be implemented;
- bound to the exact evaluated bytes, the ledger hash, the frozen-ledger hash and the protocol hash of **one** event.

These rules are checked in the **decision summary** (`mavi-model-selection-decision-v1`, `<event-id>-decision.json`). It is written at `TECHNICAL_DECISION_RECORDED` or later (S2c.4 onward), never in S2c.2a. **[checked]**:
- the decision cites the current ledger and the frozen ledger by canonical SHA-256. The repository check additionally requires `protocolSha256` to equal the LF-normalised SHA-256 of `<event-id>-protocol.md`;
- the evaluated set equals the **frozen** shortlist, and the working ledger's shortlist has not changed since. A strong candidate with an inconvenient licence cannot be dropped, before or after freezing;
- each evaluated artefact set equals the ledger identity:
  - a checkpoint: exactly its weight hashes;
  - a method: its backbone hashes plus at least one declared MAVI-trained artefact with its training-manifest hash, and nothing undeclared;
  - a baseline: a MAVI commit;
- the derived outputs of §6 are recomputed;
- an implementation is named only at `QUALIFICATION_PENDING` or `CLOSED`, and the outcome is consistent with the state and the implementation.

The markdown MSR record remains the human-readable decision record. The summary is a checked projection of MSR method §9, not a second authority.

## 9. Review obligations (not machine-checkable)

Before `PROTOCOL_FROZEN`, the independent reviewer named in the event's frozen protocol confirms:
- **Independent items.** Each `independent-*` item is a genuinely independent measurement or use, not an unmarked copy. The reviewer opens every source.
- **Attested facts.** The venue and "established group" bases; author, affiliated and independent group assignments (affiliation cannot be proven by a validator); publisher claims; evidence dates.
- **Candidate kind.** A released checkpoint used end to end is a `checkpoint` candidate, not a `method`. The decision summary requires a method to have MAVI-trained artefacts.
- **Free text.** No licence reasoning is placed under a technical disposition.
- **Discovery coverage.** Discovery covered the survey's sources plus a dated re-survey, and no candidate was left out because it was inconvenient. An unlisted strong candidate is a review finding.
- **Freeze record.** The frozen protocol records the frozen ledger's SHA-256 (template `selection-protocol.md` §2).

## 10. 500-camera standing requirement

Scale to up to 500 cameras remains a permanent selection constraint (MSR method §7.1, S2c plan §14.1). Credibility and reported accuracy say nothing about it. Reported runtime figures (parameters, claimed latency) may be recorded as `runtime` claims, but they are class R and decide nothing. The bake-off decides from MAVI measurements (M-E) and the reproducible projection:
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
| I1 | No shortlist without known provenance: `SHORTLISTED` needs `established`/`emerging` (with basis and second reviewer), provenance High/Medium and pinned bytes. A `mavi-owned` baseline is bound to its commit at evaluation | validator |
| I2 | First-party repetition cannot masquerade as independent evidence | validator (§4.2) |
| I3 | The credibility class is computed from recorded evidence, never asserted | validator |
| I4 | Credibility cannot alter measured MAVI technical results, and MAVI results cannot alter credibility | no MAVI result or MAVI-produced evidence in the ledger; the ranking reads recorded scores only |
| I5 | Licence cannot rewrite the technical ranking, and discovery is licence-blind | no licence field or licence reason in the ledger; derived outputs ignore licence except "strongest cleared" |
| I6 | A technically strongest but deployment-ineligible candidate remains recorded | evaluated set equals the frozen shortlist; strongest technical derived without licence or credibility |
| I7 | The implementation candidate traces to one MSR event and exact artefacts | decision summary: event id, ledger, frozen-ledger and protocol hashes; evaluated bytes equal the ledger bytes plus declared MAVI-trained artefacts |
| I8 | Class changes leave an auditable reason; promotions cannot outrun their evidence; after freeze nothing is rewritten | history rules and the frozen-ledger evolution check (§7) |
| I9 | An `emerging` candidate cannot become the implementation candidate without a recorded promotion | implementation eligibility on the decision date (§8) |
| I10 | A name cannot keep its entry while its bytes change | identity hash and pinned-hash history; no weight bytes shared except an identical method backbone |
| I11 | Person and vehicle evidence cannot be conflated | fixed event scopes; claim and technical-evidence sub-task and object-class checks |
| I12 | No S2c.2a artefact claims a MAVI bake-off result | pre-evaluation dispositions only; strict fields; no MAVI evidence; no ledger or decision summary exists in S2c.2a |

## 12. Loopholes considered

| Attack | Outcome |
|---|---|
| Promote an unknown model with five websites copying one README figure | five `repetition` items collapse to one first-party origin; 0 independent groups, so at most `emerging` |
| Re-type those pages as `independent-reproduction`, or add `#table-2` / `http` variants of the README URL | refused: an independent item must be a distinct document by normalised source and retrieved bytes |
| Have an affiliated spin-off act as the "independent" group | refused: affiliated groups are declared and can never be `independent`. Undeclared affiliation is a review item |
| Record MAVI's own bake-off win as an independent reproduction | refused: reserved `mavi` groups, MAVI sources and MAVI datasets |
| Drop the strongest technical candidate because its licence is inconvenient | the frozen shortlist forces it into the evaluated set; strongest technical is recomputed without licence |
| Edit the shortlist after freeze, then cite the new ledger | refused: the decision checks the frozen ledger, and the working ledger must evolve append-only with a fixed shortlist |
| Present licence clearance as technical superiority | "strongest cleared" is a separate derived field; MSR method §9's standard sentence applies only when the two coincide |
| Shortlist a model with unknown checkpoint provenance | Low confidence makes it `reference-only`, and `SHORTLISTED` is refused |
| Shortlist an `emerging` model quietly | refused without a recorded basis and a second reviewer |
| Implement an `emerging` model, or one that was `emerging` on the decision date | refused: implementation requires `established` in the history entry in force on the decision date |
| Backdate a promotion or cite evidence after its date | refused: no entry may overclaim on its date; cited evidence must predate it and support it; no future dates; nothing recorded before it was retrieved |
| Keep the name, swap the checkpoint | refused by the identity hash and the pinned-hash history; after freeze, a shortlisted identity is fixed |
| Smuggle a community fine-tune in as part of a method's artefacts | refused: evaluated bytes are the backbone plus declared MAVI-trained artefacts with training manifests |
| Use person evidence for a vehicle candidate, or widen a ledger's sub-tasks | refused: fixed event scopes; sub-task and object class on claims and technical evidence |
| Park an evidence-supported `established` candidate as reference-only for "credibility" | refused: a credibility reason must match the computed class |
| Hide a demotion by deleting evidence | before freeze a Git-reviewed deletion; after freeze refused (append-only); the last history entry must match the recomputed class |
| Count stars or downloads, or one group posting three reproductions | popularity signals are never read; producer groups count once |

Residual human trust (P3): group independence and affiliation, publisher claims, evidence dates before freeze, and whether an item typed "independent" really measured something itself. These are reviewer obligations (§9), and Git history anchors the dates.
