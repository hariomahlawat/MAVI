using System.Security.Cryptography;
using Mavi.Domain.Media;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The S2b schema (ADR-013 §14; acceptance E1): the placeholder table is replaced, not
/// altered; integrity constraints hold in the database, not only in the domain.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributePersistenceTests(PostgresFixture fixture)
{
    private const string Preceding = "20260925020849_AddVisionFinalization";
    private const string Lifecycle = "20260928035552_AddVisualAttributeLifecycle";
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    [Fact]
    public void ModelHasNoChangesPendingAgainstTheSnapshot()
    {
        using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges());
    }

    [Fact]
    public async Task TheMigrationRefusesToDiscardPlaceholderRows()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.GetService<IMigrator>().MigrateAsync(Preceding);
        var trackId = await SeedTrackAtPrecedingSchemaAsync();
        await ExecuteAsync(
            "INSERT INTO visual_attributes (id, track_id, attribute_type, value, confidence, created_at_utc) VALUES ($1, $2, 'colour', 'red', 0.5, now())",
            Guid.CreateVersion7(), trackId);

        var exception = await Assert.ThrowsAsync<PostgresException>(() => db.GetService<IMigrator>().MigrateAsync(Lifecycle));

        Assert.Contains("placeholder rows", exception.MessageText, StringComparison.Ordinal);
        Assert.DoesNotContain(Lifecycle, await db.Database.GetAppliedMigrationsAsync());
    }

    [Fact]
    public async Task TheMigrationRoundTripsOnAnEmptyPlaceholder()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        Assert.True(await ColumnExistsAsync("visual_attributes", "analysis_id"));
        Assert.False(await ColumnExistsAsync("visual_attributes", "model_name"));

        await db.GetService<IMigrator>().MigrateAsync(Preceding);
        Assert.True(await ColumnExistsAsync("visual_attributes", "model_name"));
        Assert.False(await TableExistsAsync("visual_attribute_analyses"));

        await db.Database.MigrateAsync();
        Assert.True(await TableExistsAsync("visual_attribute_analyses"));
    }

    [Fact]
    public async Task DatabaseConstraintsHoldTheFactShape()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 1, vehicles: 0, observationsPerTrack: 1);
        var track = run.Track(0);
        var analysisId = await SeedCompletedAnalysisAsync(world, run.RunId);

        // Observed without its evidence, and Unknown with a value, are refused by the shape check.
        await ExecuteAsync(
            "INSERT INTO visual_attribute_track_outcomes (analysis_id, track_id, outcome, reason) VALUES ($1, $2, 'Analysed', NULL)",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ck_visual_attributes_shape",
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome, value, confidence, supporting_observation_id) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-upper', 'Observed', 'dark', 0.5, NULL)",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ck_visual_attributes_shape",
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome, value, confidence, supporting_observation_id) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-upper', 'Unknown', 'dark', NULL, NULL)",
            analysisId, track.TrackId);

        // One final row per (analysis, Track, attribute type).
        await ExecuteAsync(
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-upper', 'Unknown')",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ux_visual_attributes_analysis_track_type",
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-upper', 'Unknown')",
            analysisId, track.TrackId);

        // A fact without its Track's outcome row is refused.
        var other = await world.SeedRunAsync(persons: 1, vehicles: 0);
        await AssertViolatesAsync("FK_visual_attributes_visual_attribute_track_outcomes_analysis_~",
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-lower', 'Unknown')",
            analysisId, other.Track(0).TrackId);

        // Unavailable must explain itself with a pinned reason.
        await AssertViolatesAsync("ck_visual_attribute_track_outcomes_shape",
            "INSERT INTO visual_attribute_track_outcomes (analysis_id, track_id, outcome, reason) VALUES ($1, $2, 'Unavailable', NULL)",
            analysisId, other.Track(0).TrackId);
        await AssertViolatesAsync("ck_visual_attribute_track_outcomes_shape",
            "INSERT INTO visual_attribute_track_outcomes (analysis_id, track_id, outcome, reason) VALUES ($1, $2, 'Unavailable', 'network_blip')",
            analysisId, other.Track(0).TrackId);

        // Evidence linkage is Restrict: a supporting Observation cannot disappear beneath a fact.
        await ExecuteAsync(
            "INSERT INTO visual_attributes (id, analysis_id, track_id, attribute_type, outcome, value, confidence, supporting_observation_id) VALUES (gen_random_uuid(), $1, $2, 'fixture-person-lower', 'Observed', 'dark', 0.9, $3)",
            analysisId, track.TrackId, track.Observations[0].ObservationId);
        await AssertViolatesAsync("FK_visual_attributes_observations_supporting_observation_id",
            "DELETE FROM observations WHERE id = $1", track.Observations[0].ObservationId);
    }

    [Fact]
    public async Task TheIdentityIsUniquePerRun()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(1, 0);
        await using var db = world.Read();
        db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(run.RunId, VisualAttributeTestIdentity.Fields(), Now));
        await db.SaveChangesAsync();
        await using var second = world.Read();
        second.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(run.RunId, VisualAttributeTestIdentity.Fields(), Now));
        var exception = await Assert.ThrowsAsync<DbUpdateException>(() => second.SaveChangesAsync());
        Assert.Equal("ux_visual_attribute_analyses_identity", ((PostgresException)exception.InnerException!).ConstraintName);
    }

    // --- Helpers ---------------------------------------------------------------------------

    internal static async Task<Guid> SeedCompletedAnalysisAsync(VisualAttributeWorld world, Guid runId)
    {
        await using var db = world.Read();
        var artifact = Artifact.Create(ArtifactType.AttributePredictions, $"evidence/attributes/{Guid.NewGuid():D}/predictions-{new string('f', 64)}.json",
            "application/json", 10, new string('f', 64));
        var unit = VisualAttributeAnalysis.Queue(runId, VisualAttributeTestIdentity.Fields(), Now);
        unit.Claim("attributes-01", SHA256.HashData(new byte[32]), Now,
            new VisualAttributeLeasePolicy(TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 3, TimeSpan.FromHours(1)));
        unit.Complete("attributes-01", true, 1, Now, new VisualAttributeCompletion(new string('e', 64), 9_000 + Random.Shared.Next(1000), artifact.Id, "{}", 1, 0, 1, 0), isPreferred: true);
        db.AddRange(artifact, unit);
        await db.SaveChangesAsync();
        return unit.Id;
    }

    private async Task<Guid> SeedTrackAtPrecedingSchemaAsync()
    {
        // Tables unchanged since the preceding schema are written with their own entity types.
        await using var db = fixture.CreateDbContext();
        var camera = Mavi.Domain.Cameras.Camera.Create("CAM-VA-MIG", "Migration camera", "UTC");
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/CAM-VA-MIG/{Guid.CreateVersion7()}.mp4", "video/mp4", 1, new string('a', 64));
        var video = VideoAsset.Create(camera.Id, source.Id, "m.mp4", Now.AddHours(-1), 1_000, 25, 1, 64, 64, "h264", TimestampSource.Manual, 1.0);
        var run = Mavi.Domain.Processing.ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", Now.AddMinutes(-5));
        db.AddRange(camera, source, video, run);
        await db.SaveChangesAsync();

        // tracks has gained columns since (Stage 3, AddTrackObjectSubclass), so the current
        // entity cannot be written at this schema: insert with the preceding column list.
        var trackId = Guid.CreateVersion7();
        var start = Now.AddHours(-1);
        await ExecuteAsync(
            """
            INSERT INTO tracks (id, processing_run_id, video_asset_id, local_track_number, object_class,
                start_offset_ms, end_offset_ms, start_timestamp_utc, end_timestamp_utc, duration_ms,
                detection_count, mean_confidence, max_confidence, review_status, created_at_utc)
            VALUES ($1, $2, $3, 1, 'Person', 0, 1000, $4, $5, 1000, 1, 0.5, 0.5, 'Unreviewed', $4)
            """,
            trackId, run.Id, video.Id, start, start.AddMilliseconds(1_000));
        return trackId;
    }

    private async Task AssertViolatesAsync(string constraint, string sql, params object[] parameters)
    {
        var exception = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(sql, parameters));
        Assert.Equal(constraint, exception.ConstraintName);
    }

    private async Task ExecuteAsync(string sql, params object[] parameters)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var parameter in parameters) command.Parameters.AddWithValue(parameter);
        await command.ExecuteNonQueryAsync();
    }

    private async Task<bool> ColumnExistsAsync(string table, string column)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = $1 AND column_name = $2", connection);
        command.Parameters.AddWithValue(table);
        command.Parameters.AddWithValue(column);
        return (long)(await command.ExecuteScalarAsync())! == 1;
    }

    private async Task<bool> TableExistsAsync(string table)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT to_regclass($1) IS NOT NULL", connection);
        command.Parameters.AddWithValue("public." + table);
        return (bool)(await command.ExecuteScalarAsync())!;
    }
}
