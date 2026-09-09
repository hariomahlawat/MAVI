# ADR-004: MAVI Time and Timezone Architecture

**Status:** Accepted  
**Date:** 2026-09-09

## Decision

UTC is MAVI's canonical internal and cross-system time. Absolute instants use `DateTimeOffset`, UTC API timestamps, and PostgreSQL `timestamptz`. Current UTC comes from injected .NET `TimeProvider`.

IANA timezone identifiers describe wall-clock interpretation. A Camera's timezone is authoritative when a source local timestamp is imported. Each VideoAsset snapshots the actual `RecordingTimeZoneId` and `RecordingUtcOffsetMinutes`, so later camera configuration changes cannot reinterpret historical evidence. Invalid and ambiguous wall-clock times are rejected by the central application-facing timezone service.

The operator display timezone is deployment configuration and defaults to `Asia/Kolkata`. APIs continue returning UTC; React converts only for presentation with central `Intl.DateTimeFormat` utilities and an explicit timezone obtained from `/api/system/config`. The browser or operating-system timezone is never authoritative, and manual fixed-offset arithmetic is prohibited.

Media-relative offsets and durations (`...OffsetMs`, `...DurationMs`) are timezone-independent and are never converted.

## Future query input

Operator-entered date/time filters are wall-clock display-zone values. A future search contract will send the local date/time plus its timezone identifier; the backend will convert the boundary to UTC before querying PostgreSQL. The frontend must not use the browser timezone to infer boundaries.

## Consequences

Deployments can change display timezone without recompiling, historical recording provenance remains stable, and current-time behavior is deterministic in tests. `TimeZoneInfo` is retained behind an interface; NodaTime is intentionally not introduced at this checkpoint.
