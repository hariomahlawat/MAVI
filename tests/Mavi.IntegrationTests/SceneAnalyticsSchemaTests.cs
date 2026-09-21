using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// What PostgreSQL itself enforces about the analytics schema, executed against a real
/// server. Every guarantee here is one the application must not be the only thing
/// holding: a second host, a repair script or a future phase writes through the same
/// tables.
/// </summary>
/// <remarks>
/// The domain entities refuse most of these shapes before they reach the database, so
/// the invalid cases are written as raw SQL on purpose. A test that can only fail by
/// going through the guard it is meant to back up proves nothing about the database.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsSchemaTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    // Identity
    /// <summary>
    /// Re-analysis and explicit retry both insert and let the constraint arbitrate
    /// rather than reading first, so this uniqueness is what makes them safe under
    /// concurrency.
    /// </summary>
    [Fact]
    public async Task TheUnitIdentityIsRejectedTwice()
    {
        var world = await FreshWorldAsync();

        world.Db.SceneAnalyses.Add(Unit(world));
        await world.Db.SaveChangesAsync();

        await using var second = fixture.CreateDbContext();
        second.SceneAnalyses.Add(Unit(world));

        await AssertUniqueViolationAsync(() => second.SaveChangesAsync(), "ux_scene_analyses_identity");
    }

    /// <summary>A different algorithm version is a different unit, not a duplicate.</summary>
    [Fact]
    public async Task TheSameRunAndRevisionMayBeAnalysedByAnotherAlgorithmVersion()
    {
        var world = await FreshWorldAsync();

        world.Db.SceneAnalyses.Add(Unit(world));
        world.Db.SceneAnalyses.Add(Unit(world, algorithmVersion: "scene-analytics-v2"));
        await world.Db.SaveChangesAsync();

        Assert.Equal(2, await world.Db.SceneAnalyses.CountAsync());
    }

    [Fact]
    public async Task ZoneVisitsAreUniquePerUnitTrackZoneAndIndex()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        world.Db.TrackZoneVisits.Add(Visit(unit.Id, world.TrackId, world.ZoneId, 0));
        await world.Db.SaveChangesAsync();

        await using var second = fixture.CreateDbContext();
        second.TrackZoneVisits.Add(Visit(unit.Id, world.TrackId, world.ZoneId, 0));

        await AssertUniqueViolationAsync(() => second.SaveChangesAsync(), "ux_track_zone_visits_identity");
    }

    [Fact]
    public async Task LineCrossingsAreUniquePerUnitTrackLineAndIndex()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        world.Db.TrackLineCrossings.Add(Crossing(unit.Id, world.TrackId, world.LineId, 0));
        await world.Db.SaveChangesAsync();

        await using var second = fixture.CreateDbContext();
        second.TrackLineCrossings.Add(Crossing(unit.Id, world.TrackId, world.LineId, 0));

        await AssertUniqueViolationAsync(() => second.SaveChangesAsync(), "ux_track_line_crossings_identity");
    }

    /// <summary>
    /// One outcome per Track per unit is the primary key, so a second write for the
    /// same pair is refused by the table rather than by a repository.
    /// </summary>
    [Fact]
    public async Task OneOutcomePerTrackPerUnitIsEnforcedByThePrimaryKey()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        world.Db.TrackAnalysisOutcomes.Add(
            TrackAnalysisOutcome.Unavailable(unit.Id, world.TrackId, SceneAnalyticsErrorCodes.TrajectoryMissing));
        await world.Db.SaveChangesAsync();

        await AssertUniqueViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_analysis_outcomes
                  (analysis_id, track_id, outcome, reason, reference_point, sample_count, gap_count, gap_total_ms)
                VALUES (@analysis, @track, 'Unavailable', 'trajectory_missing', NULL, 0, 0, 0);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId)),
            "PK_track_analysis_outcomes");
    }

    [Fact]
    public async Task OneZoneSummaryPerTrackPerZonePerUnitIsEnforcedByThePrimaryKey()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        world.Db.TrackZoneSummaries.Add(
            TrackZoneSummary.Create(unit.Id, world.TrackId, world.ZoneId, 0, 0, null, null, false, 45, 0));
        await world.Db.SaveChangesAsync();

        await AssertUniqueViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_zone_summaries
                  (analysis_id, track_id, zone_id, visit_count, total_dwell_ms,
                   first_entry_timestamp_utc, last_exit_timestamp_utc,
                   loitering, loitering_threshold_seconds, loitering_dwell_ms)
                VALUES (@analysis, @track, @zone, 0, 0, NULL, NULL, false, 45, 0);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId),
                ("zone", world.ZoneId)),
            "PK_track_zone_summaries");
    }

    [Fact]
    public async Task OneMotionSummaryPerTrackPerUnitIsEnforcedByThePrimaryKey()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        world.Db.TrackMotionSummaries.Add(
            TrackMotionSummary.Create(unit.Id, world.TrackId, "NE", 0.4, 0.01, 0, 0, [], []));
        await world.Db.SaveChangesAsync();

        await AssertUniqueViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_motion_summaries
                  (analysis_id, track_id, heading, path_length_normalised, mean_displacement_rate,
                   longest_stationary_ms, total_stationary_ms, stationary_intervals, stationary_zone_ids)
                VALUES (@analysis, @track, 'NE', 0.4, 0.01, 0, 0, '[]'::jsonb, '[]'::jsonb);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId)),
            "PK_track_motion_summaries");
    }

    // Ownership of facts
    /// <summary>
    /// A unit owns its facts. Nothing in Slice 3 deletes a unit, but if one ever is,
    /// its facts must not outlive the identity that gives them meaning.
    /// </summary>
    [Fact]
    public async Task DeletingAUnitTakesItsFactsWithIt()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);
        await PersistEveryFactKindAsync(world, unit.Id);

        await ExecuteAsync("DELETE FROM scene_analyses WHERE id = @analysis;", ("analysis", unit.Id));

        await using var reader = fixture.CreateDbContext();
        Assert.Empty(await reader.TrackAnalysisOutcomes.ToListAsync());
        Assert.Empty(await reader.TrackZoneVisits.ToListAsync());
        Assert.Empty(await reader.TrackZoneSummaries.ToListAsync());
        Assert.Empty(await reader.TrackLineCrossings.ToListAsync());
        Assert.Empty(await reader.TrackMotionSummaries.ToListAsync());
    }

    /// <summary>
    /// The reverse must not hold. Derived analytics may never become a route by which
    /// sealed detector evidence is deleted, so the Track reference restricts.
    /// </summary>
    [Fact]
    public async Task AFactRefusesToLetItsTrackBeDeleted()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);
        await PersistEveryFactKindAsync(world, unit.Id);

        var exception = await Assert.ThrowsAsync<PostgresException>(
            () => ExecuteAsync("DELETE FROM tracks WHERE id = @track;", ("track", world.TrackId)));

        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, exception.SqlState);
    }

    /// <summary>The unit refuses to let the run or the revision it is pinned to vanish.</summary>
    [Fact]
    public async Task AUnitRefusesToLetItsRunOrRevisionBeDeleted()
    {
        var world = await FreshWorldAsync();
        await PersistUnitAsync(world);

        var run = await Assert.ThrowsAsync<PostgresException>(
            () => ExecuteAsync("DELETE FROM processing_runs WHERE id = @run;", ("run", world.RunId)));
        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, run.SqlState);

        var revision = await Assert.ThrowsAsync<PostgresException>(
            () => ExecuteAsync(
                "DELETE FROM scene_configuration_revisions WHERE id = @revision;",
                ("revision", world.RevisionId)));
        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, revision.SqlState);
    }

    // Value constraints
    [Fact]
    public async Task ANegativeDwellIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => InsertVisitAsync(world, unit.Id, dwellMs: -1),
            "ck_track_zone_visits_dwell");
    }

    [Fact]
    public async Task AVisitThatExitsBeforeItEntersIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => InsertVisitAsync(world, unit.Id, exitTimestampUtc: Now.AddSeconds(-1)),
            "ck_track_zone_visits_timestamps");

        await AssertCheckViolationAsync(
            () => InsertVisitAsync(world, unit.Id, entryOffsetMs: 5_000, exitOffsetMs: 4_999),
            "ck_track_zone_visits_offsets");
    }

    [Theory]
    [InlineData(-0.01, 0.5)]
    [InlineData(1.01, 0.5)]
    [InlineData(0.5, -0.01)]
    [InlineData(0.5, 1.01)]
    public async Task ACrossingPointOutsideTheNormalisedFrameIsRejected(double x, double y)
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_line_crossings
                  (id, analysis_id, track_id, line_id, crossing_index, offset_ms, timestamp_utc,
                   direction, point_x, point_y)
                VALUES (gen_random_uuid(), @analysis, @track, @line, 0, 0, @at, 'AToB', @x, @y);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId),
                ("line", world.LineId),
                ("at", Now),
                ("x", x),
                ("y", y)),
            "ck_track_line_crossings_point");
    }

    [Fact]
    public async Task AValueOutsideAClosedVocabularyIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => InsertVisitAsync(world, unit.Id, entryHeading: "NNE"),
            "ck_track_zone_visits_headings");

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_motion_summaries
                  (analysis_id, track_id, heading, path_length_normalised, mean_displacement_rate,
                   longest_stationary_ms, total_stationary_ms, stationary_intervals, stationary_zone_ids)
                VALUES (@analysis, @track, 'north', 0.4, 0.01, 0, 0, '[]'::jsonb, '[]'::jsonb);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId)),
            "ck_track_motion_summaries_heading");
    }

    /// <summary>
    /// An "analysed" Track carries a reference point and no reason; an "unavailable"
    /// one carries a reason and derived nothing. A row that says both, or neither, is
    /// not a fact about anything.
    /// </summary>
    [Fact]
    public async Task AnOutcomeThatClaimsBothOrNeitherShapeIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => InsertOutcomeAsync(unit.Id, world.TrackId, "Analysed", reason: "trajectory_missing"),
            "ck_track_analysis_outcomes_shape");

        await AssertCheckViolationAsync(
            () => InsertOutcomeAsync(unit.Id, world.TrackId, "Unavailable", referencePoint: "bbox-centre"),
            "ck_track_analysis_outcomes_shape");

        await AssertCheckViolationAsync(
            () => InsertOutcomeAsync(unit.Id, world.TrackId, "Unavailable", reason: "trajectory_missing", sampleCount: 7),
            "ck_track_analysis_outcomes_shape");
    }

    // Claim token and visibility
    /// <summary>
    /// The column holds a SHA-256 of the opaque claim token. A value of the wrong
    /// length is not a hash, and storing one would mean the plaintext token had leaked
    /// into the row.
    /// </summary>
    [Fact]
    public async Task AClaimTokenHashOfTheWrongLengthIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                "UPDATE scene_analyses SET claim_token_hash = '\\x00'::bytea WHERE id = @analysis;",
                ("analysis", unit.Id)),
            "ck_scene_analyses_claim_token_hash");

        // 32 bytes is accepted, and NULL — no current owner — stays legal.
        await ExecuteAsync(
            "UPDATE scene_analyses SET claim_token_hash = sha256('token'::bytea) WHERE id = @analysis;",
            ("analysis", unit.Id));
        await ExecuteAsync(
            "UPDATE scene_analyses SET claim_token_hash = NULL WHERE id = @analysis;",
            ("analysis", unit.Id));
    }

    [Fact]
    public async Task TheVisibilitySequenceIsUniqueOnceAllocated()
    {
        var world = await FreshWorldAsync();
        var first = await PersistUnitAsync(world);
        var second = await PersistUnitAsync(world, algorithmVersion: "scene-analytics-v2");

        await ExecuteAsync(
            "UPDATE scene_analyses SET visibility_sequence = 41 WHERE id = @analysis;",
            ("analysis", first.Id));

        await AssertUniqueViolationAsync(
            () => ExecuteAsync(
                "UPDATE scene_analyses SET visibility_sequence = 41 WHERE id = @analysis;",
                ("analysis", second.Id)),
            "ux_scene_analyses_visibility_sequence");
    }

    /// <summary>
    /// Every unit that has not completed has no sequence, so the uniqueness must be
    /// partial or the second queued unit could never be inserted.
    /// </summary>
    [Fact]
    public async Task ManyUnitsMayHaveNoVisibilitySequenceAtOnce()
    {
        var world = await FreshWorldAsync();

        world.Db.SceneAnalyses.Add(Unit(world));
        world.Db.SceneAnalyses.Add(Unit(world, algorithmVersion: "scene-analytics-v2"));
        world.Db.SceneAnalyses.Add(Unit(world, algorithmVersion: "scene-analytics-v3"));
        await world.Db.SaveChangesAsync();

        Assert.Equal(3, await world.Db.SceneAnalyses.CountAsync(x => x.VisibilitySequence == null));
    }

    [Fact]
    public async Task ANonCanonicalParametersDigestIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                $"UPDATE scene_analyses SET parameters_sha256 = '{new string('A', 64)}' WHERE id = @analysis;",
                ("analysis", unit.Id)),
            "ck_scene_analyses_parameters_sha256");
    }

    [Fact]
    public async Task AStatusOutsideTheLifecycleIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                "UPDATE scene_analyses SET status = 'Cancelled' WHERE id = @analysis;",
                ("analysis", unit.Id)),
            "ck_scene_analyses_status");
    }

    // Round trip
    [Fact]
    public async Task EveryFactKindRoundTripsThroughTheSchema()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);
        await PersistEveryFactKindAsync(world, unit.Id);

        await using var reader = fixture.CreateDbContext();

        var outcome = await reader.TrackAnalysisOutcomes.SingleAsync();
        Assert.Equal(TrackAnalysisOutcomeKind.Analysed, outcome.Outcome);
        Assert.Equal("bbox-centre", outcome.ReferencePoint);
        Assert.Null(outcome.Reason);

        var visit = await reader.TrackZoneVisits.SingleAsync();
        Assert.Equal(world.ZoneId, visit.ZoneId);
        Assert.Equal("NE", visit.EntryHeading);
        Assert.Equal(4_000, visit.DwellMs);

        var summary = await reader.TrackZoneSummaries.SingleAsync();
        Assert.Equal(1, summary.VisitCount);
        Assert.True(summary.Loitering);

        var crossing = await reader.TrackLineCrossings.SingleAsync();
        Assert.Equal("AToB", crossing.Direction);
        Assert.Equal(0.25, crossing.PointX);

        var motion = await reader.TrackMotionSummaries.SingleAsync();
        Assert.Equal("NE", motion.Heading);
        Assert.Equal([world.ZoneId], motion.StationaryZoneIds);
        var interval = Assert.Single(motion.StationaryIntervals);
        Assert.Equal(1_000, interval.StartOffsetMs);
        Assert.Equal(3_500, interval.EndOffsetMs);
    }

    /// <summary>
    /// The jsonb columns are written by hand rather than by a general object
    /// serializer, so the stored shape is asserted as text, not only as a round trip.
    /// </summary>
    [Fact]
    public async Task MotionCollectionsAreStoredAsCanonicalJsonArrays()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);
        world.Db.TrackMotionSummaries.Add(TrackMotionSummary.Create(
            unit.Id,
            world.TrackId,
            "NE",
            0.42,
            0.01,
            2_500,
            2_500,
            [new StationaryInterval(1_000, 3_500)],
            [world.ZoneId]));
        await world.Db.SaveChangesAsync();

        Assert.Equal(
            "array",
            await ScalarAsync("SELECT jsonb_typeof(stationary_intervals) FROM track_motion_summaries;"));
        Assert.Equal(
            // Compact start/end pairs, not named members: the writer is hand-written so
            // that the stored bytes cannot change because a serializer default did.
            "[[1000, 3500]]",
            await ScalarAsync("SELECT stationary_intervals::text FROM track_motion_summaries;"));
        Assert.Equal(
            $"[\"{world.ZoneId:D}\"]",
            await ScalarAsync("SELECT stationary_zone_ids::text FROM track_motion_summaries;"));
    }

    [Fact]
    public async Task ANonArrayInTheMotionJsonColumnsIsRejected()
    {
        var world = await FreshWorldAsync();
        var unit = await PersistUnitAsync(world);

        await AssertCheckViolationAsync(
            () => ExecuteAsync(
                """
                INSERT INTO track_motion_summaries
                  (analysis_id, track_id, heading, path_length_normalised, mean_displacement_rate,
                   longest_stationary_ms, total_stationary_ms, stationary_intervals, stationary_zone_ids)
                VALUES (@analysis, @track, 'NE', 0.4, 0.01, 0, 0, '{}'::jsonb, '[]'::jsonb);
                """,
                ("analysis", unit.Id),
                ("track", world.TrackId)),
            "ck_track_motion_summaries_json_shape");
    }

    // Schema shape
    [Fact]
    public async Task TheMigrationCreatesEveryAnalyticsTableAndItsIndexes()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        string[] tables =
        [
            "scene_analyses",
            "track_analysis_outcomes",
            "track_zone_visits",
            "track_zone_summaries",
            "track_line_crossings",
            "track_motion_summaries",
        ];
        foreach (var table in tables)
        {
            Assert.Equal(table, await ScalarAsync($"SELECT to_regclass('public.{table}')::text;"));
        }

        string[] indexes =
        [
            "ux_scene_analyses_identity",
            "ix_scene_analyses_run",
            "ix_scene_analyses_pending",
            "ux_scene_analyses_visibility_sequence",
            "ux_track_zone_visits_identity",
            "ix_track_zone_visits_analysis_track",
            "ix_track_zone_visits_zone_entry",
            "ux_track_line_crossings_identity",
            "ix_track_line_crossings_line_time_direction",
            "ix_track_zone_summaries_zone_dwell",
            "ix_track_zone_summaries_zone_loitering",
            "ix_track_motion_summaries_longest_stationary",
        ];
        foreach (var index in indexes)
        {
            Assert.Equal(
                index,
                await ScalarAsync($"SELECT indexname FROM pg_indexes WHERE indexname = '{index}';"));
        }
    }

    /// <summary>
    /// The partial indexes must actually be partial in the database. A planner that
    /// sees a full index instead is a different cost model, and a filter silently
    /// dropped in a future migration would not otherwise fail anything.
    /// </summary>
    [Fact]
    public async Task ThePartialIndexesKeepTheirFilters()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        Assert.Contains(
            "WHERE ((status)::text = ANY",
            await IndexDefinitionAsync("ix_scene_analyses_pending"));
        Assert.Contains(
            "WHERE (visibility_sequence IS NOT NULL)",
            await IndexDefinitionAsync("ux_scene_analyses_visibility_sequence"));
        Assert.Contains(
            "WHERE loitering",
            await IndexDefinitionAsync("ix_track_zone_summaries_zone_loitering"));
    }

    /// <summary>
    /// Nothing in the database decides ownership from the lease clock: no trigger, no
    /// rule, no generated column. ADR-011 decision 4 reserves that to the reconciler's
    /// two fenced transitions, taken under a row lock.
    /// </summary>
    [Fact]
    public async Task NoTriggerOrGeneratedColumnInterpretsTheLeaseClock()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        Assert.Equal(
            0L,
            await ScalarAsync(
                """
                SELECT count(*) FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                WHERE NOT t.tgisinternal
                  AND c.relname IN ('scene_analyses', 'track_analysis_outcomes', 'track_zone_visits',
                                    'track_zone_summaries', 'track_line_crossings', 'track_motion_summaries');
                """));

        Assert.Equal(
            0L,
            await ScalarAsync(
                """
                SELECT count(*) FROM information_schema.columns
                WHERE table_name = 'scene_analyses'
                  AND (is_generated <> 'NEVER' OR column_default IS NOT NULL);
                """));

        // Nor in any index predicate: a partial index keyed on the lease column would
        // make the claimer's own working-set query decide ownership, which is the same
        // defect in a shape that reads like an optimisation. (A predicate calling now()
        // is refused by PostgreSQL itself, which is why only the column is checked.)
        Assert.Equal(
            0L,
            await ScalarAsync(
                """
                SELECT count(*) FROM pg_indexes
                WHERE tablename = 'scene_analyses'
                  AND indexdef LIKE '%lease_expires_at_utc%';
                """));

        // The lease clock appears in no constraint expression at all.
        Assert.Equal(
            0L,
            await ScalarAsync(
                """
                SELECT count(*) FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                WHERE c.relname = 'scene_analyses'
                  AND pg_get_constraintdef(con.oid) LIKE '%lease_expires_at_utc%';
                """));
    }

    /// <summary>
    /// The migration must be reversible in one step, leaving no table, index or
    /// constraint behind — otherwise a failed upgrade cannot be rolled back cleanly.
    /// </summary>
    [Fact]
    public async Task TheMigrationIsReversibleAndLeavesNothingBehind()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        await db.GetService<IMigrator>().MigrateAsync("20260920060000_AddSceneConfiguration");

        string[] tables =
        [
            "scene_analyses",
            "track_analysis_outcomes",
            "track_zone_visits",
            "track_zone_summaries",
            "track_line_crossings",
            "track_motion_summaries",
        ];
        foreach (var table in tables)
        {
            Assert.Null(await ScalarAsync($"SELECT to_regclass('public.{table}')::text;"));
        }

        Assert.Equal(
            0L,
            await ScalarAsync("SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%scene_analyses%';"));
        Assert.Equal(
            0L,
            await ScalarAsync("SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%track_zone_%';"));

        // Slice 1's schema is untouched by the rollback.
        Assert.Equal(
            "scene_configuration_revisions",
            await ScalarAsync("SELECT to_regclass('public.scene_configuration_revisions')::text;"));

        // And it goes back up again on the same database.
        await db.Database.MigrateAsync();
        Assert.Equal("scene_analyses", await ScalarAsync("SELECT to_regclass('public.scene_analyses')::text;"));
    }

    // Test data
    private sealed record World(
        MaviDbContext Db,
        Guid RunId,
        Guid TrackId,
        Guid RevisionId,
        Guid ZoneId,
        Guid LineId);

    private async Task<World> FreshWorldAsync()
    {
        await fixture.ResetDatabaseAsync();
        var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        var camera = Camera.Create("CAM-SA-01", "Analytics Test Camera", "UTC");
        var source = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/CAM-SA-01/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            1,
            new string('a', 64));
        var video = VideoAsset.Create(
            camera.Id,
            source.Id,
            "analytics.mp4",
            Now.AddMinutes(-10),
            10_000,
            25,
            1,
            640,
            360,
            "h264",
            TimestampSource.Manual,
            1.0);
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", Now.AddMinutes(-5));
        run.MarkRunning("worker-01", Now.AddMinutes(-4));
        var track = Track.Create(
            run.Id,
            video.Id,
            1,
            ObjectClass.Person,
            0,
            8_000,
            Now.AddMinutes(-10),
            detectionCount: 8,
            meanConfidence: 0.8,
            maxConfidence: 0.9,
            createdAtUtc: Now.AddMinutes(-3));

        var configuration = SceneConfiguration.Create(camera.Id, Now.AddMinutes(-9));
        var revision = configuration.SaveRevision(
            null,
            new SceneRevisionDraft(
                "Analytics fixture",
                null,
                null,
                [
                    new SceneZoneDraft(
                        null,
                        "Gate",
                        null,
                        true,
                        [
                            new ScenePointDraft(0.1, 0.1),
                            new ScenePointDraft(0.4, 0.1),
                            new ScenePointDraft(0.4, 0.4),
                            new ScenePointDraft(0.1, 0.4),
                        ],
                        45),
                ],
                [
                    new TripLineDraft(
                        null,
                        "Kerb",
                        true,
                        new ScenePointDraft(0.1, 0.5),
                        new ScenePointDraft(0.9, 0.5),
                        true,
                        "inbound",
                        "outbound"),
                ]),
            null,
            SceneRules.UnattributedDevelopmentActor,
            Now.AddMinutes(-9));

        db.AddRange(camera, source, video, run, track, configuration, revision);
        await db.SaveChangesAsync();

        return new World(
            db,
            run.Id,
            track.Id,
            revision.Id,
            revision.Zones[0].ZoneId,
            revision.TripLines[0].LineId);
    }

    private static SceneAnalysis Unit(World world, string algorithmVersion = "scene-analytics-v1") =>
        SceneAnalysis.Queue(
            world.RunId,
            world.RevisionId,
            algorithmVersion,
            new string('b', 64),
            sourceCommit: null,
            Now);

    private static async Task<SceneAnalysis> PersistUnitAsync(
        World world,
        string algorithmVersion = "scene-analytics-v1")
    {
        var unit = Unit(world, algorithmVersion);
        world.Db.SceneAnalyses.Add(unit);
        await world.Db.SaveChangesAsync();
        return unit;
    }

    private static TrackZoneVisit Visit(Guid analysisId, Guid trackId, Guid zoneId, int visitIndex) =>
        TrackZoneVisit.Create(
            analysisId,
            trackId,
            zoneId,
            visitIndex,
            1_000,
            5_000,
            Now,
            Now.AddSeconds(4),
            4_000,
            beganInside: false,
            endedInside: false,
            closedByGap: false,
            "NE",
            "SW");

    private static TrackLineCrossing Crossing(Guid analysisId, Guid trackId, Guid lineId, int crossingIndex) =>
        TrackLineCrossing.Create(analysisId, trackId, lineId, crossingIndex, 2_000, Now.AddSeconds(2), "AToB", 0.25, 0.5);

    private static async Task PersistEveryFactKindAsync(World world, Guid analysisId)
    {
        world.Db.TrackAnalysisOutcomes.Add(
            TrackAnalysisOutcome.Analysed(analysisId, world.TrackId, "bbox-centre", 120, 1, 400));
        world.Db.TrackZoneVisits.Add(Visit(analysisId, world.TrackId, world.ZoneId, 0));
        world.Db.TrackZoneSummaries.Add(TrackZoneSummary.Create(
            analysisId, world.TrackId, world.ZoneId, 1, 4_000, Now, Now.AddSeconds(4), true, 45, 4_000));
        world.Db.TrackLineCrossings.Add(Crossing(analysisId, world.TrackId, world.LineId, 0));
        world.Db.TrackMotionSummaries.Add(TrackMotionSummary.Create(
            analysisId,
            world.TrackId,
            "NE",
            0.42,
            0.01,
            2_500,
            2_500,
            [new StationaryInterval(1_000, 3_500)],
            [world.ZoneId]));
        await world.Db.SaveChangesAsync();
    }

    // Raw SQL, so the database is asked directly rather than through the domain guards
    private Task InsertVisitAsync(
        World world,
        Guid analysisId,
        long entryOffsetMs = 1_000,
        long exitOffsetMs = 5_000,
        DateTimeOffset? exitTimestampUtc = null,
        long dwellMs = 4_000,
        string entryHeading = "NE") =>
        ExecuteAsync(
            """
            INSERT INTO track_zone_visits
              (id, analysis_id, track_id, zone_id, visit_index, entry_offset_ms, exit_offset_ms,
               entry_timestamp_utc, exit_timestamp_utc, dwell_ms, began_inside, ended_inside,
               closed_by_gap, entry_heading, exit_heading)
            VALUES (gen_random_uuid(), @analysis, @track, @zone, 0, @entryOffset, @exitOffset,
                    @entry, @exit, @dwell, false, false, false, @entryHeading, 'SW');
            """,
            ("analysis", analysisId),
            ("track", world.TrackId),
            ("zone", world.ZoneId),
            ("entryOffset", entryOffsetMs),
            ("exitOffset", exitOffsetMs),
            ("entry", Now),
            ("exit", exitTimestampUtc ?? Now.AddSeconds(4)),
            ("dwell", dwellMs),
            ("entryHeading", entryHeading));

    private Task InsertOutcomeAsync(
        Guid analysisId,
        Guid trackId,
        string outcome,
        string? reason = null,
        string? referencePoint = null,
        int sampleCount = 0) =>
        ExecuteAsync(
            """
            INSERT INTO track_analysis_outcomes
              (analysis_id, track_id, outcome, reason, reference_point, sample_count, gap_count, gap_total_ms)
            VALUES (@analysis, @track, @outcome, @reason, @referencePoint, @sampleCount, 0, 0);
            """,
            ("analysis", analysisId),
            ("track", trackId),
            ("outcome", outcome),
            ("reason", (object?)reason ?? DBNull.Value),
            ("referencePoint", (object?)referencePoint ?? DBNull.Value),
            ("sampleCount", sampleCount));

    private async Task ExecuteAsync(string sql, params (string Name, object Value)[] parameters)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var (name, value) in parameters)
        {
            command.Parameters.AddWithValue(name, value);
        }

        await command.ExecuteNonQueryAsync();
    }

    private async Task<string> IndexDefinitionAsync(string index) =>
        (string?)await ScalarAsync($"SELECT indexdef FROM pg_indexes WHERE indexname = '{index}';") ?? "";

    private async Task<object?> ScalarAsync(string sql)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        var value = await command.ExecuteScalarAsync();
        return value == DBNull.Value ? null : value;
    }

    private static async Task AssertCheckViolationAsync(Func<Task> act, string constraint)
    {
        var exception = await Assert.ThrowsAsync<PostgresException>(act);
        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
        Assert.Equal(constraint, exception.ConstraintName);
    }

    private static async Task AssertUniqueViolationAsync(Func<Task> act, string constraint)
    {
        var exception = await Assert.ThrowsAnyAsync<Exception>(act);
        var postgres = exception as PostgresException ?? exception.InnerException as PostgresException;
        Assert.NotNull(postgres);
        Assert.Equal(PostgresErrorCodes.UniqueViolation, postgres.SqlState);
        Assert.Equal(constraint, postgres.ConstraintName);
    }
}
