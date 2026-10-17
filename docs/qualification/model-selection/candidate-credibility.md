# Candidate Admissibility and Credibility (MSR method v1, revision M1)

**Status:** Governing — slice S2c.2a (planning/protocol only), merged in PR #118 at `main@db2b25a24d0f850c3841a9eabcb915f7c92eebfb`; that merge is the acceptance event. It is a revision of **MSR method v1** (`README.md` §14), not a new method and not a new source of architectural truth.
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

- Layer 3 never feeds layer 1. A MAVI measurement is never external evidence, so a candidate cannot promote itself with its own bake-off result. A denylist narrows this risk **[checked]**; it refuses:
  - evidence produced by the reserved group `mavi` or any `mavi-…` group;
  - sources that are MAVI repository-relative paths, MAVI MSR event files or `evidence-store:` references;
  - evidence whose source, locator or independence basis names MAVI as a word;
  - a summary or caveat that puts MAVI next to MAVI's evaluation vocabulary (bake-off, selection or tuning partition, frozen test, gates). The bare word is not refused in a summary, because an author may be called Mavi;
  - claims on a MAVI dataset.

  A denylist cannot recognise every disguise, for example an internal evaluation posted under another group name. The reviewer therefore confirms that no item is MAVI-produced (§9). MAVI is matched as a whole word, so unrelated names such as "Mavic" or "MAVIS" are not refused.
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
| `reference-only` | origin known, but provenance confidence Low, architecture undocumented, or a claim untraceable | `DISCOVERED`, `REFERENCE_ONLY`, `NOT_SHORTLISTED` (technical), `DEFERRED`, and under M3 `BENCHMARK_BASELINE` (§4.4). **Never `SHORTLISTED`** |
| `excluded-discovery` | no identifiable original source, unknown publisher, no author group, or an integrity conflict (the bytes conflict with what the source publishes) | `DISCOVERED` or `NOT_SHORTLISTED` with reason class `credibility`; retained in the ledger |
| `mavi-owned` | a MAVI-owned deterministic baseline (for example PC-B0, VC-B0), identified by a MAVI commit | as MSR method v1. It may be shortlisted before its code exists, because the commit is bound at evaluation (§8) |

A **method candidate** (an architecture MAVI trains or fits) is classified on its backbone checkpoint identity, its published method and its code revision. The artefacts MAVI trains are declared in the decision summary with their training-manifest hash (§8).

A **checkpoint used for several sub-tasks** is one entry listing those sub-tasks (for example VTFPAR++ as PC-9/PO-8). An entry that uses the same bytes differently may share their weight hashes, but only with an **identical** identity block **[checked]**:
- a method entry with its own heads (MSR method §5.1, S2c plan §9.5a), for example PC-1 and PO-1 on one SigLIP 2 tower;
- such a method entry beside a zero-shot checkpoint entry, for example VC-2 and VC-R.

Two checkpoint entries for the same bytes are one candidate recorded twice, and are refused.

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
  - it admits only the pre-evaluation dispositions `DISCOVERED`, `SHORTLISTED`, `NOT_SHORTLISTED`, `REFERENCE_ONLY`, `DEFERRED` and, under M3, `BENCHMARK_BASELINE` (§4.4);
  - it refuses every unknown field **[checked]**.

  No ledger can claim that a candidate passed a MAVI bake-off;
- has **no licence field** **[checked]**. Licence wording is refused in every ledger text field too, except the reason and revisit trigger of an `evaluation-permission` disposition **[checked]**. Two exemptions exist, both whole-value only **[checked]**:
  - the plate domain term: a field whose **entire** value, after normalisation, is exactly "license plate", "license plates", "licence plate" or "licence plates". Normalisation is NFKC, case folding, combining marks and invisible format characters (zero-width spaces, soft hyphens, bidi marks) removed, Unicode dash forms folded to "-", whitespace runs folded to one space and the ends trimmed. No position, punctuation or neighbouring word is read as evidence that "license" is a noun: a value that merely contains the phrase ("License plate weights to anyone", "vehicle and license plate crops", "multi-line license plates", "the license plate detector", a quoted, bracketed or listed phrase) is scanned and refused. Benign prose is rewritten ("number plate", "plate");
  - a declared exact identifier: a value in a typed identifier field that the frozen ledger lists in `identifierExemptions` (§4.5).

  Everything else that contains "licen", after the normalisation and a fold of Cyrillic, Greek and Armenian look-alike letters to Latin, is refused. The licence axis lives in the MSR record §7 and the decision summary (§8);
- contains no weights, imagery or credentials. Sources are citations or URLs;
- uses no future date (today in UTC plus one day), and records no evidence before it was retrieved **[checked]**. Before freeze the dates themselves are attested by the recorder and checked in Git review (§9); after freeze, everything added must be dated on or after the freeze (§7) **[checked]**.

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
- **Re-typing a page does not help.** An independent item must be a distinct document, differing from **every other item in the entry**, whatever its type, in both:
  - its normalised source:
    - ignored: scheme, `www.`, fragment, case, trailing slashes and tracking parameters;
    - kept: an identifying query such as `forum?id=…`;
    - reduced to one id: arXiv abstract, PDF, HTML, version, export and Hugging Face paper links (new- and old-style ids), and OpenReview forum and PDF links;
  - its retrieved-document SHA-256.

  A repeating page re-typed as a "reproduction", or one page cited under two groups, is refused.

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

