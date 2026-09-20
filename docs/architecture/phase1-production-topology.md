# Development and Phase-1 Production Deployment Profiles

**Authority:** ADR-008  
**Status:** Approved architecture. Exact device/runtime versions and profile qualification evidence remain pending.

## Development reference topology — single Windows laptop/workstation

```text
Windows Development Machine
├── React UI
├── ASP.NET Core API
├── MAVI PostgreSQL + pgvector
├── App-local FFmpeg
└── MAVI Vision Worker
    ├── Model Pack
    └── Device policy
        ├── Auto  -> CUDA when compatible/available, otherwise CPU
        ├── CUDA  -> require GPU or fail
        └── CPU   -> force CPU
```

This is the normal development model. A second machine is not required.

### Development device rules

- Use GPU when available and the correct Windows CUDA Runtime Pack is installed.
- CPU remains a supported explicit mode.
- `Auto` may fall back only with clear startup/runtime logging and provenance.
- `CUDA` must fail rather than silently execute on CPU.
- Device actually used must be recorded with the processing/runtime provenance.

## Production profiles

### P1 — Single-host Windows GPU

```text
Windows Production Host
├── IIS / ASP.NET Core
│   └── MAVI API + React UI
├── App-local FFmpeg
├── MAVI PostgreSQL 18 + pgvector
└── MAVI Vision Worker
    ├── Windows CUDA Runtime Pack
    ├── Model Pack
    └── NVIDIA GPU
```

Use when one capable Windows machine provides the complete installation.

### P2 — Split-host Windows + Linux GPU

```text
Controlled disconnected LAN

Host A — Windows
├── IIS / ASP.NET Core
├── MAVI API + React UI
├── App-local FFmpeg
└── MAVI PostgreSQL 18 + pgvector
          │
          │ worker/API contract
          ▼
Host B — Linux x86_64
└── MAVI Vision Worker
    ├── Linux CUDA Runtime Pack
    ├── Model Pack
    └── NVIDIA GPU
```

Use when dedicated compute, isolation or scale-out is desirable.

### P3 — Single-host Windows CPU

```text
Windows Production Host
├── IIS / ASP.NET Core
├── MAVI API + React UI
├── App-local FFmpeg
├── MAVI PostgreSQL 18 + pgvector
└── MAVI Vision Worker
    ├── Windows CPU Runtime Pack
    └── Model Pack
```

Use only where the qualified CPU performance envelope is acceptable.

## Logical-plane mapping

| Plane | Development | P1 | P2 | P3 |
|---|---|---|---|---|
| Operator | Windows laptop | Windows host | Windows Host A | Windows host |
| Operational | Windows laptop | Windows host | Windows Host A | Windows host |
| Data | Windows laptop | Windows host | Windows Host A | Windows host |
| Vision | Windows laptop | Windows host | Linux Host B | Windows host |
| Accelerator | optional Windows GPU | Windows GPU | Linux GPU | none |

Logical evidence boundaries remain separate even when planes share one physical host.

## Qualification rule

A profile is supported only when its exact evidence is complete.

| Profile | Current architectural status | Qualification status |
|---|---|---|
| Development Windows CPU | supported | real functional evidence exists |
| Development Windows CUDA | supported; runtime merged (PR #49, `ed1acf4`) | **C4 Development hardware evidence** on the controlled Development host (`qualified-development-hardware`, ADR-009); C5.4 device-resolution checks, C6 E2E runs and C7 failure matrix outstanding on the host; CUDA release lock still `pending-hardware-qualification`. This is Development evidence only and is **not** P1/P2 Production qualification. |
| P1 Windows GPU | approved Production profile | pending Windows CUDA + Production acceptance |
| P2 Windows + Linux GPU | approved Production profile | pending Linux CUDA + Production acceptance |
| P3 Windows CPU | approved Production profile | pending Production performance/acceptance even though CPU subsystem evidence exists |

No profile inherits qualification from another.

## Tooling status

The Task-18 implementation now carries the deployment profile through Runtime selection, prerequisite evidence, offline qualification, performance/recovery evidence, formal/failure scenarios, additive release promotion, Production acceptance and closure. Production startup requires an explicit profile and fails closed if its policy identity, runtime variant or host/device does not match. Development `Auto` prefers a qualified available Windows CUDA device and otherwise falls back visibly to CPU.

Authoritative Task-18 qualification remains blocked until this implementation passes exact-head CI, independent cold review, and the remaining acceptance inputs are frozen.

## Offline boundary

All Production profiles:

- run without Internet connectivity;
- use approved Offline Binary Kit/component media;
- prohibit first-run package/model downloads;
- prohibit CDN/runtime cloud dependencies;
- retain exact application, Runtime Pack, Model Pack and topology identities.
