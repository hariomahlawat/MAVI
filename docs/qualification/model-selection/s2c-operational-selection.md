# S2c.2b-2 Operational selection protocol

## Authority and execution

This implements the PR #121 design from `main@8b6614721ff3d0fe7a77cde66ce6051defcceb74`. b-1 owns S/U/I/A, Track calibration, partition authority, support, owner quality gates, margins and paired cluster-aware outcomes. b-2 consumes those outcomes; it does not fit another quality ranking. Both machine contracts are checked together. Frozen-test inputs are forbidden in quality selection evidence.

Freeze exact candidates/configurations/compositions, required scope, fallback, Q and simultaneous family, MPID-unavailable disposition, host/workload/topology, operational constraints and deployment profiles before selection. Gate ids must include absolute-quality, support and engineering summaries; their underlying b-1 owner tables and measured engineering evidence are retained in the protocol/harness evidence. Optional gates are also frozen, never removed at result time.

E excludes label-free engineering failures, absolute/component gate failures and MPID failures. F is protected directly against every other member of the complete original E, across all Q claims. No transitivity, peeling or comparator deletion is allowed. J is F when nonempty; otherwise it is the valid gate-passing frozen fallback, including a declared disabled identity. F and its quality-outcome reason remain unchanged by fallback use.

Evaluate exact J_person×J_vehicle pairs. Operational evidence binds each pair's unit/configuration/component identities and the frozen host topology. H_lo/H_up are recomputed from the same bounded whole-job replay with frozen demand/error scenarios. H* is the minimum admitted H_up; T contains every admitted pair whose H_lo is at most H*. Lexical ids order display only. Missing evidence, infeasibility, tied sets and a unique winner are distinct outcomes.

From QUALIFICATION_PENDING, licence status and M1 component credibility produce K per capability, with that capability's admissible frozen fallback if needed. C_impl=K_person×K_vehicle; recompute T_impl there. C_r/T_r/C_all are credibility-blind reports over J, not F. Licence/credibility never rewrite technical T or hide an emerging winner. The owner may name only an exact T_impl pair; the two event decisions must agree. Before this state, profile/implementation outputs and implementationPair are null. NO_QUALIFIABLE_CANDIDATE is final at CLOSED only, after required licence determinations resolve.

## Lifecycle, projection and E2 evidence

The replay follows the existing S2b domain/claim/completion services and serial AttributeRunner lane. FIFO uses queuedAtUtc then id; retries retain queue position, claim consumes an attempt, first-claim deadlines cap leases, and no claim/reclaim occurs at or after deadline. Lost inference is reexecuted without checkpoints. A cancelled inference lane drains before its next claim. Phase A protects publication up to the frozen cap; Phase C uses the real ownership fence. Bounded publication is an operational gate, not an invented domain clock fence.

