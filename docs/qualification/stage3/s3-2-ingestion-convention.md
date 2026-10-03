# S3.2 ingestion convention (Development only)

**Scope.** This convention applies to the S3.2 event `2026-10-03-commons`. It defines the `recordingStartLocal` and `timeZoneId` values that the committed ingestion map (`vehicle-subclass-ingestion-map-v1`) gives T9 for the frozen pilot pool. The pool is bound by `docs/qualification/stage3/s3-2-source-pool.sha256`.

**Not capture times.** The source release (Wikimedia Commons file revisions) states at most a capture date, never a trustworthy wall-clock time and zone. The values below are deterministic Development placeholders. They are **not** claimed as the actual capture times or places of any footage, and must never be reported as such.

**Rule.**

1. **Time zone.** Every camera uses `timeZoneId` `UTC`. It has no daylight-saving transitions, so no assigned time can be nonexistent or ambiguous.
2. **Ordering.** Pool members are ordered by their release-relative member path, in ascending ordinal (byte) order. Ordinal `n` starts at 0 for the first member.
3. **Recording start.** Member `n` receives `recordingStartLocal` = `2026-01-15T10:00:00` plus `n` hours, written as `YYYY-MM-DDTHH:MM:SS` with no offset. With 6–10 members, every value falls on 2026-01-15, between 10:00:00 and 19:00:00.
4. **No source facts.** No other property of the footage influences the assigned values.

This document names no member, as Mode B of the S3.2b-2 runbook (§12.2) requires. The member-to-value mapping exists only in the ingestion map, which applies this rule mechanically.
