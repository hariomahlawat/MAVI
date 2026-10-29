using System.Security.Cryptography;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The Stage-4 plate schema (plan §5.1; ADR-013 implementation amendment 2026-10-13, items 11–15): the
/// migration is additive and round-trips, and the fact shapes hold in the database, not only in the domain.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlatePersistenceTests(PostgresFixture fixture)
{
    private const string Preceding = "20261002120000_AddTrackObjectSubclass";
    private const string Lifecycle = "20261013022604_AddPlateAnalysisLifecycle";
    // The last Stage-4 plate migration: the round trip covers every plate migration and no later, unrelated one.
    private const string LastPlateMigration = "20261016120000_LockTrackForPlateTextTrackStart";
    private static readonly DateTimeOffset Now = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);
    private static readonly PlateLeasePolicy Policy = new(TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 3, TimeSpan.FromHours(1));

    private static readonly string[] PlateTables =
    [
        "plate_analyses", "plate_identity_activations", "plate_attempt_failures", "plate_track_outcomes",
        "plate_observations", "plate_readings", "plate_track_texts",
    ];

    [Fact]
    public void ModelHasNoChangesPendingAgainstTheSnapshot()
    {
        using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges());
    }

    [Fact]
    public async Task TheMigrationIsAdditiveAndRoundTrips()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.GetService<IMigrator>().MigrateAsync(Preceding);
        var before = await ColumnSignatureAsync();
        Assert.All(PlateTables, table => Assert.False(TableExistsAsync(table).GetAwaiter().GetResult(), table));

        await db.GetService<IMigrator>().MigrateAsync(LastPlateMigration);
        Assert.Contains(Lifecycle, await db.Database.GetAppliedMigrationsAsync());
        Assert.All(PlateTables, table => Assert.True(TableExistsAsync(table).GetAwaiter().GetResult(), table));
        // No existing column changed: the pre-existing tables' columns are exactly as before.
        var after = await ColumnSignatureAsync();
        Assert.Equal(before, after.Where(item => !PlateTables.Contains(item.Split('.')[0])).ToList());

        await db.GetService<IMigrator>().MigrateAsync(Preceding);
        Assert.All(PlateTables, table => Assert.False(TableExistsAsync(table).GetAwaiter().GetResult(), table));
        Assert.Equal(before, await ColumnSignatureAsync());

        await db.Database.MigrateAsync();
        Assert.True(await TableExistsAsync("plate_track_texts"));
    }

    [Fact]
    public async Task APublishedAnalysisRoundTripsWithItsReadings()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 1, observationsPerTrack: 2);
        var track = run.Track(0);
        var analysisId = await SeedCompletedAnalysisAsync(world, run.RunId);

        await using (var db = world.Read())
        {
            db.PlateTrackOutcomes.Add(PlateTrackOutcome.Analysed(analysisId, track.TrackId, plateObservationCount: 2, distinctTextCount: 1));
            var read = PlateObservation.Create(analysisId, track.TrackId, track.Observations[1].ObservationId, 0, 150, 240, 118, 30, 412, 330,
                0.95, PlateObservationOutcome.Read,
            [
                new PlateReadingValues(0, "KA 01 AB 1234", 1, 0.97, "KA01AB1234", PlateNormalisationOutcome.Ok, null, "in-standard"),
                new PlateReadingValues(1, "MH12\nDE 4321", 2, 0.6, "MH12DE4321", PlateNormalisationOutcome.Ok, null, "in-standard"),
            ]);
            var unreadable = PlateObservation.Create(analysisId, track.TrackId, track.Observations[0].ObservationId, 0, 70, 120, 64, 16, 212, 168,
                0.52, PlateObservationOutcome.Unreadable, []);
            db.PlateObservations.AddRange(read, unreadable);
            db.PlateTrackTexts.Add(PlateTrackText.Create(analysisId, track.TrackId, "KA01AB1234", 1, 0.97, read.Id));
            await db.SaveChangesAsync();
        }

        await using (var db = world.Read())
        {
            var observations = await db.PlateObservations.Include(item => item.Readings)
                .Where(item => item.AnalysisId == analysisId).OrderBy(item => item.DetectorConfidence).ToListAsync();
            Assert.Equal(2, observations.Count);
            Assert.Equal(PlateObservationOutcome.Unreadable, observations[0].Outcome);
            Assert.Empty(observations[0].Readings);
            var readings = observations[1].Readings.OrderBy(item => item.Rank).ToList();
            Assert.Equal(["KA 01 AB 1234", "MH12\nDE 4321"], readings.Select(item => item.RawText));
            Assert.Equal(2, readings[1].RawLineCount);
            var text = await db.PlateTrackTexts.SingleAsync(item => item.AnalysisId == analysisId);
            Assert.Equal(observations[1].Id, text.BestPlateObservationId);
        }
    }

    [Fact]
    public async Task DatabaseConstraintsHoldTheFactShape()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 2, observationsPerTrack: 1);
        var track = run.Track(0);
        var source = track.Observations[0].ObservationId;
        var analysisId = await SeedCompletedAnalysisAsync(world, run.RunId);

        // Unavailable must explain itself with a pinned reason and assert no plate.
        await AssertViolatesAsync("ck_plate_track_outcomes_shape",
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Unavailable', NULL, 0, 0)",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ck_plate_track_outcomes_shape",
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Unavailable', 'network_blip', 0, 0)",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ck_plate_track_outcomes_shape",
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Unavailable', 'evidence_missing', 1, 0)",
            analysisId, track.TrackId);
        await AssertViolatesAsync("ck_plate_track_outcomes_counts",
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Analysed', NULL, 1, 2)",
            analysisId, track.TrackId);

        // A plate observation without its Track's outcome row is refused.
        await AssertViolatesAsync("FK_plate_observations_plate_track_outcomes_analysis_id_track_id",
            InsertObservation, Guid.CreateVersion7(), analysisId, track.TrackId, source, 0, 10, 10, 20, 8, 100, 80, "Read");

        await ExecuteAsync(
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Analysed', NULL, 1, 1)",
            analysisId, track.TrackId);

        // The box lies inside its crop.
        await AssertViolatesAsync("ck_plate_observations_box_inside_crop",
            InsertObservation, Guid.CreateVersion7(), analysisId, track.TrackId, source, 0, 90, 10, 20, 8, 100, 80, "Read");
        await AssertViolatesAsync("ck_plate_observations_box_inside_crop",
            InsertObservation, Guid.CreateVersion7(), analysisId, track.TrackId, source, 0, -1, 10, 20, 8, 100, 80, "Read");
        await AssertViolatesAsync("ck_plate_observations_outcome",
            InsertObservation, Guid.CreateVersion7(), analysisId, track.TrackId, source, 0, 10, 10, 20, 8, 100, 80, "Confirmed");

        var plateId = Guid.CreateVersion7();
        await ExecuteAsync(InsertObservation, plateId, analysisId, track.TrackId, source, 0, 10, 10, 20, 8, 100, 80, "Read");
        // One row per (analysis, source crop, plate index).
        await AssertViolatesAsync("ux_plate_observations_analysis_source_plate",
            InsertObservation, Guid.CreateVersion7(), analysisId, track.TrackId, source, 0, 10, 10, 20, 8, 100, 80, "Read");

        // ok carries a normalised text and a class; rejected carries neither.
        await AssertViolatesAsync("ck_plate_readings_normalisation",
            InsertReading, plateId, 0, "KA01", 0.9, DBNull.Value, "Ok", DBNull.Value, "other");
        await AssertViolatesAsync("ck_plate_readings_normalisation",
            InsertReading, plateId, 0, "KA01", 0.9, "ka01", "Ok", DBNull.Value, "other");
        await AssertViolatesAsync("ck_plate_readings_normalisation",
            InsertReading, plateId, 0, "KA01", 0.9, "KA01", "Rejected", "non-alphanumeric", DBNull.Value);
        await AssertViolatesAsync("ck_plate_readings_confidence",
            InsertReading, plateId, 0, "KA01", 1.5, "KA01", "Ok", DBNull.Value, "other");
        await AssertViolatesAsync("ck_plate_readings_rank",
            InsertReading, plateId, 5, "KA01", 0.9, "KA01", "Ok", DBNull.Value, "other");
        await ExecuteAsync(InsertReading, plateId, 0, "KA01", 0.9, "KA01", "Ok", DBNull.Value, "other");

        // Track texts are normalised and reference a real plate observation.
        await AssertViolatesAsync("ck_plate_track_texts_text",
            "INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) VALUES ($1, $2, 'KA 01', 1, 0.9, $3)",
            analysisId, track.TrackId, plateId);
        await ExecuteAsync(
            "INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) VALUES ($1, $2, 'KA01', 1, 0.9, $3)",
            analysisId, track.TrackId, plateId);

        // Evidence linkage is Restrict: the sealed source crop cannot disappear beneath a plate.
        await AssertViolatesAsync("FK_plate_observations_observations_source_observation_id",
            "DELETE FROM observations WHERE id = $1", source);
    }

    [Fact]
    public async Task TheIdentityIsUniquePerRun()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(0, 1);
        await using var db = world.Read();
        db.PlateAnalyses.Add(PlateAnalysis.Queue(run.RunId, Identity(), Now));
        await db.SaveChangesAsync();
        await using var second = world.Read();
        second.PlateAnalyses.Add(PlateAnalysis.Queue(run.RunId, Identity(), Now));
        var exception = await Assert.ThrowsAsync<DbUpdateException>(() => second.SaveChangesAsync());
        Assert.Equal("ux_plate_analyses_identity", ((PostgresException)exception.InnerException!).ConstraintName);
    }

    [Fact]
    public async Task ARunningUnitAlwaysHasItsLease()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(0, 1);
        var unit = PlateAnalysis.Queue(run.RunId, Identity(), Now);
        await using (var db = world.Read())
        {
            db.PlateAnalyses.Add(unit);
            await db.SaveChangesAsync();
        }

        await AssertViolatesAsync("ck_plate_analyses_running_lease",
            "UPDATE plate_analyses SET status = 'Running' WHERE id = $1", unit.Id);
        await AssertViolatesAsync("ck_plate_analyses_fact_bearing",
            "UPDATE plate_analyses SET status = 'Completed' WHERE id = $1", unit.Id);
    }

    // --- Helpers ---------------------------------------------------------------------------

    private const string InsertObservation =
        "INSERT INTO plate_observations (id, analysis_id, track_id, source_observation_id, plate_index, box_x, box_y, box_width, box_height, crop_width, crop_height, detector_confidence, outcome) " +
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 0.9, $12)";

    private const string InsertReading =
        "INSERT INTO plate_readings (plate_observation_id, rank, raw_text, raw_line_count, confidence, normalised_text, normalisation_outcome, normalisation_reason, format_class) " +
        "VALUES ($1, $2, $3, 1, $4, $5, $6, $7, $8)";

    internal static PlateIdentityFields Identity() => new(
        Fingerprint: new string('a', 64),
        PipelineId: "plates-fixture",
        PipelineVersion: "1.0.0",
        PredictionsSchemaVersion: "mavi-plate-predictions-v1",
        NormalisationId: "mavi-plate-normalisation-v1",
        NormalisationSha256: new string('b', 64),
        SummaryPolicyId: "plate-track-text-rank0",
        SummaryPolicyVersion: "1.0.0",
        SummaryPolicySha256: new string('c', 64),
        CapabilitiesCanonical: "[{\"capabilityId\":\"ocr\",\"modelPackId\":\"mavi-model-v2-" + new string('1', 64) +
            "\"},{\"capabilityId\":\"plate-detector\",\"modelPackId\":\"mavi-model-v2-" + new string('2', 64) + "\"}]",
        ParametersSha256: new string('d', 64));

    private static async Task<Guid> SeedCompletedAnalysisAsync(VisualAttributeWorld world, Guid runId)
    {
        await using var db = world.Read();
        var artifact = Artifact.Create(ArtifactType.PlatePredictions, $"evidence/plates/{Guid.NewGuid():D}/predictions-{new string('f', 64)}.json",
            "application/json", 10, new string('f', 64));
        var unit = PlateAnalysis.Queue(runId, Identity(), Now);
        unit.Claim("plates-01", SHA256.HashData(new byte[32]), Now, Policy);
        unit.Complete("plates-01", true, 1, Now,
            new PlateCompletion(new string('e', 64), 19_000 + Random.Shared.Next(1000), artifact.Id, "{}", 1, 0, 1, 0), isPreferred: true);
        db.AddRange(artifact, unit);
        await db.SaveChangesAsync();
        return unit.Id;
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

    private async Task<bool> TableExistsAsync(string table)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT to_regclass($1) IS NOT NULL", connection);
        command.Parameters.AddWithValue("public." + table);
        return (bool)(await command.ExecuteScalarAsync())!;
    }

    /// <summary>Every column of every public table as <c>table.column:type:nullable:default</c>, ordered.</summary>
    private async Task<List<string>> ColumnSignatureAsync()
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT table_name || '.' || column_name || ':' || data_type || ':' || is_nullable || ':' || coalesce(column_default, '') " +
            "FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, column_name", connection);
        var result = new List<string>();
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync()) result.Add(reader.GetString(0));
        return result;
    }
}
