# Phase-1 Production Topology

**Authority:** ADR-008  
**Status:** Approved architecture; exact prerequisite versions and qualification evidence remain pending.

## Canonical topology

```text
          Controlled disconnected LAN
        ┌───────────────────────────────┐
        │                               │
        │  Host A — Windows             │
        │  ┌─────────────────────────┐  │
        │  │ IIS / ASP.NET Core      │  │
        │  │ MAVI API + React UI     │  │
        │  │ App-local FFmpeg        │  │
        │  └────────────┬────────────┘  │
        │               │               │
        │  ┌────────────▼────────────┐  │
        │  │ MAVI PostgreSQL 18     │  │
        │  │ + pgvector             │  │
        │  │ database: mavi         │  │
        │  └─────────────────────────┘  │
        │                               │
        │         worker/API contract   │
        │                  │            │
        │                  ▼            │
        │  Host B — Linux x86_64        │
        │  ┌─────────────────────────┐  │
        │  │ MAVI Vision Worker      │  │
        │  │ Linux CUDA Runtime Pack │  │
        │  │ Qualified Model Pack    │  │
        │  │ NVIDIA GPU              │  │
        │  └─────────────────────────┘  │
        │                               │
        └───────────────────────────────┘
                 No Internet dependency
```

## Logical planes

| Plane | Physical host | Phase-1 responsibility |
|---|---|---|
| Operator | Host A | React UI served through MAVI/IIS |
| Operational | Host A | ASP.NET Core API, orchestration, worker control plane |
| Data | Host A | MAVI-owned PostgreSQL 18 + pgvector, authoritative state |
| Vision | Host B | RTMDet/ByteTrack execution on qualified Linux CUDA worker |
| Integration | LAN contract | Versioned API/worker contracts and evidence-bound identities |

Co-location of Operational and Data planes on Host A is the canonical Phase-1 deployment choice. They remain separate logical/evidence roles.

## Storage

Production storage is under the MAVI-owned Production root on Host A and must expose distinct identities for:

- managed source media;
- accepted evidence;
- database;
- setup/qualification evidence where applicable.

Exact roots are installation-policy values and must be captured in qualification evidence rather than assumed from a developer workstation.

## Runtime/model distribution

Host B receives Vision components from approved offline media:

- Linux CUDA Runtime Binary Pack — **not yet qualified**;
- required Model Pack;
- current Application / Release Overlay.

No first-run package/model download is allowed.

## Qualification boundary

The topology is approved. The following remain unresolved and therefore block authoritative final acceptance:

1. exact Windows/IIS/.NET/PostgreSQL/pgvector versions;
2. exact Linux distribution/Python/NVIDIA/CUDA versions;
3. Linux CUDA Runtime Pack identity and hardware evidence;
4. final application artifact;
5. final Offline Binary Kit/setup-media identity;
6. acceptance corpus and thresholds;
7. supported-update artifact/scope.

The topology approval does not convert any pending qualification gate into passed.
