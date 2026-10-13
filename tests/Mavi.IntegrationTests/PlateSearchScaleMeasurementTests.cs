using System.Diagnostics;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.IntegrationTests.Qualification;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>Runs only when <c>MAVI_PLATE_SEARCH_SCALE_DB</c> names a scratch database (never <c>mavi_test</c>).</summary>
public sealed class PlateSearchScaleFactAttribute : FactAttribute
{
    public const string Variable = "MAVI_PLATE_SEARCH_SCALE_DB";

    public PlateSearchScaleFactAttribute()
    {
        var connection = Environment.GetEnvironmentVariable(Variable);
        if (string.IsNullOrWhiteSpace(connection))
            Skip = $"opt-in Development measurement; set {Variable} to a scratch database's connection string";
        else if (string.Equals(new NpgsqlConnectionStringBuilder(connection).Database, "mavi_test", StringComparison.Ordinal))
            Skip = $"{Variable} must not name the integration-test database";
    }
}

/// <summary>
/// The plan §2.8 budget, measured (Stage 4 PR-4): the first page of a plate-only search over 10^6 Vehicle
/// Tracks and 10^6 <c>plate_track_texts</c> rows, through the real repository, with the plans of every
/// statement it issues. Development evidence on one host, not a qualification or a CI gate; the record is
/// <c>docs/qualification/stage4/2026-10-13-plate-search-at-scale.md</c>.
/// </summary>
/// <remarks>
/// The corpus is synthetic and deterministic: 10 cameras × 100 videos, one completed visible run of 1 000
/// Vehicle Tracks per video spread over 30 days, one Read plate and one Indian-standard-format Track text
/// per Track (36 state codes × 100 districts × 676 series × 10 000 numbers), all under one completed plate
/// analysis per run. Every run is Ready, so coverage counts the whole scope. The questions are frozen in
/// <see cref="Queries"/> before any result is read.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateSearchScaleMeasurementTests(ITestOutputHelper output)
{
    private const int Runs = 1_000;
    private const int TracksPerRun = 1_000;
    private const int WarmUps = 3;
    private const int Samples = 20;
    private const double BudgetMilliseconds = 300;
    private const string Fingerprint = "521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25";

    /// <summary>The frozen query set: broad and selective contains, prefix, exact, and a contains with no match.</summary>
    private static readonly (string Name, TrackPlateQuery Query)[] Queries =
    [
        ("contains-broad KA0", new TrackPlateQuery("KA0", TrackPlateMatch.Contains)),
        ("contains KA01", new TrackPlateQuery("KA01", TrackPlateMatch.Contains)),
        ("contains-digits 1234", new TrackPlateQuery("1234", TrackPlateMatch.Contains)),
        ("prefix MH12", new TrackPlateQuery("MH12", TrackPlateMatch.Prefix)),
        ("exact (an existing text)", new TrackPlateQuery("<first>", TrackPlateMatch.Exact)),
        ("contains-no-match ZZ99ZZ", new TrackPlateQuery("ZZ99ZZ", TrackPlateMatch.Contains)),
    ];

    [PlateSearchScaleFact]
    public async Task TheFirstPageOfAPlateSearchAtTheSeededScaleIsMeasured()
    {
        var connectionString = Environment.GetEnvironmentVariable(PlateSearchScaleFactAttribute.Variable)!;
        await using (var db = CreateContext(connectionString, null))
            await db.Database.MigrateAsync();
        await SeedAsync(connectionString);

        var exact = await ScalarAsync(connectionString, "SELECT normalised_text FROM plate_track_texts ORDER BY track_id LIMIT 1") as string;
        var results = new List<(string Name, double P50, double P95, double Max, int Rows)>();
        foreach (var (name, frozen) in Queries)
        {
            var query = frozen.Text == "<first>" ? frozen with { Text = exact! } : frozen;
            var samples = new List<double>();
            var rows = 0;
            for (var index = 0; index < WarmUps + Samples; index++)
            {
                await using var db = CreateContext(connectionString, null);
                var repository = new TrackSearchRepository(db, TimeProvider.System);
                var stopwatch = Stopwatch.StartNew();
                var page = (await repository.SearchPlatesAsync(Search(query), Fingerprint, null, 51, default)).Page!;
                stopwatch.Stop();
                rows = page.Items.Count;
                if (index >= WarmUps) samples.Add(stopwatch.Elapsed.TotalMilliseconds);
            }

            samples.Sort();
            results.Add((name, Percentile(samples, 0.50), Percentile(samples, 0.95), samples[^1], rows));
        }

        output.WriteLine($"corpus: {Runs * TracksPerRun:N0} Vehicle Tracks, {Runs * TracksPerRun:N0} plate_track_texts rows, {Runs:N0} runs");
        output.WriteLine("query | rows on page | p50 ms | p95 ms | max ms");
        foreach (var result in results)
            output.WriteLine($"{result.Name} | {result.Rows} | {result.P50:F1} | {result.P95:F1} | {result.Max:F1}");

        // The plans of every statement one first page issues, for the selective and the no-match query.
        foreach (var name in new[] { "contains KA01", "contains-no-match ZZ99ZZ" })
        {
            var capture = new SqlCapture();
            await using var db = CreateContext(connectionString, capture);
            await new TrackSearchRepository(db, TimeProvider.System)
                .SearchPlatesAsync(Search(Queries.Single(item => item.Name == name).Query), Fingerprint, null, 51, default);
            foreach (var statement in capture.Statements)
            {
                output.WriteLine($"--- {name}: {statement.Sql.Split('\n')[0].Trim()} …");
                output.WriteLine(await SqlCapture.ExplainAsync(connectionString, statement));
            }
        }

        Assert.All(results, result => Assert.True(result.P95 <= BudgetMilliseconds,
            $"{result.Name}: p95 {result.P95:F1} ms exceeds the {BudgetMilliseconds} ms budget"));
    }

    private static TrackSearchQuery Search(TrackPlateQuery plate) =>
        new(null, null, null, ObjectClass.Vehicle, null, null, null, null, null, 50, Plate: plate);

    private static double Percentile(List<double> sorted, double quantile) =>
        sorted[Math.Clamp((int)Math.Ceiling(quantile * sorted.Count) - 1, 0, sorted.Count - 1)];

    private static MaviDbContext CreateContext(string connectionString, SqlCapture? capture)
    {
        var builder = new DbContextOptionsBuilder<MaviDbContext>().UseNpgsql(connectionString, npgsql => npgsql.UseVector());
        if (capture is not null) builder.AddInterceptors(capture);
        return new MaviDbContext(builder.Options);
    }

    private static async Task<object?> ScalarAsync(string connectionString, string sql)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection) { CommandTimeout = 0 };
        return await command.ExecuteScalarAsync();
    }

    /// <summary>Seeds the corpus once (idempotent on the Track count), then vacuums and analyses.</summary>
    private async Task SeedAsync(string connectionString)
    {
        var existing = Convert.ToInt64(await ScalarAsync(connectionString, "SELECT count(*) FROM plate_track_texts"), System.Globalization.CultureInfo.InvariantCulture);
        if (existing >= Runs * TracksPerRun)
            return;

        var stopwatch = Stopwatch.StartNew();
        string[] steps =
        [
            // Parents: cameras, source artefacts, videos (1 h each), runs, prediction artefacts.
            """
            INSERT INTO cameras (id, code, name, time_zone_id, is_active, created_at_utc, updated_at_utc)
            SELECT md5('camera-' || c)::uuid, 'CAM-SCALE-' || c, 'Scale camera ' || c, 'UTC', true, now(), now()
            FROM generate_series(1, 10) AS c;
            """,
            $$"""
            INSERT INTO artifacts (id, artifact_type, storage_key, mime_type, size_bytes, sha256, created_at_utc)
            SELECT md5('source-' || v)::uuid, 'SourceVideo', 'source/scale/' || v || '.mp4', 'video/mp4', 1, md5('source-' || v) || md5('source-sha-' || v), now()
            FROM generate_series(1, {{Runs}}) AS v;
            """,
            $$"""
            INSERT INTO video_assets (id, camera_id, source_artifact_id, original_file_name, source_type, recording_start_utc, recording_end_utc,
                duration_ms, frame_rate_numerator, frame_rate_denominator, width, height, codec, timestamp_source, timestamp_confidence,
                processing_status, imported_at_utc, recording_time_zone_id, recording_utc_offset_minutes)
            SELECT md5('video-' || v)::uuid, md5('camera-' || (1 + v % 10))::uuid, md5('source-' || v)::uuid, 'scale-' || v || '.mp4', 'UploadedFile',
                timestamptz '2026-09-01 00:00:00+00' + (v - 1) * interval '43 minutes',
                timestamptz '2026-09-01 00:00:00+00' + (v - 1) * interval '43 minutes' + interval '1 hour',
                3600000, 25, 1, 1920, 1080, 'h264', 'Manual', 1.0, 'Processed', now(), 'UTC', 0
            FROM generate_series(1, {{Runs}}) AS v;
            """,
            $$"""
            INSERT INTO processing_runs (id, video_asset_id, status, pipeline_version, configuration_json, queued_at_utc, started_at_utc, completed_at_utc,
                frames_processed, tracks_created, processing_duration_ms, visibility_sequence)
            SELECT md5('run-' || v)::uuid, md5('video-' || v)::uuid, 'Completed', 'phase1-v1', '{}', now(), now(), now(), 90000, {{TracksPerRun}}, 1000,
                nextval('processing_visibility_sequence')
            FROM generate_series(1, {{Runs}}) AS v ORDER BY v;
            """,
            $$"""
            INSERT INTO artifacts (id, artifact_type, storage_key, mime_type, size_bytes, sha256, created_at_utc)
            SELECT md5('predictions-' || v)::uuid, 'PlatePredictions', 'evidence/plates/scale-' || v || '.json', 'application/json', 1,
                md5('predictions-' || v) || md5('predictions-sha-' || v), now()
            FROM generate_series(1, {{Runs}}) AS v;
            """,
            // 10^6 Vehicle Tracks, 2.592 s apart across the 30 days, and one Representative Observation each.
            $$"""
            INSERT INTO tracks (id, processing_run_id, video_asset_id, local_track_number, object_class, start_offset_ms, end_offset_ms,
                start_timestamp_utc, end_timestamp_utc, duration_ms, detection_count, mean_confidence, max_confidence, review_status, created_at_utc)
            SELECT uuidv7(), md5('run-' || (1 + (i - 1) / {{TracksPerRun}}))::uuid, md5('video-' || (1 + (i - 1) / {{TracksPerRun}}))::uuid,
                1 + (i - 1) % {{TracksPerRun}}, 'Vehicle', 0, 4000,
                timestamptz '2026-09-01 00:00:00+00' + i * interval '2592 milliseconds',
                timestamptz '2026-09-01 00:00:04+00' + i * interval '2592 milliseconds',
                4000, 40, 0.8, 0.9, 'Unreviewed', now()
            FROM generate_series(1, {{Runs * TracksPerRun}}) AS i;
            """,
            """
            INSERT INTO observations (id, track_id, observation_type, source_frame_number, video_offset_ms, timestamp_utc, bounding_box_x, bounding_box_y,
                bounding_box_width, bounding_box_height, confidence, quality_score, created_at_utc, evidence_rank, selection_score)
            SELECT uuidv7(), t.id, 'Representative', 10, 400, t.start_timestamp_utc, 0.1, 0.1, 0.2, 0.2, 0.8, 0.7, now(), 0, 0.7
            FROM tracks t;
            """,
            "UPDATE tracks t SET representative_observation_id = o.id FROM observations o WHERE o.track_id = t.id;",
            // One completed analysis of the identity per run, then one Read plate and one Track text per Track.
            $$"""
            INSERT INTO plate_analyses (id, processing_run_id, identity_fingerprint, pipeline_id, pipeline_version, predictions_schema_version,
                normalisation_id, normalisation_sha256, summary_policy_id, summary_policy_version, summary_policy_sha256, capabilities_canonical,
                parameters_sha256, status, attempt_count, queued_at_utc, first_claimed_at_utc, completed_at_utc, completion_digest,
                prediction_artifact_id, provenance_json, tracks_analysed, tracks_unavailable, plate_observations_read, plate_observations_unreadable,
                visibility_sequence)
            SELECT md5('analysis-' || v)::uuid, md5('run-' || v)::uuid, '{{Fingerprint}}', 'plates-fixture', '1.0.0', 'mavi-plate-predictions-v1',
                'mavi-plate-normalisation-v1', '6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935', 'plate-track-text-rank0', '1.0.0',
                '1fb72dd2ce254a2190cd19290bc7304342d16bdacc417a03e7589cd202eecd1f',
                '[{"capabilityId":"ocr","modelPackId":"mavi-model-v2-{{new string('3', 64)}}"},{"capabilityId":"plate-detector","modelPackId":"mavi-model-v2-{{new string('4', 64)}}"}]',
                'd19bf0705c880fdf49895f99ba95e5bda61843222d1111764173e877b0128e02', 'Completed', 1, now(), now(), now(), md5('digest-' || v) || md5('d2-' || v),
                md5('predictions-' || v)::uuid, '{}', {{TracksPerRun}}, 0, {{TracksPerRun}}, 0, nextval('processing_visibility_sequence')
            FROM generate_series(1, {{Runs}}) AS v ORDER BY v;
            """,
            """
            INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, plate_observation_count, distinct_text_count)
            SELECT a.id, t.id, 'Analysed', 1, 1 FROM tracks t JOIN plate_analyses a ON a.processing_run_id = t.processing_run_id;
            """,
            """
            INSERT INTO plate_observations (id, analysis_id, track_id, source_observation_id, plate_index, box_x, box_y, box_width, box_height,
                crop_width, crop_height, detector_confidence, outcome)
            SELECT uuidv7(), a.id, t.id, t.representative_observation_id, 0, 150, 240, 118, 30, 412, 330, 0.95, 'Read'
            FROM tracks t JOIN plate_analyses a ON a.processing_run_id = t.processing_run_id;
            """,
            """
            INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id)
            SELECT p.analysis_id, p.track_id,
                (ARRAY['KA','MH','DL','TN','AP','TS','GJ','RJ','UP','MP','WB','KL','PB','HR','BR','OD','CG','JH','UK','HP','JK','GA','AS','TR',
                       'ML','MN','MZ','NL','AR','SK','CH','PY','AN','DN','LD','LA'])[1 + (h.h1 % 36)::int]
                || lpad((h.h1 / 36 % 100)::text, 2, '0') || chr(65 + (h.h2 % 26)::int) || chr(65 + (h.h2 / 26 % 26)::int)
                || lpad((h.h2 / 676 % 10000)::text, 4, '0'),
                1, 0.9, p.id
            FROM plate_observations p
            CROSS JOIN LATERAL (SELECT ('x' || substr(md5(p.track_id::text), 1, 8))::bit(32)::bigint AS h1,
                                       ('x' || substr(md5(p.track_id::text), 9, 8))::bit(32)::bigint AS h2) AS h;
            """,
        ];

        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        foreach (var step in steps)
        {
            await using var command = new NpgsqlCommand(step, connection) { CommandTimeout = 0 };
            await command.ExecuteNonQueryAsync();
        }

        await using (var vacuum = new NpgsqlCommand("VACUUM ANALYZE", connection) { CommandTimeout = 0 })
            await vacuum.ExecuteNonQueryAsync();
        output.WriteLine($"seeded in {stopwatch.Elapsed.TotalSeconds:F0} s");
    }
}
