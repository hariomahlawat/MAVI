# ADR-004: MAVI Time and Timezone Architecture

**Status:** Accepted  
**Date:** 2026-09-09

## Decision

UTC is MAVI's canonical internal and cross-system time. Absolute instants use `DateTimeOffset`, UTC API timestamps, and PostgreSQL `timestamptz`. Current UTC comes from injected .NET `TimeProvider`.

IANA/tzdb timezone identifiers describe wall-clock interpretation. New API and configuration writes accept only recognized IANA identifiers (including the explicitly supported slashless `UTC` alias) and reject Windows identifiers. A narrowly authorized pre-release repair to `PreserveRecordingTimeProvenance` deterministically canonicalizes legacy Windows identifiers to committed IANA mappings; unknown legacy identifiers fail migration rather than corrupting provenance. A Camera's timezone is authoritative when a source local timestamp is imported. Each VideoAsset snapshots the actual `RecordingTimeZoneId` and `RecordingUtcOffsetMinutes`, so later camera configuration changes cannot reinterpret historical evidence. Invalid and ambiguous wall-clock times are rejected by the central application-facing timezone service.

The operator display timezone is deployment configuration and defaults to `Asia/Kolkata`. APIs continue using UTC absolute instants. React uses central `Intl.DateTimeFormat` utilities and an explicit timezone obtained from `/api/system/config` for presentation. For structured search contracts whose accepted backend boundary is already UTC, React may also convert operator-entered display-zone wall time to UTC through one central, tested IANA-zone conversion utility that round-trips candidate instants and rejects ambiguous/nonexistent wall times. The browser or operating-system timezone is never authoritative, and manual fixed-offset arithmetic is prohibited.

Media-relative offsets and durations (`...OffsetMs`, `...DurationMs`) are timezone-independent and are never converted.

## Query input

Operator-entered date/time filters are wall-clock display-zone values.

For the Phase-1 Track search contract established by Task 14, the public API accepts explicit UTC boundaries. Task 16 therefore converts display-zone wall time to UTC in React using the central explicit-IANA-zone conversion utility described above. The conversion must reject ambiguous/nonexistent wall times and must be invariant to the workstation/browser timezone.

Future APIs may instead accept local date/time plus an explicit IANA timezone and perform conversion in the backend when that boundary is deliberately designed and versioned. Either model is valid only when the timezone is explicit; the frontend must never infer a search boundary from browser timezone.

## Consequences

Deployments can change display timezone without recompiling, historical recording provenance remains stable, and current-time behavior is deterministic in tests. `TimeZoneInfo` is retained behind an interface; NodaTime is intentionally not introduced at this checkpoint.


## Amendment — 14 September 2026

Task 14 shipped the Phase-1 Track search API with UTC-only `fromUtc`/`toUtc` boundaries. Task 16 requires operator entry in the configured display timezone without widening the already-qualified Task-14 backend contract.

This amendment therefore permits one narrowly defined frontend conversion boundary for structured Track search:

- input is a wall-clock value plus the explicit deployment IANA `displayTimeZoneId`;
- conversion is implemented centrally, not per component;
- conversion uses IANA-aware `Intl.DateTimeFormat` round-trip candidate matching;
- nonexistent and ambiguous wall times are rejected rather than guessed;
- UTC-to-wall rehydration also uses the explicit configured zone;
- browser/OS timezone and manual fixed-offset arithmetic remain forbidden;
- API/storage absolute instants remain UTC.

This amendment supersedes the earlier “future query input” assumption that all search wall-time conversion would necessarily occur in the backend.