### 4.4 Benchmark-only baselines (M3, proposed)

Normative text: `proposals/m3-benchmark-only-baseline.md` and README §14.3; validators: `credibility.py` (ledger), `m3_universe.py` (component rankings and the derived composition set), `baseline_seal.py` (seal) and `m3_authority.py` (history, group authority, anchors, decision binding).

**New rules [checked]:**
- `BENCHMARK_BASELINE` is allowed only for computed class `reference-only`, only in a ledger with `methodRevision: msr-v1-m3`, and never for an S2c capability. It needs reason class `technical` and provenance High with every file pinned.
- The entry carries `benchmarkBaseline`:
  - `purpose` and `protocolSection`;
  - `configurationSha256` (invocation/configuration) and `adapterSha256` (adapter/preprocessing);
  - `hostManifests`, `{profileId: [{path, kind, sha256, size}]}`, covering every executable, runtime library and data file, each path declaring its `kind` (`executable`, `runtime-library` or `data`). Its profile keys must equal the decision's `targetProfiles` exactly (§8);
  - `evaluationPermissions`, bound per exact artefact: `[{artefactKind: executable | runtime-libraries | model-data, sha256s, decidedBy, decidedOn, primarySourceSha256}]`, one decision per kind. Each covers exactly the files of its kind: `executable` = every `executable` manifest file, `runtime-libraries` = every `runtime-library` file (required when there is one), `model-data` = the pinned identity files plus every `data` file. A data file therefore cannot be filed under the executable permission, and a single vague permission is refused;
  - `compositions`: exactly one gate-only baseline composition's frozen Stage-1 rule: `compositionId`, `partnerEventId` (the other member of the composition group), finite `eligiblePartners` (candidate id + exact identity hash, the canonical SHA-256 of the partner's ledger `identity` block), `excludedPartners` (every other shortlisted candidate of the partner event, with its identity hash and a recorded reason), `derivationRule` (enumerated: `highest-ranked-partner-passing-every-layer-a-gate`) and `gateScope` (only `all-ordinary-compositions`; `listed-compositions` stays disabled). The partner's ranking gates and ranking rule are the partner event's entry in the frozen `compositionUniverse`. A benchmark-only component exists only to define this gate, so zero compositions are refused, and so is more than one.
