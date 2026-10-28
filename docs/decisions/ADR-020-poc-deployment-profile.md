# ADR-020: The `poc-single-host` deployment profile

**Status:** Accepted owner decision, 2026-10-28 (decision D1 of `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`). Amends ADR-008 by adding a profile; changes nothing in P1, P2, P3 or Task 18.

**Date:** 2026-10-28

**Related:** ADR-003 (offline Production); ADR-008 (device policy and Production profiles); ADR-009 (Development CUDA qualification separation); ADR-014 (capability binding v2); ADR-017 §10 and operating principle 6a (lightest evidence process appropriate to the claim); `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`; register `docs/reviews/2026-10-28-poc-acceptance.md`.

## Context

The owner has decided to build an end-to-end proof of concept covering every capability of the roadmap (Stages 2–10) that can be installed, tested and demonstrated on a single Windows host — the Development laptop now, a Windows host with an RTX 4090 for demonstrations — and improved later to production grade.

ADR-008 defines one Development reference topology and three Production profiles. None of them describes a PoC installation honestly:

- a Production profile (P1/P3) is **supported only after its exact platform/device combination has passed the required qualification evidence**, and no installer may imply support for a profile whose evidence is incomplete (ADR-008 "Phase-1 closure rule" items 2 and 4). Task 18 is `BLOCKED` and no Production profile is qualified;
- the Development topology assumes a developer workstation prepared by `Setup-MAVI-Development.cmd`, not a packaged install on a clean machine;
- ADR-009 forbids Development CUDA evidence from satisfying P1/P2, and the only Windows CUDA Runtime Pack is `qualified-development-hardware`, built for `sm_75`.

Without a named profile, every PoC slice would either misrepresent itself as Production or re-open Production qualification for work whose claim is demonstration.

## Decision

### 1. A fourth profile: `poc-single-host`

One Windows host runs the complete stack — React UI, ASP.NET Core API, MAVI-owned PostgreSQL + pgvector, application-local FFmpeg, the Vision worker and **every capability role** the PoC binds (plates, embeddings, attributes, faces, language) — installed from the Offline Binary Kit and a PoC setup bundle on a machine that may be disconnected from the network throughout.

Device policy is ADR-008's `Auto` / `CUDA` / `CPU`, unchanged: `Auto` prefers a compatible installed CUDA Runtime Pack variant and otherwise runs CPU with the resolved reason recorded; explicit `CUDA` fails closed; no silent fallback. The profile may use **Development-grade** Runtime Pack variants (the existing `qualified-development-hardware` `sm_75` pack, and the `sm_75;sm_89` variant built for the demonstration host, which is "built, hashed, locked" until a bound observation on the 4090 host earns it `qualified-development-hardware` under ADR-009) and Development-grade Model Packs (`verificationStatus: unverified` with recorded hashes and licences).

### 2. Evidence class

The profile's evidence class is **Development** (ADR-009). Each PoC slice records, in the PoC acceptance register: exact commits and CI run ids; Model Pack and Runtime Pack identities and hashes; licence and provenance of every asset; a reproducible functional demonstration; measured throughput per device; and honest limits. It does **not** carry Production qualification ceremony — no frozen protocol, no Model Selection Event, no protected holdout, no M3 authority — unless a slice chooses to make a Production claim, which this profile never does (principle 6a).

### 3. Mandatory disclosure

Every installation under this profile must state, in the operator UI (System/About page and a persistent banner), in release metadata and in the installer output: profile `poc-single-host`; **not Production-qualified**; evidence class Development; the resolved device and reason; and each bound pack's identity and verification status. The disclosure is machine-checked by a test and cannot be configured away under this profile.

### 4. Boundaries that do not move

- P1, P2 and P3 keep their ADR-008 definitions and their qualification requirements. A `poc-single-host` installation never becomes P1 or P3 by configuration; promotion is Task 18 on a frozen candidate.
- Development CUDA evidence still does not satisfy P1/P2 (ADR-009).
- Protected qualification data, frozen Stage-4 rules, M3 authority and the Stage-2 S2c protocol are untouched by PoC work.
- Offline rules (ADR-003, ADR-008 §4) apply in full: no network dependency at install or run time; every asset arrives through the kit.
- Dependency discipline applies in full: each new library, model, runtime or native payload updates `config/dependencies/offline-dependency-policy-v1.json`, the binary catalogue, the kit, licences and runbooks in the PR that introduces it.
- Biometric and plate-text data handling under this profile follow their own ADRs (ADR-022 for faces); the PoC profile grants no exemption.

### 5. Promotion path

A capability built under this profile becomes a Production candidate the way any other does: its packs are verified and qualified for the target profile, its evidence is produced under the Production rules, and Task 18 (or its successor) qualifies the frozen candidate. The PoC profile exists so that this work can be deferred honestly, not skipped.

## Rationale

1. A PoC that runs end to end on a clean machine is the fastest route to a demonstrable, improvable product, and ADR-008's profile model already anticipates qualification attaching to profiles rather than to code.
2. Naming the profile keeps ADR-008's closure rule true: no installer implies Production support, because the installer says the opposite.
3. Development-grade evidence is the right size for a demonstration claim (principle 6a); Production ceremony would not make the demonstration truer, only later.
4. The 4090 demonstration host is `sm_89`; the frozen build contract is `sm_75` only. A second Development-grade variant under this profile is cheaper and more honest than pretending the existing pack covers it or than qualifying a Production CUDA pack for a PoC.

## Consequences

- Setup tooling gains a PoC install path (`Install-MAVI-PoC`) and a PoC setup bundle; the release metadata schema gains the profile value and the disclosure fields.
- The System/About page and banner become a tested contract.
- A second Windows CUDA Runtime Pack variant (`sm_75;sm_89`) is added under a second build contract (`config/vision/windows-cuda-development-build-v2.json`, its own target-GPU list and native ABI); the frozen v1 contract is unchanged. For the PoC profile only, the owner accepts the Development laptop as the v2 variant's build host (plan D9). `onnxruntime-gpu` pins are added as Development-grade packs.
- `docs/architecture/phase1-production-topology.md` and `docs/runbooks/mavi-offline-setup.md` gain a `poc-single-host` section stating that it is not a Production profile.
- Task 18's `BLOCKED` state, P1/P2/P3 status and every existing qualification record are unchanged.
