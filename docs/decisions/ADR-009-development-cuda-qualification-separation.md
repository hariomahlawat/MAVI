# ADR-009 — Separate Development CUDA Hardware Qualification from Production CUDA Qualification

**Status:** Accepted  
**Date:** 2026-09-18  
**Context:** Windows-CUDA Development enablement / Task 18

## Decision

MAVI distinguishes **Development CUDA hardware qualification** from **Production CUDA qualification** at the runtime-metadata level.

A CUDA runtime variant may therefore have one of three relevant states:

- `pending-hardware-qualification`
- `qualified-development-hardware`
- `qualified-hardware`

`qualified-development-hardware` means that an exact CUDA Runtime Pack has been exercised successfully on controlled Development hardware and has retained non-CI evidence that binds the host observation, source revision and evidence bundle.

It does **not** mean that the runtime variant is acceptable for a Production deployment profile.

Production profile verification continues to require `qualified-hardware`.

## Why this is required

The available Windows laptop is useful and appropriate for engineering validation, but it is not automatically representative of the eventual P1 Production host.

Using the same `qualified-hardware` state for both Development and Production would allow a successful laptop run to satisfy the exact runtime status later consumed by P1. That would collapse two deliberately separate assurance boundaries.

The distinction must therefore be encoded in machine-readable metadata, not left to operator interpretation.

## Development evidence shape

A `qualified-development-hardware` runtime variant records:

- exact host-observation SHA-256;
- exact Development evidence-bundle SHA-256;
- exact source head SHA;
- capture timestamp;
- operator/reference identifier;
- exact resolved-config SHA-256;
- exact Python identity;
- exact Torch and torchvision binary build identities.

It does **not** fabricate GitHub Actions run/job IDs.

## Production rejection rule

Every Production deployment profile that uses CUDA requires the selected runtime variant to be `qualified-hardware`.

The profile-aware release verifier must reject `qualified-development-hardware` for P1 and P2.

The global runtime profile also remains `partial` while a CUDA variant is only Development-qualified.

## Gate/evidence separation

Development CUDA evidence is stored in the runtime variant's `developmentEvidence` object.

It must not set a Production qualification gate to passed merely because the same platform variant name is involved.

Production promotion and profile qualification remain bound to independent Production evidence collected under the selected deployment profile.

## Runtime lock behavior

A Development-qualified CUDA variant may bind and verify an exact offline Runtime lock. This enables reproducible Development execution.

That lock identity alone does not make the variant Production-qualified.

## Consequences

### Positive

- the laptop can be used rigorously without weakening Production assurance;
- no fake CI identifiers are required;
- Development CUDA becomes reproducible and evidence-bearing;
- future P1 qualification can reuse engineering knowledge without reusing the wrong qualification state.

### Required follow-up

When runtime metadata changes to record Development CUDA evidence:

1. the runtime-profile SHA-256 changes;
2. qualification metadata that binds the runtime-profile SHA-256 must be reissued;
3. the existing Windows CPU regression path must be re-proven against the new runtime-profile identity before merge;
4. later P1 qualification must generate new Production evidence and promote the CUDA state separately to `qualified-hardware`;
5. **the Production offline bundle's identity changes.** `verify_runtime_release_locks` returns every lock whose status is `qualified-offline-lock`, unfiltered by deployment profile, and `build_offline_bundle` both ships all of them and folds all of them into `qualifiedReleaseLocks` in the bundle ID. The moment the Windows CUDA Development lock is frozen, it is copied into the Linux P2 and Windows P3 Production bundles and every Production bundle ID changes.

   This ADR does not decide which way that is resolved. Before the CUDA lock is frozen, one of the two must be chosen deliberately:

   - **filter** the bundled locks to the variants the selected deployment profile requires, which keeps Production bundle identity independent of Development work but makes a bundle no longer a complete record of the runtime profile it was built from; or
   - **accept** that a Development lock participates in Production bundle identity, in which case Production acceptance evidence must be reissued when it is frozen.

   Today's behaviour is the second, and is pinned by `test_every_qualified_lock_enters_the_bundle_identity_of_every_variant` so it cannot change silently.

## Non-decision

This ADR does not select final Production hardware, does not qualify P1, and does not assert that the Development laptop satisfies Production performance requirements.