- **Manifest hygiene [checked]:** one SHA-256 has one kind across every profile; every pinned identity file is listed as `data` in every profile; every profile holds at least one `executable`.
- **Composition group [checked]:** every `msr-v1-m3` ledger carries `compositionUniverse` (refused in M1 and M2 ledgers): exactly two component events (its own included), each with `subTask`, `rankingLayer` (`A` or `B`), `k`, sorted `rankingGateIds` and `rankingRule` `{rule: lexicographic-v1, keys: [{metric, direction}]}`; sorted `compositionGateIds` including `baseline`; `mpid`; `includePackageableBaselines: true`. Both events carry the identical block, and the group holds exactly one benchmark-only component. `supersedes` (§7, README §14.3) is allowed only on such an event.
- **R1, BOB payload bytes (owner decision O7) [checked]:** no shortlisted ordinary candidate of either group event may pin a file whose hash is a benchmark-only executable, model, data or identity file, whatever kind or path the ordinary candidate gives it. Runtime-library dependency hashes may be shared.
- Every eligible or excluded partner must be a shortlisted candidate of the partner ledger (this ledger for a same-event universe, the partner event's frozen ledger otherwise) with that identity, and together they must be exactly its shortlist: an eligible universe smaller than the shortlist needs a recorded reason for each exclusion, and no other candidate can be injected. No eligible partner may hold a benchmark-only payload file (R1); the partner event must exist with the identical `compositionUniverse`, which the seal verification and the repository check prove (§8).
- After freeze, the set of benchmark-only baselines, and every field of each, is fixed (§7).

**Prohibited roles [checked, §8].** A benchmark-only component, and any gate-only composition containing it, is never: shortlisted; a candidate; a top-K entry; a component finalist; an ordinary composition candidate or a component of one; ranked (as a candidate or a composition); on a frontier or non-dominated set; the technical winner; the strongest evaluated technical candidate or composition, highest task-quality, strongest reported or strongest cleared candidate; the incumbent; the implementation candidate or one of its components; the subject of `BASELINE_SELECTED`.

**Restated, not new:**
- MAVI measurements never enter the ledger and never change a class (I4), so a benchmark-only component gets no credibility promotion from MAVI measurements.
- A `reference-only` candidate is never `SHORTLISTED`.

### 4.5 Exact identifier exemptions (M3 final round, new)

Some identifiers carry the letters "licen" and cannot be reworded, for example an upstream repository named
`<model>-license-plate-detection`. The ledger may declare them **[checked]**:

```json
"identifierExemptions": [{"candidateId": "<candidate id>",
                          "fieldKind": "repository-url | source-url | artefact-filename | model-identifier",
                          "value": "<the exact complete raw value>", "reason": "<short recorded reason>"}]
```

- Field kinds are a closed set, each mapped to exact field paths of that candidate: `repository-url` →
  `identity.repository`, `identity.derivation.fromRepository`, `methodCode.repository`; `source-url` →
  `evidence[].source`; `artefact-filename` → `identity.files[].path`; `model-identifier` → `candidateName`.
- Only that exact raw value, in a field of the declared kind of the declared candidate, skips the licence scan.
  Matching is whole-value equality: no wildcard, regex, substring, URL-prefix, domain, suffix or basename matching.
  The value must exist there, contain no whitespace (an identifier, never prose) and carry a non-blank reason; an
  unknown candidate, a wrong kind, a duplicate or an extra key is refused.
- The same literal anywhere else (summaries, caveats, locators, reasons, evidence prose, another field) is scanned
  and refused as usual.
- Declarations are part of the ledger frozen at `PROTOCOL_FROZEN`; any change after freeze is refused
  (`identifier_exemptions_changed_after_freeze`), so nothing can be exempted after scoring begins.
- The concrete identifiers of an event are authored with that event's ledger, never in validator code.
- Owner decision: `model-identifier` applies only to `candidateName`, and only through such an exact, frozen,
  reasoned declaration; repository URLs and artefact paths are separate kinds and never exempt a name, nor a name them.

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
- the classification-inputs hash (`inputsSha256`: the canonical SHA-256 of the kind, sub-tasks, identity, authors, publication, architecture and claims);
- the pinned weight hashes (`checkpointSha256s`, empty until pinned).

**[checked]**:
- entries are chronological and chain: `from` equals the previous `to`;
- cited evidence exists and was recorded no later than the entry;
- an entry made on the current classification inputs is recomputed. It may not claim a higher class than the evidence active on its date supports, so a promotion cannot be backdated ahead of its evidence. An entry reaching `established` must be supported by the evidence **it cites**;
- an entry made on earlier inputs (a later correction changed, say, the publication or the architecture) cannot be recomputed, because its inputs are gone. It is not re-judged, so a correction never invalidates the history. Such entries may only precede the entries on the current inputs. They are fixed by the freeze, and they can never make a candidate implementable (§8);
- an `emerging` or `established` entry has pinned bytes;
- the last entry equals the computed current class, the current identity hash and the current inputs hash. New evidence that changes the class, or any edit to the classification inputs, fails until a history entry records it;
- once `checkpointSha256s` is non-empty it never changes, and it equals the current weight hashes.

**Freezing makes the ledger append-only.** At `PROTOCOL_FROZEN`:
- the ledger is copied to `<event-id>-evidence-ledger-frozen.json` with `frozenOn` set to the freeze date. `frozenOn` is no earlier than any date the copy records **[checked]**;
- the frozen protocol records the copy's canonical SHA-256 and its `frozenOn` date;
- the event record `<event-id>.md` records the protocol's LF-normalised SHA-256.

The repository check refuses a protocol without a frozen ledger, a frozen ledger the protocol does not cite, and a protocol whose hash the record does not carry **[checked]**. From then on, the working ledger must be an append-only evolution of the frozen copy **[checked]**:
- every frozen candidate, evidence item, claim, history entry, caveat and popularity signal is kept unchanged. An evidence item may only gain `retracted`;
- every evidence item, retraction, history entry, popularity signal and new candidate added is dated on or after `frozenOn`, so nothing added after the freeze can be backdated before it;
- the shortlist is fixed. For every shortlisted candidate, everything except its append-only evidence, history, caveats and popularity signals and its recomputed classification is fixed as well, including its claims.
- **M3 (new):** the set of benchmark-only baselines is fixed, and so is every field of each (identity, manifests, configuration, adapter, permissions, disposition, Stage-1 rule) except its append-only lists and recomputed classification; so are `compositionUniverse` and `supersedes`. The component rankings, the seal and the D manifests are separate committed, canonical files (§8, README §14.3).
- **M3, the history requirement and the Git boundary (stated once here).** Repository verification (`validate_repository`, so `verify_repo` and every CI job running it) always needs full Git history: a shallow clone, a graft file or a directory outside Git is refused (`model_selection_history_unavailable`), and replace objects are ignored. Every M3 Git call runs under ONE isolated profile (`m3_git.git_environment`/`_run`): system and global configuration disabled, every inherited `GIT_*` variable dropped except tracing, and fixed options `core.longpaths=true`, no fsmonitor or untracked cache, no colour, signatures, path quoting or relative diffs. Work-tree cleanliness fails closed: any stderr output (for example a Windows path beyond MAX_PATH that Git could not stat) is a refusal even with exit 0, and skip-worktree or assume-unchanged index flags are refused (`worktree_index_flags_hide_changes`); only the user's `core.autocrlf`/`core.eol` are carried into status, so a normal Windows checkout is not misread. One reachable-history walk (`git log --full-history --sparse --diff-merges=separate --root --raw --no-renames` over the whole model-selection directory: no simplification, merges diffed against each parent) builds the **sticky audit domain**: every event with any reachable M3 artefact add, any reachable M3 frozen-ledger version (`msr-v1-m3`, a benchmark-only baseline or a `compositionUniverse`), any reachable record version with an M3 structured line, or membership in (or supersession by) any historical universe. Artefact names are parsed by their complete suffix after a full event id, never by an infix. For every domain event **[checked]**, every committed file of the event is classified by ONE registry (`m3_authority.EVENT_FILE_CLASSES`) and is add-only by default: HEAD holds its frozen ledger, protocol and record (`m3_event_erased`); IMMUTABLE files (frozen ledger, protocol, component rankings, seal, D manifests) keep exactly one blob and are never modified, retyped or deleted on any parent edge nor in the work tree (`m3_frozen_file_rewritten`, `baseline_artefact_rewritten_in_history`, `baseline_artefact_deleted_in_history`); VERSIONED files (record, addenda, decision summary, decided ledger) may gain later versions but are never deleted (`m3_versioned_file_deleted`); every structured record line (`Protocol | Component ranking <id> | Baseline seal <id> | Decision | Decision snapshot | Snapshot SHA-256: …`, `Superseded by <id>`, `Abandoned: …`) of every historical record version is still in the record (`m3_record_line_removed`); every historical version of a decision carries the same `compositionAuthority` block, except `implementationComposition` taking one value once (`composition_authority_rewritten`), whether or not a decision file exists now; the working ledger is the one mutable file (its append-only evolution is `validate_evolution`); and any other name in the event's namespace is refused (`m3_unclassified_event_file`). Renames are a delete plus an add, so they are refused like deletion; re-creation, merges and merged side branches are edges of the same walk. An event therefore stays auditable after every current declaration and file has gone. First adds are taken by ancestry, never by lexical order. Historical content is read by blob id; every Git failure is a typed refusal carrying its return code and stderr (`git_command_failed`, `git_object_missing`), never a verdict. The CI jobs that run it (`repo contracts`, the qualification shards and Task 17) check out full history.
- **M3, STOPPED and revision.** A STOPPED group is terminal; a revision freezes new events that `supersede` the stopped ones (README §14.3 is the single normative statement).

A changed shortlist needs a numbered protocol revision, which voids the results it could bias (MSR method §3.1), freezes a new copy and records the new protocol hash in the record. Before freezing, ledger edits are ordinary reviewed Git changes. A commit that rewrites the frozen copy, the protocol and the record together can be seen only in Git review. The reviewer treats any change to those files as a protocol revision (§9). `python tools/qualification/model_selection_check.py evolution <old> <new>` checks two versions on request.

**Promoting an important new entrant.** A `reference-only` or `emerging` candidate is promoted only when new evidence meets §3.2, and a history entry records it.
- Before `PROTOCOL_FROZEN`, it may then be shortlisted in that event.
- After `PROTOCOL_FROZEN`, it enters only through a numbered protocol revision, or through a new event (MSR method §12).
- A candidate that appears after the event closes is carried into the next event's discovery with its last class (MSR method §12 step 3).

Demotion follows the same rule, for example after a retraction or an integrity conflict. Evidence is never deleted: a retracted item keeps its record with `retracted: {at, reason}`, and an integrity conflict carries its date.

## 8. Implementation eligibility and the decision summary

MSR method §4 is extended. The implementation candidate, and each component of an implementation composition, must be **[checked]**:
- evaluated in the bake-off and past every technical gate;
- `CLEARED` for **each** named target profile;
- **`established`** (or `mavi-owned`) now, **and** in the history entry in force on the decision date. That entry must have been made on the current classification inputs, so that it was recomputed (§7). An `emerging` winner stays recorded at its rank (§6), and it needs a recorded promotion before it can be implemented;
- bound to the exact evaluated bytes, the ledger hash, the frozen-ledger hash and the protocol hash of **one** event.

For non-S2c events these rules are checked in the **decision summary** (`mavi-model-selection-decision-v1`, `<event-id>-decision.json`). It is written at `TECHNICAL_DECISION_RECORDED` or later (S2c.4 onward), never in S2c.2a. It comes with a **decision snapshot**: the ledger as it stood on the decision date, `<event-id>-evidence-ledger-decided.json`. **[checked]**:
- the decision cites the snapshot and the frozen ledger by canonical SHA-256. Nothing in the snapshot postdates the decision, and implementation eligibility is judged on the snapshot;
- after the decision the working ledger must grow append-only from the snapshot, with nothing added dated before the decision date. A promotion made later cannot be backdated in the working ledger to support the decision;
- the event record `<event-id>.md` carries the LF-normalised SHA-256 of the decision summary and of the snapshot. A snapshot without a decision is refused. Rewriting the snapshot, the decision and the record together remains a Git-review item (§9);
- the repository check requires `protocolSha256` to equal the LF-normalised SHA-256 of `<event-id>-protocol.md`, which the event record also carries;
- the evaluated set equals the **frozen** shortlist plus the frozen benchmark-only baselines (M3), and the working ledger's shortlist has not changed since. A strong candidate with an inconvenient licence cannot be dropped, before or after freezing;
- **M3, benchmark-only baseline rows** (new rules):
  - `technicalGates: "n/a"`, `comparativeScore: null`, `taskQualityScore: null`;
  - `hostManifestSha256s` equal to the ledger manifests' canonical hashes, whose profiles equal `targetProfiles` exactly, and the evaluated bytes equal the pinned identity;
  - `baselineSealSha256s`: the hash of the group's committed seal;
  - no licence status, because they are never implemented;
  - never named by `strongestReported`, `highestTaskQualityEvaluated`, `strongestEvaluatedTechnical`, `strongestClearedPerProfile` or `implementation.components`;
- **M3, the committed group artefacts** (README §14.3 gives the flow): each component ranking covers exactly the frozen shortlist with frozen identities, ranking gates and metrics, and its rank keys are derived; the RESOLVED seal equals, field for field, what the frozen rule re-derives from the frozen ledger, the protocol hash, the partner event's frozen ledger and both rankings, including the hash of the derived composition set U; a STOPPED seal records an enumerated reason and evidence hashes, names no partner, may not claim a supplied (committed) input absent, and with every input supplied carries exactly the derived reason; each ranking and the seal are cited by exactly one structured record line equal to the file's hash; the chronology freeze ≺ ranking ≺ seal holds strictly by ancestry; every D manifest carries the group id, U hash, seal hash with its first-add commit S0 and an `anchorCommit` re-verified as README §14.3 step 6 states;
- **M3, the mandatory decision block `compositionAuthority`** (new rules; identical in both group events): `groupId`, `anchorCommit` (the anchor of a committed D manifest, re-verified like a D manifest's), `baselineSeals` (the one RESOLVED seal by hash, status and S0), `dExecutionStartedAt` (strictly after the seal's `recordedAt`, no later than `decidedOn`), `incumbent` (null or a composition of U), `baseline` (the gate-only composition's id, seal composition hash, D-score and D result hash; a null D-score refuses the decision, `baseline_d_unavailable`), `topK` and `componentFinalists` (equal to the derivation), `compositionCandidates` (equal to U, each with its exact components, gates over exactly `compositionGateIds`, D-score, recomputed `baseline` gate, technical gates and comparative score, D result hash and seal hash), `rankedCompositions` (the passing compositions in non-increasing D-score order), `strongestEvaluatedComposition`, `frontier` (ranked compositions only) and `implementationComposition` (a ranked composition, required exactly when an implementation is named). Each ordinary row's `technicalGates` and `comparativeScore` must equal the composition-derived values (passed with the best D-score of the passing compositions containing it, else failed and null), and the implementation is exactly this event's component of `implementationComposition`. The block is never rewritten in any later version of the decision file (checked over every historical version, §7), apart from `implementationComposition` moving once from null to its value; a committed decision is never deleted. No decision exists while the seal is missing or STOPPED, or after the group was abandoned (README §14.3);
- **M3, outcome** (rule 5): the outcome is checked by the unchanged M1 rules on the composition-derived rows, with every benchmark-only row and the gate-only composition removed from every domain. The benchmark-only baseline influences it only through the frozen `baseline` hard gate (plan §4.5); M3 adds no outcome rule;
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
- **MAVI-produced evidence.** No evidence item reports a MAVI measurement under another name. The validator's denylist (§2) catches only the obvious forms.
- **Free text.** Licence reasoning appears only under an `evaluation-permission` reason. The validator refuses the letters "licen" everywhere else, except the exact whole-value plate term and declared exact identifiers (§4), but not a paraphrase ("may be redistributed under the terms of ..."). Homoglyphs are folded only for a small table of Cyrillic, Greek and Armenian letters; other confusables (other scripts, mathematical alphanumerics not covered by NFKC, look-alike digits) remain a reviewer obligation. The reviewer also confirms that each `identifierExemptions` entry names a genuine identifier (a repository or source URL, a model identifier or an artefact file name), not prose.
- **MAVI-trained artefacts.** Each training-manifest hash in the decision summary resolves to a retained MAVI training manifest in the S2c.3 evaluation harness's evidence store. The validator checks its form, not its content.
- **Frozen files.** Any change to a frozen ledger, a protocol, a decision snapshot, a decision summary or their hashes in the record is reviewed as a protocol revision or a decision revision. The decision file changes as the event state advances, so the reviewer compares each version's snapshot hash with the previous one.
- **Discovery coverage.** Discovery covered the survey's sources plus a dated re-survey, and no candidate was left out because it was inconvenient. An unlisted strong candidate is a review finding.
- **Freeze record.** The frozen protocol records the frozen ledger's SHA-256 (template `selection-protocol.md` §2).
- **Benchmark-only baselines (M3).** The exclusions, the derived composition set, the seal, the hard-gate recomputation, the chronology and the anchors are machine-checked (§7, §8, README §14.3). The reviewer confirms what remains:
  - the component-ranking metrics and gate results, and each composition's D-score and non-baseline gate results, are what the harness measured (they are bound by `measurementSha256` and `dResultSha256` to create-only harness outputs outside Git; recomputing them from raw outputs stays a review item);
  - no protected D data was read before `open_protected_d` returned (Git proves the publication order of the seal, the anchor and the D manifests, not when D data was read), and every protected D run committed its D manifest;
  - the host manifests cover every executable and runtime library actually loaded, and the benchmark-only component's own manifest classifies its files correctly (a file it mislabels as a runtime library could be shared by an ordinary candidate, owner decision O7);
  - the harness does not use the test seam `canonical_for_tests` (the only way to substitute a local repository for the canonical one).

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
| I1 | No shortlist without known provenance: `SHORTLISTED` needs `established`/`emerging` (with basis and second reviewer), provenance High/Medium and pinned bytes. A `mavi-owned` baseline is bound to its commit at evaluation. A benchmark-only baseline (M3) is never shortlisted; it is measured under its pinned identity, host manifests and permissions | validator |
| I2 | First-party repetition cannot masquerade as independent evidence | validator (§4.2) |
| I3 | The credibility class is computed from recorded evidence, never asserted | validator |
| I4 | Credibility cannot alter measured MAVI technical results, and MAVI results cannot alter credibility | no MAVI result or MAVI-produced evidence in the ledger; the ranking reads recorded scores only |
| I5 | Licence cannot rewrite the technical ranking, and discovery is licence-blind | no licence field or licence reason in the ledger; derived outputs ignore licence except "strongest cleared" |
| I6 | A technically strongest but deployment-ineligible candidate remains recorded | evaluated set equals the frozen shortlist plus frozen benchmark-only baselines; strongest technical derived without licence or credibility |
| I7 | The implementation candidate traces to one MSR event and exact artefacts | decision summary: event id, ledger and frozen-ledger hashes; repository check: protocol hash, recorded in the event record; evaluated bytes equal the ledger bytes plus declared MAVI-trained artefacts. A coordinated rewrite of the frozen files is a Git-review item (§9) |
| I8 | Class changes leave an auditable reason; promotions cannot outrun their evidence; after freeze, frozen content is never rewritten and nothing added is backdated | history rules (inputs hash, recomputation) and the frozen-ledger evolution check (§7) |
| I9 | An `emerging` candidate cannot become the implementation candidate without a recorded promotion | implementation eligibility on the decision date (§8) |
| I10 | A name cannot keep its entry while its bytes change | identity hash and pinned-hash history; no weight bytes shared except an identical method backbone |
| I11 | Person and vehicle evidence cannot be conflated | fixed event scopes; claim and technical-evidence sub-task and object-class checks |
| I12 | No S2c.2a artefact claims a MAVI bake-off result | pre-evaluation dispositions only; strict fields; no MAVI evidence; no ledger or decision summary exists in S2c.2a |
| I13 (M3) | A benchmark-only baseline is never a candidate, ranked set member, derived output or credibility input; it affects the outcome only through the frozen `baseline` hard gate on end-to-end compositions | validator: unscored rows, exclusion from every domain, mandatory decision block, derived-output refusal; composition-derived rows with the ordinary M1 outcome rules; I4 |
| I14 (M3) | The gate-only baseline composition comes only from its frozen finite universe under its frozen rule; the ordinary composition set is derived from frozen inputs, never listed by the author; implementation authority comes only from passing end-to-end compositions | validator: frozen universe and Stage-1 rule, partner-universe reconciliation, derived rank keys, top-K and U, sealed U hash, decision set equal to U, recomputed gates and composition-derived rows |
| I15 (M3) | The baseline and U are fixed and published before protected D opens and can never change afterwards; no M3 event, artefact or recorded decision can be erased or rewritten | sticky reachable-history audit with full history always required; one event-file registry, add-only by default (decisions versioned, never deleted, block unchanged across every version) and append-only record lines (§7); strict chronology freeze ≺ ranking ≺ seal; `open_protected_d` (same predicate as repository verification, verified active ruleset, canonical anchor checked outside the repository's configuration); recorded anchors re-verified; terminal STOPPED with revision only by superseding events; no abandonment after a decision |

## 12. Loopholes considered

| Attack | Outcome |
|---|---|
| Promote an unknown model with five websites copying one README figure | five `repetition` items collapse to one first-party origin; 0 independent groups, so at most `emerging` |
| Re-type those pages as `independent-reproduction`, or add `#table-2` / `http` variants of the README URL | refused: an independent item must be a distinct document by normalised source and retrieved bytes |
| Have an affiliated spin-off act as the "independent" group | refused: affiliated groups are declared and can never be `independent`. Undeclared affiliation is a review item |
| Record MAVI's own bake-off win as an independent reproduction | the obvious forms are refused (reserved `mavi` groups, MAVI paths and event files, MAVI named in the item's text, MAVI datasets); a disguised internal result is a review item (§9) |
| Drop the strongest technical candidate because its licence is inconvenient | the frozen shortlist forces it into the evaluated set; strongest technical is recomputed without licence |
| Edit the shortlist after freeze, then cite the new ledger | refused: the decision checks the frozen ledger, and the working ledger must evolve append-only with a fixed shortlist |
| Present licence clearance as technical superiority | "strongest cleared" is a separate derived field; MSR method §9's standard sentence applies only when the two coincide |
| Shortlist a model with unknown checkpoint provenance | Low confidence makes it `reference-only`, and `SHORTLISTED` is refused |
| Shortlist an `emerging` model quietly | refused without a recorded basis and a second reviewer |
| Implement an `emerging` model, or one that was `emerging` on the decision date | refused: implementation requires `established` in the history entry in force on the decision date |
| Backdate a promotion or cite evidence after its date | refused: no entry on current inputs may overclaim on its date; cited evidence must predate it and support it; no future dates; nothing recorded before it was retrieved; after freeze, nothing added may be dated before `frozenOn` |
| Correct a publication after freeze to make an old promotion look invalid, or edit inputs so that an unverifiable old entry carries the decision | a correction needs a new history entry and never invalidates old entries; implementation needs the in-force entry to be on the current inputs; shortlisted entries' inputs are fixed after freeze |
| Commit a protocol but no frozen ledger, leaving the ledger editable | refused: a protocol requires the frozen ledger it cites and a record carrying its hash |
| After the decision, add independent evidence and a promotion dated between the freeze and the decision | refused in the working ledger: the decision is judged on its snapshot, whose hash the record carries, and the working ledger may only grow from it with nothing dated before the decision. A coordinated rewrite of the snapshot, the decision and the record is a Git-review item (§9) |
| Set `frozenOn` earlier than the frozen contents, to open a window for backdated evidence | refused: a sealing date is no earlier than anything the sealed copy records |
| Keep the name, swap the checkpoint | refused by the identity hash and the pinned-hash history; after freeze, a shortlisted identity is fixed |
| Smuggle a community fine-tune in as part of a method's artefacts | refused: evaluated bytes are the backbone plus declared MAVI-trained artefacts with training manifests |
| Use person evidence for a vehicle candidate, or widen a ledger's sub-tasks | refused: fixed event scopes; sub-task and object class on claims and technical evidence |
| Park an evidence-supported `established` candidate as reference-only for "credibility" | refused: a credibility reason must match the computed class |
| Hide a demotion by deleting evidence | before freeze a Git-reviewed deletion; after freeze refused (append-only); the last history entry must match the recomputed class |
| Count stars or downloads, or one group posting three reproductions | popularity signals are never read; producer groups count once |
| (M3) Reseal the gate-only baseline to another partner after D and recompute the seal's hash | refused: the seal must equal the re-derivation from the committed rankings; the seal file is add-only; the decision block, the benchmark-only row, every composition's D result and every D manifest still carry the earlier hash and S0 |
| (M3) List only the convenient compositions, none at all, or rename one after results | refused: the decision's composition set must equal the derived, sealed U with derived ids |
| (M3) Keep a component whose every composition failed the baseline gate as top-K, finalist, frontier, winner or implementation | refused: rows, finalists and the frontier are composition-derived, and the implementation must be the component of a passing ranked composition |
| (M3) Erase or rewrite a STOPPED or decided M3 event (protocol revision in place, BOB dropped, artefacts or the decision and decided ledger deleted, renamed or re-created, then abandon the group), directly, in a merge resolution or on a merged side branch | refused: the audit domain is sticky and comes from the reachable-history walk; every event file is add-only by default (decisions versioned, never deleted); record lines are append-only; abandonment after any committed decision is refused |
| (M3) Point `url.*.insteadOf` (repository, global or environment configuration) at a fake canonical repository holding an unpublished seal | refused: the canonical anchor is queried and fetched outside the repository's configuration under the isolated profile, and the fetched tip must equal the advertised one |
| (M3) Hide a work-tree edit behind skip-worktree/assume-unchanged, or in a Windows path beyond MAX_PATH | refused: cleanliness checks run with `core.longpaths=true`, refuse any stderr output and refuse hiding index flags |
| (M3) Run the anchor's temporary directory inside another repository whose configuration rewrites the canonical URL (`url.*.insteadOf`) | refused as a redirection: both remote operations run inside the fresh bare repository the check creates, and repository-less Git runs with ceiling directories, so no enclosing configuration is read (IP-5) |
| (M3) Hide an edit of an M3 file behind a clean filter, `ident` or `working-tree-encoding` attribute, an ignore rule, or a same-size edit that keeps the modification time (Git's stat cache) | refused: those attributes refuse before status runs and ignored files count as dirty; Git's status can still miss a same-size, mtime-preserving edit, so every committed file of an M3 event (frozen ledger, protocol, record, addenda, working ledger, decision, decided ledger, rankings, seals, D manifests) is compared by content with its HEAD blob in repository verification and therefore before protected D (canonical JSON by blob id, LF-only by construction; every other class LF-normalised): an uncommitted edit, visible or not, is refused (IP-5) |
| (M3) Redirect `gh` (`GH_HOST`, `GH_REPO`, `GH_CONFIG_DIR`, an `http_unix_socket`, custom TLS roots) or answer the ruleset check from a renamed or forked repository, or weaken the ruleset (no required `quality` check, another integration, strict policy off, squash or rebase allowed) | refused: `gh api --hostname github.com` under a scrubbed environment, a socket configuration refuses, the repository identity is verified, and the ruleset predicate requires `quality`@15368 strict and merge-only (IP-5) |
| (M3) Seal after seeing D results on a local branch, or rewrite history (orphan) and reseal | refused: D opens only once the seal is on the protected canonical default branch (live anchor), recorded anchors must be in HEAD and in `origin/main`, and the ruleset forbids deleting or force-pushing `main` |
| (M3) Replace a cited seal in place (STOPPED to RESOLVED, or PD-A to PD-B) before any decision, rewriting the rankings and appending the new hash to the record | refused: one structured citation per artefact, equal to the file; artefacts are add-only and record lines append-only (full history is always required, §7) |
| (M3) Commit a fabricated STOPPED seal ("partner event missing") although the partner ledger and resolvable rankings are committed | refused: a stop cannot record a committed input as absent, and its reason must be the derived one |
| (M3) Re-list the benchmark-only weights or executable in either group event under another identity or kind | refused: no shortlisted ordinary candidate may pin a BOB executable, model, data or identity file (R1) |
| (M3) Inject a non-partner or unshortlisted detector as the baseline partner or as a composition component | refused: the partner universe and every component reconcile with the partner event's frozen shortlist by identity hash |
| (M3) Leave the benchmark-only baseline out of the decision's ranked sets so its exclusion goes unchecked | refused: the M3 decision block is mandatory and every ranked set is checked |
| (M3) Use a benchmark-only baseline to steer the outcome | the outcome is the ordinary M1 outcome with every benchmark-only entity removed; tests prove invariance |
| (M3) Hide licensing wording next to the plate term ("sub-license plates", "License plate weights to anyone", "build & license plate models"), behind zero-width characters or full-width letters, or inside a URL | refused: only a whole value equal to the plate term, or a declared, frozen exact identifier in its typed field, is exempt (§4, §4.5) |

Residual human trust (P3): these are reviewer obligations (§9), not machine checks.
- group independence and affiliation, including undeclared sibling groups;
- publisher claims;
- evidence dates before freeze;
- whether an item typed "independent" really measured something itself;
- relabelled sub-tasks on independent evidence;
- disguised MAVI results;
- paraphrased licence reasoning (without the letters "licen"), and confusable spellings of "licence" outside the folded table;
- (M3) the measured metrics, D-scores and non-baseline gate results behind the hash bindings; that no D data was read before `open_protected_d`; and the benchmark-only component's own manifest kinds (§9);
- (M3, R3, closed by D3/D4) a force-pushed or orphan history rewrite: D opens only on the canonical protected default branch, verified outside the repository's configuration, and recorded anchors are re-verified. The `mavi` ruleset (active for `~DEFAULT_BRANCH`, `deletion` and `non_fast_forward`, no bypass actors) is the owner's control; `open_protected_d` re-verifies it through the GitHub API before every D and refuses when it cannot;
- (M3, accepted residual R4) licence wording obfuscated by spacing inside the word or paraphrased without the letters "licen";
- (M3, R1, closed except runtime libraries, owner decision O7) an ordinary candidate pinning a benchmark-only executable, model, data or identity file is refused whatever its kind; runtime-library dependencies may be shared by design, and a file the benchmark-only component's own manifest mislabels as a runtime library remains a reviewer item;
- training-manifest resolution;
- the checkpoint/method kind;
- a fabricated history prefix on superseded inputs before freeze (it can never support implementation);
- URL variants the normaliser does not collapse (for example a repository root and its README);
- coordinated rewrites of the frozen files, or of the snapshot, the decision and the record, in one commit.


## 13. M2 S2c implementation boundary

S2c uses README §14.1 and `s2c-operational-selection.md`. M1 evidence/classification, sealing, dated promotion and append-only snapshot evolution remain unchanged. Credibility never changes E, F, J, T or T_r, including when the strongest technical unit is emerging. At QUALIFICATION_PENDING, each component of each unit is independently checked on the event's dated snapshot. K_c contains M1-implementable units from J_c cleared for every required profile, or the admissible frozen fallback if K_c would be empty. T_impl is recomputed on K_person×K_vehicle; it is not a filter/intersection of T or per-profile winners.

At TECHNICAL_DECISION_RECORDED the decision snapshot, profile outputs and implementation pair are absent/null. Later implementation versions can resolve pending determinations without reopening technical selection: each extends the immediate retained predecessor and copies its technical stage byte-identically. Dates cannot regress and snapshots cannot backdate later promotions. The M2 validator checks every retained paired decision, not only its active projection. Non-S2c v1 behaviour remains supported.
