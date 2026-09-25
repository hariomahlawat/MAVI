using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// S1.4 B3 F1: <c>AddVisionFinalization</c> upgrade compatibility, the payload table and the
/// Finalizing row invariants in PostgreSQL, and the F1 runtime posture (3.1 defined, not yet
/// accepted; status projection carries the phase).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationPersistenceTests(PostgresFixture fixture)
{
    private const string BeforeFinalization = "20260923160000_AddTrackEvidenceSet";
    private const string Finalization = "20260925020849_AddVisionFinalization";
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 6, 0, 0, TimeSpan.Zero);
    private static readonly string Digest = new('d', 64);

    // -- migration ----------------------------------------------------------------------------

    [Fact]
    public async Task UpgradeKeepsEveryExistingJobRowWithDefaultedFinalizationState()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(BeforeFinalization);
        await using var connection = await OpenAsync();
        var jobs = new Dictionary<string, Guid>();
        foreach (var status in new[] { "Queued", "Leased", "Completed", "Failed", "Cancelled" })
            jobs[status] = await InsertLegacyJobAsync(connection, await SeedRunAtPrecedingSchemaAsync(connection, status), status);

        await migrator.MigrateAsync(Finalization);

        await using var command = new NpgsqlCommand("""
            SELECT status, finalization_attempt_count, finalization_accepted_at_utc IS NULL, finalization_claim_token_hash IS NULL,
                   finalization_claim_expires_at_utc IS NULL, finalization_claim_extended_at_utc IS NULL, finalization_last_error_code IS NULL,
                   lease_owner, attempt_count
            FROM vision_jobs ORDER BY status
            """, connection);
        await using var reader = await command.ExecuteReaderAsync();
        var seen = new List<string>();
        while (await reader.ReadAsync())
        {
            seen.Add(reader.GetString(0));
            Assert.Equal(0, reader.GetInt32(1));
            for (var column = 2; column <= 6; column++) Assert.True(reader.GetBoolean(column), $"column {column} of {reader.GetString(0)}");
            Assert.Equal(reader.GetString(0) == "Queued" ? null : "legacy-worker", reader.IsDBNull(7) ? null : reader.GetString(7));
            Assert.Equal(reader.GetString(0) == "Queued" ? 0 : 1, reader.GetInt32(8));
        }
        await reader.DisposeAsync();
        Assert.Equal(jobs.Keys.Order(StringComparer.Ordinal), seen);

        Assert.True(await TableExistsAsync(connection, "vision_finalization_payloads"));
        Assert.Contains(Finalization, await db.Database.GetAppliedMigrationsAsync());
        // The upgraded schema is what the model expects, and it is the latest migration.
        await db.Database.MigrateAsync();
        Assert.Empty(await db.Database.GetPendingMigrationsAsync());
    }

    [Fact]
    public async Task ExistingRowsAreLoadableByTheNewBinaryAndStillLeaseable()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(BeforeFinalization);
        Guid queuedId;
        await using (var connection = await OpenAsync())
        {
            queuedId = await InsertLegacyJobAsync(connection, await SeedRunAtPrecedingSchemaAsync(connection, "Queued"), "Queued");
        }
        await db.Database.MigrateAsync();

        var job = await db.VisionJobs.SingleAsync(x => x.Id == queuedId);
        Assert.Equal(VisionJobStatus.Queued, job.Status);
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.Null(job.FinalizationAcceptedAtUtc);
        Assert.True(job.CanLease(Now.AddDays(1), 3));
        job.Lease("worker-a", new byte[32], Now.AddDays(1), TimeSpan.FromMinutes(2), 3);
        await db.SaveChangesAsync();
    }

    [Fact]
    public async Task DowngradeRefusesWhileAJobIsFinalizingAndSucceedsOnceNoneIs()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var job = await SeedFinalizingJobAsync(db);
        await using var connection = await OpenAsync();

        var refused = await Assert.ThrowsAsync<PostgresException>(() => db.GetService<IMigrator>().MigrateAsync(BeforeFinalization));
        Assert.Contains("vision_jobs_finalizing_rows_present", refused.MessageText, StringComparison.Ordinal);
        Assert.Contains(Finalization, await db.Database.GetAppliedMigrationsAsync());
        Assert.True(await TableExistsAsync(connection, "vision_finalization_payloads"));

        // A retained payload of an unfinished job also blocks the downgrade even without a Finalizing status.
        await ExecuteAsync(connection, "UPDATE vision_jobs SET status = 'Leased' WHERE id = $1", job.Id);
        var payloadBlocked = await Assert.ThrowsAsync<PostgresException>(() => db.GetService<IMigrator>().MigrateAsync(BeforeFinalization));
        Assert.Contains("vision_finalization_payloads_unfinished_present", payloadBlocked.MessageText, StringComparison.Ordinal);

        await ExecuteAsync(connection, "UPDATE vision_jobs SET status = 'Completed', completed_at_utc = finalization_accepted_at_utc WHERE id = $1", job.Id);
        await db.GetService<IMigrator>().MigrateAsync(BeforeFinalization);
        Assert.DoesNotContain(Finalization, await db.Database.GetAppliedMigrationsAsync());
        Assert.False(await TableExistsAsync(connection, "vision_finalization_payloads"));
        Assert.False(await ColumnExistsAsync(connection, "vision_jobs", "finalization_attempt_count"));
    }

    [Fact]
    public void ModelHasNoChangesPendingAgainstTheSnapshot()
    {
        using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges());
    }

    // -- model shape --------------------------------------------------------------------------

    [Fact]
    public void PayloadIsKeyedByJobAndAttemptWithNoNavigationEitherWay()
    {
        var model = BuildDesignTimeModel();
        var payload = model.FindEntityType(typeof(VisionFinalizationPayload))!;
        var job = model.FindEntityType(typeof(VisionJob))!;

        Assert.Equal(["JobId", "AttemptCount"], payload.FindPrimaryKey()!.Properties.Select(p => p.Name));
        var fk = Assert.Single(payload.GetForeignKeys());
        Assert.Equal(typeof(VisionJob), fk.PrincipalEntityType.ClrType);
        Assert.Equal(DeleteBehavior.Cascade, fk.DeleteBehavior);
        Assert.Null(fk.DependentToPrincipal);
        Assert.Null(fk.PrincipalToDependent);
        Assert.Empty(payload.GetNavigations());
        Assert.Empty(job.GetNavigations());
        Assert.Equal("vision_finalization_payloads", payload.GetTableName());
        Assert.Equal("bytea", payload.FindProperty(nameof(VisionFinalizationPayload.Payload))!.GetColumnType());

        var constraints = payload.GetCheckConstraints().ToDictionary(c => c.Name!, c => c.Sql);
        Assert.Contains("octet_length(payload)", constraints["ck_vision_finalization_payloads_length"]);
        Assert.Contains(WorkerContractRules.MaximumCompletionRequestBodyBytes.ToString(System.Globalization.CultureInfo.InvariantCulture), constraints["ck_vision_finalization_payloads_length"]);
        Assert.Contains("status <> 'Finalizing'", job.GetCheckConstraints().Single(c => c.Name == "ck_vision_jobs_finalizing_facts").Sql);
        var claimIndex = job.GetIndexes().Single(i => i.GetDatabaseName() == "ix_vision_jobs_finalizing_claim");
        Assert.Equal("status = 'Finalizing'", claimIndex.GetFilter());
    }

    // -- database invariants ------------------------------------------------------------------

    [Fact]
    public async Task PayloadRoundTripsExactBytesAndIsUniquePerAttempt()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var job = await SeedFinalizingJobAsync(db);
        db.ChangeTracker.Clear();

        var stored = await db.VisionFinalizationPayloads.AsNoTracking().SingleAsync();
        Assert.Equal(job.Id, stored.JobId);
        Assert.Equal(job.AttemptCount, stored.AttemptCount);
        Assert.Equal(PayloadBytes(), stored.Payload);
        Assert.True(stored.Matches(PayloadBytes()));
        Assert.Equal(Digest, stored.CompletionDigest);

        db.VisionFinalizationPayloads.Add(VisionFinalizationPayload.Create(job.Id, job.AttemptCount, [0x7b, 0x7d], Digest, Now, 1024));
        var duplicate = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        Assert.Equal(PostgresErrorCodes.UniqueViolation, Assert.IsType<PostgresException>(duplicate.InnerException).SqlState);
        db.ChangeTracker.Clear();

        db.VisionFinalizationPayloads.Add(VisionFinalizationPayload.Create(Guid.CreateVersion7(), 1, [0x7b, 0x7d], Digest, Now, 1024));
        var orphan = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, Assert.IsType<PostgresException>(orphan.InnerException).SqlState);
    }

    [Theory]
    [InlineData("payload_length = payload_length + 1", "ck_vision_finalization_payloads_length")]
    [InlineData("payload = payload || '\\x20'::bytea", "ck_vision_finalization_payloads_length")]
    [InlineData("payload_sha256 = upper(payload_sha256)", "ck_vision_finalization_payloads_sha256")]
    [InlineData("completion_digest = left(completion_digest, 63)", "ck_vision_finalization_payloads_digest")]
    [InlineData("attempt_count = 0", "ck_vision_finalization_payloads_attempt")]
    public async Task DatabaseRejectsAnInconsistentPayloadRow(string mutation, string constraint)
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var job = await SeedFinalizingJobAsync(db);
        await using var connection = await OpenAsync();

        var error = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync(connection, $"UPDATE vision_finalization_payloads SET {mutation} WHERE job_id = $1", job.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, error.SqlState);
        Assert.Equal(constraint, error.ConstraintName);
    }

    [Theory]
    [InlineData("completion_digest = NULL")]
    [InlineData("finalization_accepted_at_utc = NULL")]
    [InlineData("lease_owner = NULL")]
    [InlineData("lease_token_hash = NULL")]
    [InlineData("attempt_count = 0")]
    public async Task DatabaseRejectsAFinalizingRowWithoutItsHandOffFacts(string mutation)
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var job = await SeedFinalizingJobAsync(db);
        await using var connection = await OpenAsync();

        var error = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync(connection, $"UPDATE vision_jobs SET {mutation} WHERE id = $1", job.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, error.SqlState);
        Assert.Equal("ck_vision_jobs_finalizing_facts", error.ConstraintName);
    }

    [Fact]
    public async Task DatabaseBoundsTheClaimTokenHashAndAttemptCount()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var job = await SeedFinalizingJobAsync(db);
        await using var connection = await OpenAsync();

        var hash = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync(connection, "UPDATE vision_jobs SET finalization_claim_token_hash = '\\x0102'::bytea WHERE id = $1", job.Id));
        Assert.Equal("ck_vision_jobs_finalization_claim_token_hash", hash.ConstraintName);
        var attempts = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync(connection, "UPDATE vision_jobs SET finalization_attempt_count = -1 WHERE id = $1", job.Id));
        Assert.Equal("ck_vision_jobs_finalization_attempts", attempts.ConstraintName);
    }

    [Fact]
    public async Task ClaimStateRoundTripsThroughTheDomainAndDeletingTheJobCascadesToItsPayload()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seeded = await SeedFinalizingJobAsync(db);
        db.ChangeTracker.Clear();
        var token = RandomNumberGenerator.GetBytes(VisionJob.FinalizationClaimTokenByteLength);

        var job = await db.VisionJobs.SingleAsync(x => x.Id == seeded.Id);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        job.ClaimFinalization(SHA256.HashData(token), Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3);
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();

        var claimed = await db.VisionJobs.AsNoTracking().SingleAsync(x => x.Id == seeded.Id);
        Assert.True(claimed.FinalizationOwnedBy(token, Now.AddMinutes(2)));
        Assert.Equal(1, claimed.FinalizationAttemptCount);
        Assert.Equal(Now.AddMinutes(6), claimed.FinalizationClaimExpiresAtUtc);

        await using var connection = await OpenAsync();
        await ExecuteAsync(connection, "DELETE FROM vision_jobs WHERE id = $1", seeded.Id);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
    }

    [Fact]
    public async Task StatusAndLeaseQueriesDoNotLoadThePayload()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seeded = await SeedFinalizingJobAsync(db);
        db.ChangeTracker.Clear();

        var sql = db.VisionJobs.Where(x => x.Id == seeded.Id).ToQueryString();

        Assert.DoesNotContain("vision_finalization_payloads", sql, StringComparison.Ordinal);
        Assert.DoesNotContain("payload", sql, StringComparison.OrdinalIgnoreCase);
    }

    // -- F1 runtime posture -------------------------------------------------------------------

    [Fact]
    public async Task EndpointStillRejects31AndProbeStillAdvertises20And30()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await VisionResultCompletionV3ApiTests.BuildRequestAsync(factory, lease, ["representative"]);

        using var rejected = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = "3.1" });

        Assert.Equal(HttpStatusCode.BadRequest, rejected.StatusCode);
        Assert.Contains("worker_contract_version_unsupported", await rejected.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        using var probe = await client.GetAsync("/api/vision/contract");
        Assert.Contains("\"completionSchemaVersions\":[\"2.0\",\"3.0\"]", await probe.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(VisionJobStatus.Leased, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
    }

    [Fact]
    public async Task ProcessingStatusCarriesThePhaseOfTheLatestJob()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        Assert.Equal(("Queued", "queued"), await PhaseAsync(client, videoId));

        await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        Assert.Equal(("Running", "processing"), await PhaseAsync(client, videoId));

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var job = await db.VisionJobs.SingleAsync();
            job.BeginFinalization("gpu-sdd-01", true, job.AttemptCount, Now.AddSeconds(5), Digest);
            db.VisionFinalizationPayloads.Add(VisionFinalizationPayload.Create(job.Id, job.AttemptCount, PayloadBytes(), Digest, Now.AddSeconds(5), 1024));
            await db.SaveChangesAsync();
        }

        // The run stays Running while the job is Finalizing; only the phase says so, and no counters are fabricated.
        Assert.Equal(("Running", "finalizing"), await PhaseAsync(client, videoId));
        using var status = await client.GetAsync($"/api/videos/{videoId}/processing");
        using var body = JsonDocument.Parse(await status.Content.ReadAsStringAsync());
        var run = body.RootElement.GetProperty("latestRun");
        Assert.Equal(0, run.GetProperty("tracksCreated").GetInt32());
        Assert.Equal(100, run.GetProperty("progressPercent").GetDouble());
        Assert.Equal(JsonValueKind.Null, run.GetProperty("completedAtUtc").ValueKind);
    }

    // -- helpers ------------------------------------------------------------------------------

    private static byte[] PayloadBytes() => "{\"schemaVersion\":\"3.1\",\"tracks\":[]}"u8.ToArray();

    private static async Task<(string Status, string Phase)> PhaseAsync(HttpClient client, Guid videoId)
    {
        using var response = await client.GetAsync($"/api/videos/{videoId}/processing");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var run = body.RootElement.GetProperty("latestRun");
        return (run.GetProperty("status").GetString()!, run.GetProperty("phase").GetString()!);
    }

    private static async Task<VisionJob> SeedFinalizingJobAsync(MaviDbContext db)
    {
        var camera = Camera.Create("CAM-FIN", "Finalization", "UTC", Now.AddMinutes(-5));
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/{Guid.CreateVersion7()}.mp4", "video/mp4", 1, new string('a', 64), createdAtUtc: Now.AddMinutes(-4));
        var video = VideoAsset.Create(Guid.CreateVersion7(), camera.Id, source.Id, "fin.mp4", Now, durationMs: 60_000,
            frameRateNumerator: 25, frameRateDenominator: 1, width: 1920, height: 1080, codec: "h264",
            timestampSource: TimestampSource.Manual, timestampConfidence: 1.0, recordingTimeZoneId: "UTC",
            recordingUtcOffsetMinutes: 0, importedAtUtc: Now.AddMinutes(-3));
        video.QueueProcessing();
        video.MarkProcessing();
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", Now);
        run.AssignLease("worker-a", Now);
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", Now);
        job.Lease("worker-a", new byte[32], Now, TimeSpan.FromMinutes(2), 3);
        job.BeginFinalization("worker-a", true, 1, Now.AddSeconds(30), Digest);
        var payload = VisionFinalizationPayload.Create(job.Id, job.AttemptCount, PayloadBytes(), Digest, Now.AddSeconds(30), 1024);
        db.AddRange(camera, source, video, run, job, payload);
        await db.SaveChangesAsync();
        return job;
    }

    /// <summary>One legacy video, run and camera per job: a run has one job and a video one active run.</summary>
    private static async Task<Guid> SeedRunAtPrecedingSchemaAsync(NpgsqlConnection connection, string jobStatus)
    {
        var cameraId = Guid.CreateVersion7();
        var sourceId = Guid.CreateVersion7();
        var videoId = Guid.CreateVersion7();
        var runId = Guid.CreateVersion7();
        var runStatus = jobStatus switch { "Queued" or "Leased" => "Running", "Completed" => "Completed", _ => "Failed" };
        await using var batch = new NpgsqlBatch(connection);
        var camera = new NpgsqlBatchCommand("""
            INSERT INTO cameras(id,code,name,time_zone_id,is_active,created_at_utc,updated_at_utc)
            VALUES ($1,$3,'Legacy','UTC',true,$2,$2)
            """);
        camera.Parameters.AddWithValue(cameraId); camera.Parameters.AddWithValue(Now); camera.Parameters.AddWithValue($"CAM-{jobStatus.ToUpperInvariant()}");
        var source = new NpgsqlBatchCommand("""
            INSERT INTO artifacts(id,artifact_type,storage_key,mime_type,size_bytes,sha256,created_at_utc)
            VALUES ($1,'SourceVideo',$4,'video/mp4',1,$2,$3)
            """);
        source.Parameters.AddWithValue(sourceId); source.Parameters.AddWithValue(Convert.ToHexStringLower(SHA256.HashData(Guid.NewGuid().ToByteArray())));
        source.Parameters.AddWithValue(Now); source.Parameters.AddWithValue($"source/{sourceId:D}.mp4");
        var video = new NpgsqlBatchCommand("""
            INSERT INTO video_assets(id,camera_id,source_artifact_id,original_file_name,source_type,
                recording_start_utc,recording_end_utc,duration_ms,frame_rate_numerator,frame_rate_denominator,
                width,height,codec,timestamp_source,timestamp_confidence,processing_status,imported_at_utc,
                recording_time_zone_id,recording_utc_offset_minutes)
            VALUES ($1,$2,$3,'legacy.mp4','UploadedFile',$4,$4 + interval '60 seconds',60000,25,1,1920,1080,
                'h264','Manual',1,'Processing',$4,'UTC',0)
            """);
        video.Parameters.AddWithValue(videoId); video.Parameters.AddWithValue(cameraId); video.Parameters.AddWithValue(sourceId); video.Parameters.AddWithValue(Now);
        var run = new NpgsqlBatchCommand("""
            INSERT INTO processing_runs(id,video_asset_id,status,pipeline_version,configuration_json,worker_id,
                queued_at_utc,started_at_utc,frames_processed,tracks_created)
            VALUES ($1,$2,$4,'phase1-v1','{}','legacy-worker',$3,$3,0,0)
            """);
        run.Parameters.AddWithValue(runId); run.Parameters.AddWithValue(videoId); run.Parameters.AddWithValue(Now); run.Parameters.AddWithValue(runStatus);
        batch.BatchCommands.Add(camera); batch.BatchCommands.Add(source); batch.BatchCommands.Add(video); batch.BatchCommands.Add(run);
        await batch.ExecuteNonQueryAsync();
        return runId;
    }

    private static async Task<Guid> InsertLegacyJobAsync(NpgsqlConnection connection, Guid runId, string status)
    {
        var jobId = Guid.CreateVersion7();
        var leased = status != "Queued";
        await using var insert = new NpgsqlCommand("""
            INSERT INTO vision_jobs(id,processing_run_id,pipeline,status,created_at_utc,available_at_utc,lease_owner,lease_token_hash,
                lease_expires_at_utc,attempt_count,progress_percent,completed_at_utc,failure_code,completion_digest)
            VALUES ($1,$2,'phase1',$3,$4,$4,$5,$6,$7,$8,0,$9,$10,$11)
            """, connection);
        insert.Parameters.AddWithValue(jobId);
        insert.Parameters.AddWithValue(runId);
        insert.Parameters.AddWithValue(status);
        insert.Parameters.AddWithValue(Now);
        insert.Parameters.AddWithValue(leased ? "legacy-worker" : DBNull.Value);
        insert.Parameters.AddWithValue(leased ? new byte[32] : DBNull.Value);
        insert.Parameters.AddWithValue(leased ? Now.AddMinutes(2) : DBNull.Value);
        insert.Parameters.AddWithValue(leased ? 1 : 0);
        insert.Parameters.AddWithValue(status is "Completed" or "Failed" or "Cancelled" ? Now.AddMinutes(1) : DBNull.Value);
        insert.Parameters.AddWithValue(status is "Failed" ? "vision_dummy_not_implemented" : DBNull.Value);
        insert.Parameters.AddWithValue(status is "Completed" ? new string('c', 64) : DBNull.Value);
        await insert.ExecuteNonQueryAsync();
        return jobId;
    }

    private static IModel BuildDesignTimeModel()
    {
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql("Host=model-only;Database=mavi_test", npgsql => npgsql.UseVector())
            .Options;
        using var db = new MaviDbContext(options);
        return db.GetService<IDesignTimeModel>().Model;
    }

    private async Task<NpgsqlConnection> OpenAsync()
    {
        var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        return connection;
    }

    private static async Task ExecuteAsync(NpgsqlConnection connection, string sql, Guid id)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue(id);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<bool> TableExistsAsync(NpgsqlConnection connection, string table)
    {
        await using var command = new NpgsqlCommand("SELECT to_regclass($1) IS NOT NULL", connection);
        command.Parameters.AddWithValue(table);
        return (bool)(await command.ExecuteScalarAsync())!;
    }

    private static async Task<bool> ColumnExistsAsync(NpgsqlConnection connection, string table, string column)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2)", connection);
        command.Parameters.AddWithValue(table);
        command.Parameters.AddWithValue(column);
        return (bool)(await command.ExecuteScalarAsync())!;
    }
}
