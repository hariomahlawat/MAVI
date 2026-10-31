# ADR-026: Ask MAVI — the language runtime, closed translation and the grounding rule (PoC Stage 9)

**Status:** **Accepted**, 2026-10-30. The owner ratified this ADR as written ("accept all"), relayed by the coordinator session. Register: owner decisions D-S10-1 (this ADR), D-S10-2 (both models and both runtime builds in the kit), D-S10-3 (the laptop demonstrates the 1.5B only), D-S10-4 (the C9.2 bar) and D-S10-5 (the §3 exception to `AGENTS.md` rule 3). The decision text below is unchanged. Amendments follow it: accepted ones are dated and part of the decision; proposed ones are not, until accepted.

**Date:** 2026-10-30

**Related:**
- ADR-024 (the structured query contract `mavi-query-v1`: closed, versioned, typed refusals, the result envelope). Ask MAVI is its second consumer.
- ADR-020 (`poc-single-host`, Development evidence class, mandatory disclosure).
- ADR-002 and `AGENTS.md` architecture rule 3 (inference runs outside the operational platform), ADR-003 (offline Production), ADR-008 (device policy `Auto`/`CUDA`/`CPU`), ADR-014 (Model Pack identity, fail-closed selection).
- Plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`, decision D7 and slice S10. Register `docs/reviews/2026-10-28-poc-acceptance.md`, rows C9.1, C9.2 and C9.3.

## Context

Stage 9 lets an operator ask in plain language what the Advanced Search builder (S9) composes by hand: "count Person Tracks that crossed the gate between 08:00 and 14:00, by hour". Plan decision D7 already fixed the model (Qwen2.5-Instruct, Apache-2.0, in GGUF through llama.cpp, MIT; the research-licensed 3B and 72B sizes excluded) and the rule that **the model only writes structured queries and MAVI computes**. Four things are left to decide before code:

1. where the language runtime runs and how it is bound, verified and started;
2. what exactly the model is allowed to emit, and what happens to anything else;
3. what the operator is shown, and how we prove that none of it was invented by the model;
4. how a non-deterministic-looking component gets a reproducible, testable claim.

A language model is the first PoC component whose output reads like an answer. The risk is not a wrong query (the operator can see and reject a wrong interpretation) but a **plausible fact that no query produced**. Every decision below exists to make that impossible by construction rather than unlikely by prompting.

## Decision

### 1. The Language Runtime Pack: the published llama.cpp Windows builds, not a local build

- The runtime is llama.cpp release **`b12000`** (MIT), consumed as the project's own published Windows x64 archives: `llama-b12000-bin-win-cpu-x64.zip` (CPU, runtime-dispatched AVX/AVX2/AVX-512 variants) and `llama-b12000-bin-win-cuda-12.4-x64.zip` with `cudart-llama-bin-win-cuda-12.4-x64.zip` (CUDA 12.4, the same major line as the pinned torch `cu124` runtime).
- **No compiler and no build contract is involved.** The frozen Windows CUDA build contracts v1 and v2 govern mmcv and torch and are unchanged. The published CUDA build carries native code (SASS) for `sm_86`/`sm_89` (the RTX 4090) and PTX for `sm_50`–`sm_90`, so the GTX 1650 Ti (`sm_75`) runs it through the driver's PTX JIT (measured with `cuobjdump` at acquisition and recorded in the payload file). The launcher points `CUDA_CACHE_PATH` at the PoC data root so the JIT cache is never written to the system profile.
- Each archive and the upstream `LICENSE` at the tag are acquired once on the Development machine (HTTPS, SHA-256 compared with the release's published digest) and recorded in `tools/language/language-payloads-v1.json`. The SHA-256 of every executable and library the role loads is recorded there too, and the launcher verifies them before every start. They travel through the Offline Binary Kit like every other native payload.

### 2. The Language Model Packs

Two packs, each a source model manifest (ADR-014 §3) under `models/manifests/`, from Qwen's own GGUF repositories at pinned revisions, with the licence read from **each repository's own `LICENSE` file** and kept as the pack's `licence-notice` artefact:

| Pack | File | Quantisation and reason | Hardware |
|---|---|---|---|
| `language-qwen2.5-1.5b-instruct-q8-0-dev-v1` | `qwen2.5-1.5b-instruct-q8_0.gguf` (1.89 GB) | **Q8_0**: at 1.5B parameters quantisation error costs more accuracy than at 7B, and Q8_0 is still small enough to sit fully on a 4 GiB GPU with its context, or run on CPU | the Development laptop: GTX 1650 Ti (`sm_75`, 4 GiB) or CPU |
| `language-qwen2.5-7b-instruct-q4-k-m-dev-v1` | `qwen2.5-7b-instruct-q4_k_m-0000{1,2}-of-00002.gguf` (4.68 GB, the upstream two-part split, loaded as one model) | **Q4_K_M**: the standard size/quality point for 7B; leaves most of the 4090's memory to the vision roles | the demonstration host: RTX 4090 (`sm_89`) |

Both are `verificationStatus: unverified` Development packs (ADR-020 §1). The 3B and 72B sizes are never acquired. Model bytes never enter Git.

### 3. Topology: the `language` role is a supervised loopback inference process the API calls synchronously

- The PoC launcher starts the pack's `llama-server.exe` as the `language` role (`tools/setup/Start-MaviLanguageRuntime.ps1`), bound to `127.0.0.1` on a configured port, one slot, the bound GGUF, its context size and its thread count fixed by configuration. The launcher verifies the runtime and model hashes first, resolves the device by ADR-008 policy (`Auto` prefers CUDA when a compatible GPU is present and records the reason; explicit `CUDA` fails closed) and writes the device record, as the other roles do.
- The API calls it through one narrow typed client (`ILanguageRuntime`): prompt text and decoding grammar in, generated text out, with a bounded timeout. The pack identity it reports is the one the installer bound (`Language:*` machine configuration), and the device is the one the launcher observed and recorded; the launcher verifies, before every start, that the bound pack is the one on disk. **It is not a lease worker.** Ask MAVI is an interactive request with no media and no durable result; a job table and polling would add latency and state without adding evidence. The translator holds no authority: it produces candidate text that the platform then validates (§4).
- **Reading of `AGENTS.md` rule 3.** Rule 3 keeps AI inference out of the operational platform and keeps authority out of the inference side. Here inference runs in its own native process, never inside the .NET process, and owns nothing. What changes is that this role is native C++ rather than Python and is called rather than polling. That is a deliberate exception for one runtime, stated here so the owner can refuse it; the alternative is §Alternatives B.
- The API refuses an Ask request with `language_unavailable` when the role is not bound or not answering. Nothing else in MAVI depends on it.

### 4. Closed translation: a query or a refusal, validated, never repaired

The model sees the vocabulary the platform publishes at `GET /api/query/contract` (units, predicates, operations, dimensions, bounds, attribute vocabulary, rule ids), the **site catalogue** (each camera's id and name, and the enabled zones and lines of its active scene revision with their names and direction labels), the site time zone and the reference date, and a fixed set of worked examples. It must emit exactly one **translation document**:

```json
{"answer": "query", "query": { …a mavi-query-v1 document… }}
{"answer": "refusal", "reason": "outside_contract" | "unknown_reference"}
```

- **Decoding is constrained** by a grammar the API derives per request from the same vocabulary and catalogue: the model can only write members the contract has, and only ids the catalogue lists. Constraint is a generation aid, not the authority.
- **One lossless rewrite.** Instants are written by the model as site-local time with the site's explicit UTC offset (`2026-10-01T09:00:00+05:30`), because a small model cannot be relied on to do time-zone arithmetic. The translator converts each to the same instant in UTC (`2026-10-01T03:30:00Z`) and refuses the translation if the offset is not the site zone's offset at that instant (`Z` therefore passes only for a site whose offset is +00:00; millisecond fractions are accepted and kept). No other member is rewritten, defaulted, completed or reordered by the translator.
- **Then the strict S9 parser and the S9 service decide.** The rewritten query goes through `StructuredQueryParser.Parse` and `StructuredQueryService.EvaluateAsync` exactly as a builder query does, including every typed refusal. The JSON Schema `structured-query-v1.schema.json` checks the same documents in CI (§6); the golden corpus already holds parser and schema to each other (ADR-024 §1).
- **Anything out of contract is refused to the operator with its reason, never retried.** (Since D-S10-10, 2026-10-31, Ask does not evaluate the query: a service refusal comes from the operator's Run through `POST /api/query`, and the `service` stage of an Ask refusal no longer exists; see the amendment.) Unparseable output, a member outside the translation document, a bad offset, a parser refusal or a service refusal ends the request with a typed refusal: the stage (`model`, `translation`, `contract`, `service`), the code, the JSON pointer where there is one, and fixed platform text for the message. There is no second attempt, no "repair" pass and no fallback to a different prompt, because each of those would turn an honest "I can't ask that" into something plausible.
- A model refusal carries **no free text**: the reason is one of the two codes and the message shown is platform text.

### 5. The grounding rule: nothing displayed is model-generated

The operator sees:

- the question as typed;
- **"Interpreted as"**: the server's canonical `resolvedQuery` from the S9 envelope, rendered in readable form by a deterministic formatter (camera, zone and line names come from the envelope's identity block and the catalogue, never from model text), with the exact JSON one click away;
- **the answer**: the S9 envelope only — a count, groups, buckets, comparison or rows — as figure, chart and table, with the same withheld, empty and partial-coverage states the Advanced Search page shows; a one-line summary sentence is produced by a fixed template from envelope fields;
- drill-through to Tracks (Review, pinned as S9 pins it) and Events from envelope ids;
- a refusal, plainly, with its stage and reason;
- the model and runtime identity, the latency, and the Development disclosure.

The model's raw text is never displayed. The rule is checked by **grounding tests**: for a fixed set of envelopes, every number and every name the Ask surface renders must equal a value of the envelope (or of the catalogue, for names), and the surface must render nothing for a refusal except the refusal.

### 6. Determinism and the measured claim

- Decoding is greedy (temperature 0, top-k 1) with a fixed seed, no prompt-cache reuse, one slot, and a pinned pack identity; the API records the decoding settings and the bound pack identity with every answer.
- **The question corpus** (`contracts/test-vectors/ask-mavi-questions-v1.json`, about 60 questions in the demo-corpus domain, written before the model was run on it) gives each question a reference date and its expected canonical query or expected refusal. It is split into a **development** part (used while the prompt and examples were written) and a **held** part (frozen before measurement and not used to tune anything). The held exact-match rate is **the only measured claim** of Ask MAVI.
- **CI cannot run the model** (no GPU, no model bytes on runners, and model bytes never enter Git). CI therefore replays **recorded model outputs** (`contracts/test-vectors/ask-mavi-recordings-*.json`), each bound to the model pack identity, the runtime identity and device, the decoding settings and the SHA-256 of the exact prompt. A CI test rebuilds every prompt from the current code and fixture catalogue and fails if any hash differs (the recordings are then stale and must be re-recorded); it then runs each recorded output through the real translator, parser and canonicaliser and checks the outcome against the expected one. The recordings are re-made locally with one command against a running language role. The limit is stated: CI proves the pipeline and the recorded run, not a fresh inference.
- Recordings are device-specific: the same GGUF can decode differently on CPU, on the `sm_75` JIT path and on `sm_89`. Each recording set names its device.

### 7. Surface

- `POST /api/ask` `{question, referenceDate?}` returns the translation outcome and, for a query, the unchanged S9 envelope; `GET /api/ask/status` reports whether the language role is bound and answering, with pack and runtime identity. Both are read-only; neither stores the question.
- The web surface is a page in the operator rail ("Ask MAVI"), built from the existing Advanced Search result components.

## Trade-off accepted

A closed translation target trades **conversational range** for the guarantee that **nothing displayed is model-generated**.

- The operator can ask only what `mavi-query-v1` can express: no "why", no identity, no prediction, no follow-up that depends on the previous answer, no free summary, no OR or nesting, no relative phrases the reference date does not settle. Those questions are refused, not approximated.
- The model may still misread a question that is in range. That error is visible ("Interpreted as") and bounded (it can only produce a valid query the operator could have built by hand); the corpus measures how often it happens. It cannot produce a number.
- In exchange every displayed figure has the S9 contract's properties: checkable before it runs, the same answer from the same snapshot, identity and coverage attached, withheld rather than invented when coverage is incomplete.

## Consequences

- New native payloads (llama.cpp CPU and CUDA builds, CUDA 12.4 runtime DLLs) and two Model Packs: dependency policy, binary catalogue, kit, licences and runbooks change in the same PR. No NuGet, npm or Python package is added; the API calls the runtime with `HttpClient`.
- A new PoC role (`language`) in the installer, launcher, stopper, uninstaller and System page.
- No schema migration and no new table; Ask stores nothing.
- Adding a predicate to Ask means adding it to the S9 contract first (a new contract version), then to the prompt, grammar and corpus.

## Alternatives rejected

- **A. Free generation with post-hoc validation only** (no grammar). Simpler, but a 1.5B model then fails on syntax rather than meaning, and the failures are invisible in the corpus as "refusals" that are really format errors. Constraint keeps the corpus about understanding.
- **B. A Python lease worker wrapping the model** (`llama-cpp-python` or a Python client of `llama-server`), matching the vision roles' polling pattern. It satisfies rule 3 literally, but adds a compiled Python dependency or a second hop, a job table and polling latency to an interactive request, for no change in authority. Kept available if the owner reads rule 3 strictly.
- **C. Letting the model write UTC directly.** Rejected for the time-zone arithmetic it demands of a small model; the explicit-offset rewrite is lossless and checked.
- **D. Letting the model phrase the answer.** Rejected: it is exactly the fabrication path this ADR exists to close.
- **E. Running the model in CI** (download weights on the runner at a pinned hash). Possible for the 1.5B on CPU, but slow (minutes per corpus pass), Internet-dependent in CI, and still not the device the demonstration uses; recorded, hash-bound outputs give the same regression protection deterministically.

## Amendment 2026-10-30 (accepted, D-S10-6): lexical gating of the decoding grammar (§4)

The owner adopted this amendment ("agree", 2026-10-30). It adds to §4:

1. **Lexical gating of the decoding grammar.** On the development split both models added predicates the question did not ask for: an invented colour attribute, an unasked zone, line or direction, or an extra camera. The grammar is therefore also gated by the question (`AskQuestionScope`):
   - a camera, zone or line can be written only if the question contains every significant word of its name (a camera also through a zone or line of its own);
   - a line direction only on the side whose label (or a fixed synonym) the question contains;
   - an attribute value only if it occurs in the question;
   - a plate text, a rule, the vehicle subclass, a duration or the Entity unit only if their fixed words occur.

   It is a pure function of the question and the catalogue and only removes choices. Trade-off: indirect phrasing ("the gate" for a line named "Arch gate") cannot reference that item. The query then lacks the predicate, which "Interpreted as" shows, or the model refuses. Measured effect on the development split: the 7B pack rose from 12/20 to 16/20, and the 1.5B pack from 8/20 to 11/20 and then 10/20, the two figures being two successive gating rounds (each deterministic), not run-to-run noise.

## Amendment 2026-10-30 (accepted, D-S10-7): prompt-prefix cache reuse (§6)

The owner accepted this amendment on condition ("Accept, conditional", 2026-10-30), and the condition is met. In §6, "no prompt-cache reuse" is replaced by: **the cached prompt prefix is reused (`cache_prompt: true`); recordings are made the same way.**

- **Why.** The prompt is about 6,400 tokens and only the question changes. Without reuse, a question costs about 17 s on the laptop GPU for the 1.5B pack and several minutes for the 7B pack on that GPU.
- **Evidence.** Each model was recorded over all 60 corpus questions, once in corpus order and once in reverse order. All 60 model outputs were byte-identical, so reuse does not change what the model writes. Hash = SHA-256 of the compact JSON array of the 60 outputs in corpus order.

| Pack, device | Forward hash | Reverse hash |
|---|---|---|
| 7B Q4_K_M, GTX 1650 Ti partial offload | `82b2fe6ff8f8013f92501e4383e0f5a8698377c6e7b2b4332dcf74449f640958` | identical |
| 1.5B Q8_0, GTX 1650 Ti | `297f62993d41b686a95b333aaf38d0b32808bbaa7e515a341378f0526acc58a6` | identical |

  The reverse recordings are kept under `E:\MAVI-Controlled\PoC\S10\reverse\`. A new recording set (another device, or prompt v2) repeats this check. If any output differs, reuse is switched off for that set and the set is re-recorded.

  **Prompt v2 (2026-10-31): reuse failed the condition for the 7B pack and is off for it.**
  - The 7B pack's prompt-v2 held set, recorded with reuse on the laptop (16 of 28 layers on the GPU), was not byte-identical in reverse order. One output (n11) differed in bytes but kept the same canonical outcome.
  - Reuse is therefore off for the 7B pack. `Language:CachePrompt` is resolved per pack by the installer and asserted by the setup contracts.
  - The set was re-recorded with reuse off, and that recording is byte-identical in both orders (`b8295f54…`).
  - Reuse does change decoding numerics on that device: the superseded reuse-on run decoded n26 differently and scored 21/40, against 20/40. This is disclosed in the register.
  - The 1.5B pack's prompt-v2 set is byte-identical in both orders with reuse on (`a04dee1d…`), so reuse stays on for it.

## Amendment 2026-10-31 (accepted, D-S10-9): prompt version `mavi-ask-prompt-v2` (§4, §6)

The owner accepted this amendment, with one edit to the measurement ("Accept with edit", 2026-10-31; relayed by the coordinator session). It follows owner decision D-S10-8 ("Keep bar, follow-up"). The C9.2 bar (D-S10-4) is unchanged: the 7B overall held exact-match must be at least 85%, safety and grounding 100%, and the CI replay exact.

**Why.** On the v1 held split the 7B pack answered two questions about places the site does not have ("the Central Station camera", "the Loading dock zone") for the whole site. The reason: gating removed the reference the model could not match, and the model then wrote a valid whole-site query. The S10 cold review also deferred three items that change prompt or grammar bytes: plate text grounded in the question (m2), tighter single-word gating (m3), and daylight-saving offsets (m8).

**Version 1 is kept byte for byte.** The v1 prompt, grammar, gating and translator path stay in the code, so the v1 recordings keep replaying in CI. They are never re-recorded. The API uses v2 (`AskPrompt.TemplateVersion`). A recording set replays through the version it names.

1. **Unknown places are refused by the platform, before the model (`AskPlaceReferences`).**
   - The question's place references are found by three fixed patterns:
     - (a) the words before a singular `camera`, `cam`, `zone` or `line`, back to an article, preposition, question word or sentence start. Ranking words ("the busiest camera") and fixed compounds ("line crossings", "line direction", "zone dwell") are excluded;
     - (b) such a noun followed by a number or a capitalised name ("camera 14", "zone C");
     - (c) a run of two or more capitalised words that is not at a sentence start and is not contract vocabulary ("Central Station").
   - A reference names the catalogue items of its kind whose names contain all its words. A camera can also be named by the number its code ends with.
   - Gating offers the named items to the model. A reference that names nothing refuses the request: `unknown_reference` at a new stage `question`, with platform text. The model is not called.
   - **Corpus accounting:** this refusal matches an expected `unknown_reference`. Recordings mark these rows with the stage and no output, and CI re-derives the refusal from the current code.
   - **Trade-offs:** a question whose wording looks like an unknown place is refused rather than answered. A place named outside the three patterns ("the parking garage") is still left to the model, as in v1.
2. **Plate text grounded in the question (m2).** After the strict parser, a plate text is accepted only when its normalised form (`mavi-plate-normalisation-v1`) occurs in the question's letters and digits, upper-cased and joined. Otherwise the request is refused with `plate_text_ungrounded` at stage `translation`.
3. **Tighter gating (m3).**
   - A name with one significant word ("Crossing") is offered only for "<name> <kind>" ("crossing zone").
   - A name that ends in its kind ("Count line") is offered only for that phrase.
   - A line side labelled "In" or "Out" is offered only for a synonym or a verb phrase ("went in", "walked out"), never for the bare preposition.
   - "To door" and "From door" are offered only for their phrase.
4. **Every offset of the site zone (m8).**
   - The grammar's instant pattern admits each offset the site zone uses from the reference date minus 366 days to the reference date plus 2 days.
   - The translator still refuses an offset that is not the zone's own at that instant.
   - For a zone with daylight saving, the prompt names both offsets. For a single-offset zone (the demo's Asia/Kolkata) the time sentence is unchanged.
5. **One query shape per unit.**
   - The grammar offers Track, Event (and Entity, when the question names entities) as separate shapes.
   - Each shape has only the predicates, `groupBy`/`top` dimensions and `countDistinct` fields the contract allows for that unit. An Event zone names the zone only.
   - A predicate the unit lacks therefore cannot be decoded. Like gating, this only removes choices, and the strict parser remains the authority.
6. **Prompt text** (chosen on the development set only, the 60 v1 questions):
   - the refusal sentence also covers "any other place … the site list does not have";
   - four rules: durations in milliseconds; loitering as a Track zone predicate; "by hour" as `timeBucket` 3600, never `groupBy`; "show", "list" and "find" as `find` even for one thing;
   - one worked example of a zone question "by hour";
   - the JSON the model is shown is written as the grammar lets it write it (`+05:30`, not `+05:30`).
7. **Measurement (§6).**
   - The v1 held split is spent and becomes development data.
   - v2 is measured once per model on a **fresh held split** (`contracts/test-vectors/ask-mavi-questions-v2.json`). That split is written under the authorship rule the owner ratified and committed with its SHA-256 before any v2 model output existed.
     - Rule: a fresh agent writes it, blind to the v2 design and to every model output, and a second blind agent checks it. It is validated by the parser and the schema. The implementer does not read it until both held runs are recorded.
     - **Owner's edit:** it keeps the v1 held split's proportions, 31 in contract, 6 `outside_contract` and 3 `unknown_reference` out of 40. The pre-check makes `unknown_reference` refusals nearly free, so a richer refusal mix would ease the bar.
     - The report gives the in-contract exact-match beside the overall figure, and the number of pre-check refusals.
   - The protocol, prompt, grammar and pre-check are frozen by commit before the held runs.
   - The reverse-order byte-identity check (D-S10-7) is repeated for each v2 recording set.

**Trade-off accepted.**
- Deterministic place checks and a narrower grammar trade some recall for the guarantee that a named place the site lacks is refused, not answered for the whole site. A valid question with place-like wording, or an item named by a partial phrase the patterns do not catch, may be refused.
- Both outcomes are visible: a refusal, or "Interpreted as". Neither can produce a number the site did not compute.

**Measured result (2026-10-31).**
- The fresh held split was measured once against the unchanged bar:
  - 7B pack 20/40 (50%), in contract 17/31. **The bar is not met.**
  - 1.5B pack 19/40, in contract 16/31.
- The pre-check refused 2 of the 3 unknown places, with no false refusal on those 40 questions. The 7B had no parser refusal, and the 1.5B had one (a duplicated camera id). Safety and grounding are 100%, and CI replay is exact.
- Cold-review fixes to the pre-check came after measurement. They leave every held and development decision unchanged, and CI replays the recordings exactly.
- The pre-check can still refuse a valid question whose wording looks like an unknown place (known-limits).
- Reuse for the 1.5B was checked on `sm_75` only. Another device (CPU, or `sm_89` at S12) repeats the reverse-order check before reuse is relied on there.
- The remaining misses are the model's: dropped predicates, wrong units or relations, and outside-contract questions answered as queries. Register C9.2 holds the classification.

## Amendment 2026-10-31 (accepted, D-S10-10): Ask MAVI proposes, the operator confirms (§5, §7)

The owner decided this on 2026-10-31 ("Yes, (a)+(b)+confirm"), after the measured result of prompt v2: about one question in two is interpreted exactly on independently written questions.

- **The decision.** It replaces "the query is evaluated" in §4 and §7, and "the answer" in §5.
  - `POST /api/ask` translates the question and returns the **proposed query** (`outcome: interpreted`): the strict parser's canonical query, its fingerprint and the catalogue names, or a typed refusal.
  - It never evaluates the query. The Ask service has no access to the query service, and the response has no envelope member, so no answer can exist before the operator confirms.
  - The page shows the proposal ("Interpreted as", the query JSON one click away) with two actions:
    - **Run** sends exactly the proposed query to `POST /api/query`. The answer, coverage and drill-through are that envelope, rendered as before (§5 grounding unchanged).
    - **Open in Advanced Search** loads the query into the builder without running it. It is disabled, with the reason shown, for a query the builder cannot hold losslessly (a minimum duration, a minimum dwell or loitering, a bucket size the builder does not offer).
  - Refusals are unchanged. A refusal of the S9 service now comes from Run (`POST /api/query`), so the `service` stage of an Ask refusal no longer exists. An Entity query run by a caller who is not an operator is refused by the query endpoint (401/403, ADR-023), and the page says it is for operators only.
  - When attributes imply the object class, the S9 service states that class at run time (ADR-024), so the fingerprint of the query as run can differ from the proposal's. The page says so, and Open in Advanced Search refuses attributes without a class, because the builder would send them hidden.
- **Accuracy stated.** The measured accuracy (C9.2, prompt v2 on the fresh held split) is stated on the Ask page and on known-limits: 7B 20/40, 1.5B 19/40.
- **Why.** At this accuracy an unconfirmed answer would present the result of a misread question as an answer. Confirming first makes the interpretation, not the number, the thing the operator acts on. Running costs one click.
- **Trade-off accepted.** One more step per question, in exchange for no number reaching the operator for a query they have not seen and accepted.
- **Evidence.** E2E with the 1.5B under the confirm flow:
  - every one of the 40 Ask responses carried no answer;
  - Run answered 35 queries, refused the one Entity query for the anonymous caller (#253), and 4 questions were refused with nothing to run;
  - translation 19/40, unchanged.
- **Also decided (D-S10-10).**
  - C9.2 stays FAIL and S10 closes.
  - The frozen prompt v2 is measured on the RTX 4090 at S12, as disclosed evidence, not as a new attempt at the bar.
  - The first post-PoC improvement is the larger Apache-2.0 model (Qwen2.5-14B-Instruct) with deterministic slot checks, measured on a new fresh held split.