`completedAtUtc` models the timestamp sampled inside the Phase-C publication transaction. `publicationCommittedAtUtc` is its commit and `completionAcknowledgedAtUtc` the client acknowledgement. Production samples CompletedAtUtc before the insert/barrier/commit; these instants must not be equated. All absolute instants use `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC values and ...Utc names. Fixed replay event ordering makes coincident instants auditable.

The six workload roles are typical, small-burst, 10k-boundary, mixed, recovery and 500-camera. Boundary/mixed/burst/loss structure is checked; representativeness is reviewed. The 500-camera role binds the target explicitly. The fluid screen establishes only a necessary service-demand capacity bound; all queue/deadline/recovery admission comes from bounded replay. Reserve hosts are counted as installed but withheld from normal active capacity. This is a projection on declared loads/hardware, not “500 cameras qualified”.

E1 is isolated engineering measurement. `operational_measurement.measure_attempts` observes the actual AttributeRunner through its existing inferencer seam; real E2 requires AttributeApiClient and the platform path. It preserves evidence reads, aggregation, upload, heartbeat, completion retries and the serial lane. Calls retain integer client durations and UTC boundaries without scores/crops/tokens. A retained matching real-platform trace is required for complete operational evidence; client timings alone do not establish server transaction times or resource demand. The qualification run supplies and retains those separate measurements and frozen service envelopes. Synthetic clients are test-only. E3 is later integrated held-out engineering validation; contradiction reopens incomplete evidence or triggers a fresh numbered calibration revision, never selection-time rescue.

## Canonical bytes and retained versions

Machine artefacts use JSON objects/lists/strings/null/bools and integers only. Fractions/error factors are represented by declared integer microseconds/parts-per-million, not floats; 1.0, NaN and infinities are refused. Integers never coerce bools. Objects sort keys by Python Unicode code-point ordering; strings use JSON ASCII escapes (valid UTF-8), preserving Unicode without normalization. Compact separators and exactly one trailing LF are mandatory. Duplicate keys, BOM, CRLF, unknown/missing fields, lone surrogates and other noncanonical bytes are refused. SHA-256 covers those exact bytes. Set-like unit/claim/pair arrays have checked lexical order; evidence event arrays preserve their meaningful order.

Frozen inputs, raw evidence and immutable quality results are content addressed under s2c-evidence/<sha>.json. Each quality result also has an immutable event address `<capability>/<event>-quality-result.json`; corrections retain the original and create `<event>-quality-result-v<N>.json` from N=2. Joint files are `<eventPairId>-joint-<technical|implementation>-v<N>.json` under s2c-joint/. N starts at 1 and increases without gaps. The joint index is rederived from all retained files; active is last, every predecessor resolves exactly once and must be the immediately preceding file/hash. No retained file is overwritten or deleted by the writers.

The first implementation version extends the preceding technical version. Clarification I1 permits later implementation-only revisions to resolve pending licence/snapshot determinations by extending the preceding implementation version, keeping all frozen inputs and technicalStage byte-identical, dates monotone and snapshots append-only. A numbered technical revision requires new frozen evaluation/calibration inputs. Every retained event decision-v<N>.json keeps its own joint hash; active event decision.json is a checked projection. Earlier person/vehicle decision versions remain paired and validated.

Hash dependencies are frozen inputs → per-event quality result → joint version → event decision-v2. Joint documents reject full event-decision hash fields. Shape schemas under tools/qualification/model_selection/schemas supplement, but never replace, canonical parsing/recomputation. Check with `python tools/qualification/s2c_operational_check.py repository`; deterministic projection is emitted by its `projection` command and validated by verify_repo.py.

## Review boundary

Human review remains responsible for representative loads/hardware/camera classes, legal clearance, scientific grounding of supplied b-1 gate/pairwise outcomes and confidence envelopes, exact inferencer/configuration execution attestation, and owner margin/SLA wisdom. Before S2c.3 emits a first-selection-read chain, the freeze-before-read attestation is reviewed rather than independently provable. Hashes detect mismatch against retained references; they do not authenticate an author or detect coordinated replacement of all roots. No real experiment is frozen by implementing this method.

<!-- BEGIN S2C_B2_CONTRACT_PROJECTION -->
_Generated from `s2c-operational-selection-contract.json`._

### compositionAccounting

```json
{"PO-B0Selectable":false,"exactExecutableUnits":true,"standaloneRankPruning":false}
```

### experimentFreeze

```json
{"completeManifest":true,"frozenTestSelection":false,"labelFreePreScreen":true,"selectionMutation":false}
```

### finalSelection

```json
{"credibilityChangesT":false,"credibilityChangesTr":false,"implementationOptimum":"recomputed-before-owner-choice","implementationPopulation":"K_person-times-K_vehicle","qualityFallbackChangesF":false,"setValued":true}
```

### frozenInvariants

```json
{"b1":true,"e3":true,"freeze":true,"implementation":true,"joint":true,"quality":true,"retention":true,"scope":true,"uncertainty":true}
```

### historicalOrdering

```json
{"paretoWinner":false,"rankSumComposition":false,"weightedWinner":false}
```

### hostProfile

```json
{"defaultHostClasses":1,"topologySearch":"frozen-label-free"}
```

### invariantStatements

```json
{"b1":"b-1 retains populations, calibration, partitions, gates, support, margins and paired outcomes.","e3":"Candidate-specific E3 contradiction reopens incomplete evidence; no selection rescue.","freeze":"Complete executable units, claims, family, fallback, workload, host, limits and objective precede selection.","implementation":"Credibility and licence enter K only; C_impl is K_person x K_vehicle; recompute T_impl.","joint":"J is F or the valid frozen fallback; technical selection uses exact person x vehicle pairs.","quality":"MPID precedes E; F protects directly against every other member of original E; no peeling or transitivity.","retention":"Canonical immutable quality results precede retained linear joint versions, which precede decision-v2.","scope":"500-camera capacity is a validated projection on declared loads/hardware, never blanket qualification.","uncertainty":"Hstar is min H_up over admitted pairs; T contains every pair with H_lo <= Hstar."}
```

### jointOperationalSelection

```json
{"bounds":"same-replay-lower-upper-frozen-demand","identity":"exact-pair","population":"J_person-times-J_vehicle","technicalSet":"H_lo<=min-H_up"}
```

### method

```json
"s2c-2b2"
```

### mpidExtensionRule

```json
{"allRequiredComparators":true,"beforeQualityProtection":true,"defaultUnavailable":"exclude-pending-ADR","requiredOutcome":"superior"}
```

### msrRepresentation

```json
{"S2cDecision":"mavi-model-selection-decision-v2","earlyImplementation":false,"nonS2cDecision":"mavi-model-selection-decision-v1","revision":"msr-v1-m2"}
```

### ownerInputs

```json
{"freezeBeforeRead":"reviewed-attestation-until-S2c3","numericalTargets":"event-frozen"}
```

### prerequisite

```json
{"deferredDispositions":{"10k-track-deadline-mechanics":"defined","500-camera-projection":"defined","composition-resource-accounting":"defined","disabled-attribute-frontier-treatment":"required-scope-gate","dominance-semantics":"retired-as-selection-authority","final-technical-selection":"defined","historical-weighted-ordering-reconciliation":"defined","msr-final-ranking-representation":"defined","non-dominated-set-construction":"retired-as-selection-authority","operational-performance":"defined","pareto-axes":"retired-as-selection-authority","pareto-directions":"retired-as-selection-authority","pareto-normalization":"retired-as-selection-authority","sub-task-finalist-ordering":"retired-as-selection-authority","whole-job-cpu-host-gates":"defined"},"method":"s2c-2b1","redefinesB1":false,"schema":"mavi-s2c-quality-statistics-v1"}
```

### qualityDecisionClaims

```json
{"directions":["higher","lower"],"family":"all-ordered-manifest-pairs-times-Q","nonempty":true,"protection":"direct-all-original-E"}
```

### scaleProjection

```json
{"E2":"real-S2b-runner-inference-seam","E3":"held-out-integrated-engineering","cameraTarget":500,"fluidIsDeadlineProof":false,"qualificationClaim":false,"replay":"bounded-whole-job"}
```

### schema

```json
"mavi-s2c-operational-selection-v1"
```

### wholeJob

```json
{"acknowledgementIsCommit":false,"attemptConsumedAt":"claim","boundedPublicationIsOperationalGate":true,"checkpointReuse":false,"claimAtDeadline":false,"completedAtUtc":"phase-C-transaction-sample","deadlineFrom":"firstClaimedAtUtc","fifo":["queuedAtUtc","id"],"leaseDeadlineCap":true,"phaseCFence":"ownership","publicationProtection":"phaseA-plus-lease-capped-at-deadline-plus-lease","retryRetainsQueue":true}
```

### workloadFamily

```json
{"requiredShapes":["typical","small-burst","10k-boundary","mixed","recovery","500-camera"]}
```

<!-- END S2C_B2_CONTRACT_PROJECTION -->
