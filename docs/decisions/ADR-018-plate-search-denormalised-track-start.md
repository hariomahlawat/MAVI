# ADR-018: Plate search reads candidates by a denormalised Track start time

**Status:** Accepted owner decision for Stage 4 PR-4, 2026-10-15 (option (c2) of the PR-4 options packet; implemented together with ADR-019).

**Date:** 2026-10-15

**Related:** ADR-013 implementation amendment 2026-10-13 (Stage 4 plate search), items 16–19; plan `docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` §2.7, §2.8; evidence `docs/qualification/stage4/2026-10-13-plate-search-at-scale.md`; ADR-019.

## Context

A plate search returns the Tracks of the base chain that match the plate predicate, ordered `StartTimestampUtc DESC, Id DESC`, one page at a time. The predicate is an EXISTS over `plate_track_texts` for a visible analysis of the pinned identity of the Track's own run (ADR-013 item 16). The page order lives on `tracks`. The text match lives on `plate_track_texts`, which knows nothing of time. So the first page design had to choose one of two indirect paths:

- walk the scope's Tracks in page order and test each batch against the texts;
- read every matching text and sort its Tracks.

On the frozen skewed corpus (`mavi-plate-search-skewed-v1`, 10^6 Vehicle Tracks), the walk missed the plan §2.8 budget of p95 ≤ 300 ms:

- broad state-code texts installation-wide took 374–989 ms;
- the declared stress probe, a text dense only in old data, took about 63 s, because the walk's cost grows with the scope.

The options packet measured four candidate designs, each on a quiet host. Option (c2) met the budget on every budgeted query, and with ADR-019 its worst p95 was 154 ms. It also brought the stress probe down to 33 ms, because its cost is bounded by the number of matching texts, not by the scope.

## Decision

1. **The column.** `plate_track_texts` gains `track_start_timestamp_utc timestamptz NOT NULL`: a copy of its Track's `tracks.start_timestamp_utc`. It is a search accelerator only. It is never an independent semantic authority, and nothing outside the plate search reads it. EF maps it as a store-generated shadow property (`PlateSearchIndexConfiguration`) that the application never writes.

2. **Maintained only by the database, atomically.** Migration `20261015120000_AddPlateTextTrackStart` creates two triggers:
   - A BEFORE INSERT OR UPDATE row trigger on `plate_track_texts`, `tr_plate_track_texts_track_start`, derives the value from `tracks` inside the writing statement and replaces any value supplied. PR-3's completion path is unchanged in code: its `COPY` publication does not name the column.
   - An AFTER UPDATE OF `start_timestamp_utc` row trigger on `tracks`, `tr_tracks_plate_text_track_start`, carries a changed start time to that Track's texts in the same statement. It finds them through `plate_track_outcomes`' Track index and the texts' primary key.

   No committed path can leave a text with a missing value, since the column is NOT NULL. Nor can any committed path leave a text with a value other than its Track's, short of disabling triggers.

3. **The run invariant is enforced.** The same insert trigger refuses a text whose Track is not of its analysis's run (`check_violation`, constraint name `tr_plate_track_texts_track_start`). This is PR-3's completion invariant: its lease lists exactly the run's Tracks. Until now it was enforced only by the application. The candidate read relies on it, as item 6 explains.

4. **Backfill and atomicity.** The migration does all of the following in one transaction:
   - adds the column, which holds an ACCESS EXCLUSIVE lock on `plate_track_texts` until commit, so no text can be written in between;
   - backfills the column from `tracks`;
   - fails if any text has no Track or names a Track of another run;
   - sets NOT NULL;
   - creates the triggers.

   Down drops the triggers, their functions and the column. The column is derived, so the migration is reversible without losing a fact, and Up recomputes it.

5. **The candidate read.** For each page, `TrackSearchRepository.PlatePageAsync` does the following:
   - It reads the runs of the scope that hold a visible analysis of the pinned identity. If there are none, nothing matches.
   - It reads candidate texts in batches of 256, doubling to 4 096. Each batch is one statement:
     - a materialised CTE computes the text match once, served by the trigram index for contains or the pattern b-tree for prefix and exact;
     - an optional keyset bound `(track_start_timestamp_utc, track_id) < cursor` applies;
     - the CTE is joined to the visible analyses of the pinned identity in those runs;
     - the rows are ordered `track_start_timestamp_utc DESC, track_id DESC` with a `LIMIT`.
   - Each batch's Tracks go through the page's own query, restricted to them. That query applies every other predicate, the keyset and the order, all over `tracks` itself.
   - It stops when the page is full or the candidates are exhausted.

   The v4 HMAC cursor, its keyset `(StartTimestampUtc, Id)`, its pins and the wire contracts frozen at `0150627b` are unchanged.

