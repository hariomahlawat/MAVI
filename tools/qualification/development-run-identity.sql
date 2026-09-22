-- Stage-1 exit-gate item 14: the exact runtime identity of the Development real-worker
-- runs — NOT a MAVI runtime component.
--
-- Read-only. Run against the live Development database (mavi_dev):
--
--   psql -h localhost -p 5433 -U <user> -d mavi_dev -f tools/qualification/development-run-identity.sql
--
-- Every completed run already carries the provenance the worker reported and the API
-- validated on completion (runtime_provenance_json). This reads it back rather than
-- restating it: model and checkpoint digests, pipeline profile, runtime profile and
-- variant, the qualification and platform-lock identities, the device actually used
-- and why, the tracker parameters and the MAVI build that produced the evidence.

SELECT
    pr.id                                                        AS processing_run_id,
    va.original_file_name                                        AS video,
    c.code                                                       AS camera,
    pr.status,
    pr.completed_at_utc,
    pr.pipeline_version,
    pr.detector_name, pr.detector_version,
    pr.tracker_name,  pr.tracker_version,
    pr.worker_id,
    -- The whole persisted provenance document, printed rather than picked apart, so the
    -- record is exactly what the API validated and stored: model and checkpoint digests,
    -- pipeline and runtime profiles, runtime variant, platform lock, qualification
    -- identity, configured and actual device and the reason, dependency versions, GPU
    -- and the MAVI build and commit.
    jsonb_pretty(pr.runtime_provenance_json)                     AS runtime_provenance
FROM processing_runs pr
JOIN video_assets va ON va.id = pr.video_asset_id
JOIN cameras c       ON c.id = va.camera_id
WHERE pr.status = 'Completed'
ORDER BY pr.completed_at_utc DESC;
