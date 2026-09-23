-- Stage-1 exit-gate item 4(a): analytical-unit duration and rows written for the
-- Development corpus — NOT a MAVI runtime component.
--
-- Read-only. Run against the live Development database the real-worker acceptance
-- used (mavi_dev), after the units under test have completed:
--
--   psql -h 127.0.0.1 -p 55433 -U <user> -d mavi_dev -f tools/qualification/development-unit-record.sql
--
-- One row per analytical unit: its identity, attempt, the duration of its final
-- attempt (claim to fenced commit), analysed/unavailable Track counts, and the rows
-- it wrote to each fact table. Nothing is inferred; every figure is read from the
-- unit and the facts that reference it.

SELECT
    sa.id                                                     AS analysis_id,
    sa.processing_run_id,
    r.revision_number                                         AS scene_revision,
    sa.algorithm_version,
    sa.status,
    sa.attempt_count,
    sa.started_at_utc,
    sa.completed_at_utc,
    round(extract(epoch FROM (sa.completed_at_utc - sa.started_at_utc)) * 1000)::bigint
                                                              AS final_attempt_duration_ms,
    sa.analysed_track_count,
    sa.unavailable_track_count,
    (SELECT count(*) FROM track_analysis_outcomes o WHERE o.analysis_id = sa.id) AS outcomes,
    (SELECT count(*) FROM track_zone_visits v       WHERE v.analysis_id = sa.id) AS zone_visits,
    (SELECT count(*) FROM track_zone_summaries s    WHERE s.analysis_id = sa.id) AS zone_summaries,
    (SELECT count(*) FROM track_line_crossings c    WHERE c.analysis_id = sa.id) AS line_crossings,
    (SELECT count(*) FROM track_motion_summaries m  WHERE m.analysis_id = sa.id) AS motion_summaries,
    (SELECT coalesce(sum(o.sample_count), 0) FROM track_analysis_outcomes o WHERE o.analysis_id = sa.id)
                                                              AS trajectory_samples
FROM scene_analyses sa
JOIN scene_configuration_revisions r ON r.id = sa.revision_id
ORDER BY sa.completed_at_utc NULLS LAST, sa.queued_at_utc;