6. **Why the result is exactly the pre-optimisation result.**
   - Membership is decided by three things: the text, its analysis (identity, status, visibility within the snapshot, run in scope) and the base chain. The denormalised column decides none of them.
   - Order and keyset are applied by the base chain over `tracks`.
   - The column only chooses which candidates a batch holds. It equals the Track's start (item 2), and a text's Track is of its analysis's run (item 3). Therefore:
     - every matching Track strictly between the keyset and a batch's last candidate is in that batch;
     - consecutive batches partition the page order;
     - the next batch resumes strictly after the last candidate.
   - A Track with several matching texts is one candidate per text and one row.

   Tests pin this against the plan §2.8 correlated-EXISTS formulation evaluated as LINQ, at the snapshot (`TrackPlateSearchRepositoryTests.TheCandidateReadEqualsThePreOptimisationPredicate`, `EveryPageStrategyReturnsExactlyThePredicateInPageOrder`).

7. **Drift is detectable.** `SELECT count(*) FROM plate_track_texts x JOIN tracks t ON t.id = x.track_id WHERE x.track_start_timestamp_utc IS DISTINCT FROM t.start_timestamp_utc` must be 0. The following check it:
   - the repository tests, after inserts, updates of texts and updates of Track starts;
   - PR-3's `PlateCompletionTimingTests`, after a real `COPY` completion;
   - the scale measurement, after the migration on the 10^6 corpus.

## Consequences

### Positive

- Page cost is bounded by the matching texts and the page, not by the scope.
- The stress probe that took about 63 s with the walk takes tens of milliseconds.
- The walk, the sparse path and their density probe are removed: there is one candidate path instead of three.
- The run invariant that PR-3 enforced in code is now also enforced by the database.

### Costs (the trade-off accepted)

- **A denormalised copy of a fact.**
  - Its correctness rests on two triggers and on nobody disabling them (`session_replication_role = replica` or `ALTER TABLE … DISABLE TRIGGER` would).
  - The drift query in item 7 is the check for that.
  - A change of a Track's run is not re-validated against existing texts: Track run and start are immutable in the domain (`Track.Create`).
- **Write cost.**
  - Each text insert costs two primary-key lookups (`tracks`, `plate_analyses`).
  - On the prototype this was within noise at PR-3's worst shape (10 000 Tracks × 4 texts, ≈ +0.5 s on ≈ 9–10 s completions, budget 15 s).
  - The candidate head's interleaved measurement is in the evidence record.
- **Migration cost.**
  - The backfill rewrites every text row, ≈ 38 s at 10^6 rows on the Development host in the prototype, under an exclusive lock on `plate_track_texts`.
  - It leaves dead row versions to autovacuum. Run `VACUUM (ANALYZE) plate_track_texts` after the upgrade to reclaim them at once.
- **Statement cost per batch.**
  - A batch recomputes the full text match, so a broad text costs about 100 ms per batch at 10^6 rows (`contains KA0`: 69 k matches).
  - A page whose base-chain filters reject most candidates, such as an old time window under a common text, reads several batches. This case is not in the frozen query set and is recorded as a limit, not measured.
  - A window's upper bound could be pushed into the candidate statement as `track_start_timestamp_utc < toUtc`. That would be a later, separately measured change.
- **Raw SQL.** One statement is raw SQL, because the materialised CTE is not expressible in LINQ. Every value is a bound parameter.

## Alternatives rejected

- **(a2)**, a bounded sparse statement tried after any unfilled first batch.
  - It met the budget only together with ADR-019, at a worst p95 of 262 ms.
  - It left the stress probe at about 40 s, so its cost still grew with the scope.
  - The owner rejected it in favour of (c2).
- **(c)**, the denormalised key without a materialised match.
  - The planner re-ran the trigram bitmap once per analysis.
  - Q01 took 4.8 s.
- **Application-written column.**
  - PR-3's completion would have to write the column, so its code would change.
  - Every other write path (tests, tools, repair) could then omit it or write it wrongly.
  - A trigger is the only writer that cannot be bypassed by an ordinary write.
- **A generated column.** PostgreSQL generated columns cannot reference another table.
