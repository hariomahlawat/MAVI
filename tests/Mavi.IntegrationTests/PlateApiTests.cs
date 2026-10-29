using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Api.Plates;
using Mavi.Application.Modules.Plates;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Mavi.Domain.Processing;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The plate lifecycle through the real API host and PostgreSQL (Stage 4 plan §7 PR-3; register rows
/// P7–P9): lease, fencing, evidence integrity, three-phase completion, supersession and default
/// derivation, bounded re-analysis, and failure isolation from the vision and attribute planes.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);

    /// <summary>Activation at T0, then a run that completes after it (so it is queued automatically).</summary>
    private static async Task<SeededRun> ActivateAndSeedAsync(PlateApiHost host, int persons = 1, int vehicles = 2, int crops = 2)
    {
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        return await host.World.SeedRunAsync(persons, vehicles, crops, completedAtUtc: host.World.Clock.GetUtcNow());
    }

    private static async Task<string?> CodeAsync(HttpResponseMessage response) => await VisualAttributeApiHost.ProblemCodeAsync(response);

    [Fact]
    public async Task ARunIsLeasedAnalysedPublishedAndReady()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host);
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        // Queueing is idempotent.
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);

        var unit = await host.LeaseAsync();
        // Only Vehicle Tracks are leased, each with its accepted crops in rank order.
        var vehicles = run.Tracks.Where(track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Vehicle).ToList();
        Assert.Equal(vehicles.Select(track => track.TrackId).ToHashSet(), unit.Lease.Tracks.Select(track => track.TrackId).ToHashSet());
        Assert.All(unit.Lease.Tracks, track => Assert.Equal([0, 1], track.Observations.Select(item => item.EvidenceRank)));
        Assert.Equal(host.PreferredFingerprint, unit.Lease.Identity.Fingerprint);

        // Lease-scoped evidence is served byte-exact, and refused for a Person crop.
        var crop = vehicles[0].Observations[0];
        using (var evidence = await host.EvidenceAsync(unit, crop.ObservationId))
        {
            Assert.Equal(HttpStatusCode.OK, evidence.StatusCode);
            Assert.Equal(crop.Bytes, await evidence.Content.ReadAsByteArrayAsync());
        }

        var person = run.Tracks.Single(track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Person).Observations[0];
        using (var refused = await host.EvidenceAsync(unit, person.ObservationId))
            Assert.Equal(PlateLifecycle_EvidenceForbidden, await CodeAsync(refused));

        var built = PlateCompletionBuilder.Build(unit.Lease);
        using var completed = await host.UploadAndCompleteAsync(unit, built);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var response = await completed.Content.ReadFromJsonAsync<PlateCompleteResponse>();
        Assert.Equal("completed", response!.Status);
        Assert.Equal(2, response.TracksAnalysed);

        await using (var db = host.World.Read())
        {
            var analysis = await db.PlateAnalyses.AsNoTracking().SingleAsync();
            Assert.Equal(PlateAnalysisStatus.Completed, analysis.Status);
            Assert.Equal(4, analysis.PlateObservationsRead);
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == analysis.PredictionArtifactId);
            Assert.Equal(ArtifactType.PlatePredictions, artifact.ArtifactType);
            Assert.Equal(built.Predictions, await File.ReadAllBytesAsync(host.World.EvidencePath(artifact.StorageKey)));
            var readings = await db.PlateReadings.AsNoTracking().ToListAsync();
            // Two kept readings per plate (0.8 and 0.6 reach the 0.5 floor); raw kept, normalised by the platform.
            Assert.Equal(8, readings.Count);
            Assert.All(readings.Where(item => item.Rank == 0), item =>
            {
                Assert.Equal("KA 01 AB 1234", item.RawText);
                Assert.Equal("KA01AB1234", item.NormalisedText);
                Assert.Equal("in-standard", item.FormatClass);
            });
            var texts = await db.PlateTrackTexts.AsNoTracking().ToListAsync();
            Assert.Equal(2, texts.Count);
            Assert.All(texts, text => Assert.Equal(("KA01AB1234", 2), (text.NormalisedText, text.SupportCount)));
            var outcomes = await db.PlateTrackOutcomes.AsNoTracking().ToListAsync();
            Assert.All(outcomes, outcome => Assert.Equal(PlateTrackOutcomeKind.Analysed, outcome.Outcome));
        }

        var readiness = await host.ReadinessAsync(run.RunId);
        Assert.Equal("Ready", readiness.GetProperty("state").GetString());

        // An exact replay is answered from what was committed; a different body conflicts.
        using (var replay = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var other = built.Request with { Provenance = built.Request.Provenance! with { ActualDevice = "cuda:0" } };
        using (var conflict = await host.CompleteAsync(unit, other))
            Assert.Equal("plate_completion_conflict", await CodeAsync(conflict));

        // No capability reached any log line, and no plate text did either.
        var logs = string.Join('\n', host.Logs.Entries.Select(entry => entry.Message));
        Assert.DoesNotContain(unit.Capability, logs, StringComparison.Ordinal);
        Assert.DoesNotContain("KA01AB1234", logs, StringComparison.Ordinal);
    }

    private const string PlateLifecycle_EvidenceForbidden = "plate_evidence_forbidden";

    [Fact]
    public async Task LeaseFencingRefusesAnotherCapabilityAnExpiredLeaseAndAReclaimedAttempt()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var first = await host.LeaseAsync();

        using (var wrong = await host.HeartbeatAsync(first, capability: new string('A', 43)))
            Assert.Equal(PlateAnalysis.LeaseInvalidCode, await CodeAsync(wrong));
        using (var ok = await host.HeartbeatAsync(first))
            Assert.Equal(HttpStatusCode.OK, ok.StatusCode);

        // The lease expires: evidence is refused, and another worker reclaims with a new attempt.
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        using (var late = await host.EvidenceAsync(first, run.Track(0).Observations[0].ObservationId))
            Assert.Equal(PlateAnalysis.LeaseInvalidCode, await CodeAsync(late));
        var second = await host.LeaseAsync("plates-02");
        Assert.Equal(2, second.Attempt);
        Assert.Equal(first.AnalysisId, second.AnalysisId);

        // The reclaimed attempt can neither upload nor complete.
        var built = PlateCompletionBuilder.Build(first.Lease);
        using (var upload = await host.UploadAsync(first, built.Predictions))
            Assert.Equal(PlateAnalysis.LeaseInvalidCode, await CodeAsync(upload));
        using (var complete = await host.CompleteAsync(first, built.Request))
            Assert.Equal(HttpStatusCode.Conflict, complete.StatusCode);

        // The new owner publishes.
        using var published = await host.UploadAndCompleteAsync(second, PlateCompletionBuilder.Build(second.Lease, workerId: "plates-02"));
        Assert.Equal(HttpStatusCode.OK, published.StatusCode);
    }

    [Fact]
    public async Task AnUnauthenticatedCompletionIsRefusedBeforeTheRunScopeIsRead()
    {
        // The unit row is held FOR UPDATE during Phase A; a caller without this attempt's capability must be
        // refused before the run scope (up to 10,000 Tracks) is read, so it cannot starve the real holder.
        var trace = new FinalizationWorld.SqlTrace();
        await using var host = await PlateApiHost.CreateAsync(fixture, T0, configureDbContext: options => options.AddInterceptors(trace));
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 2, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var built = PlateCompletionBuilder.Build(unit.Lease);
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        static bool ReadsScope(string sql) =>
            sql.Contains("plate_identity_activations", StringComparison.Ordinal) || sql.Contains("FROM tracks", StringComparison.Ordinal);
        var wrongCapability = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        // A malformed body too: a scope-dependent check would answer 400; authentication answers first.
        var malformed = built.Request with { Payload = built.Request.Payload! with { Tracks = [] } };
        foreach (var (body, capability) in new[]
                 {
                     (built.Request, wrongCapability),
                     (malformed, wrongCapability),
                     (built.Request with { AttemptCount = unit.Attempt + 1 }, unit.Capability),
                 })
        {
            trace.Clear();
            using var refused = await host.CompleteAsync(unit, body, capability);
            Assert.Equal(HttpStatusCode.Conflict, refused.StatusCode);
            Assert.Equal(PlateAnalysis.LeaseInvalidCode, await CodeAsync(refused));
            Assert.DoesNotContain(trace.Commands, ReadsScope);
        }

        // The real holder is unaffected and completes; the replay reads the scope only after authenticating.
        trace.Clear();
        using (var completed = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Contains(trace.Commands, ReadsScope);

        // On the committed unit, a foreign capability is a conflict without a scope read.
        trace.Clear();
        using (var conflict = await host.CompleteAsync(unit, built.Request, wrongCapability))
            Assert.Equal("plate_completion_conflict", await CodeAsync(conflict));
        Assert.DoesNotContain(trace.Commands, ReadsScope);
        using (var replay = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
    }

    [Fact]
    public async Task AReclaimBetweenSealAndPublicationPublishesNothing()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var built = PlateCompletionBuilder.Build(unit.Lease);
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        var (service, scope) = host.CompletionService(beforePhaseC: async _ =>
        {
            // The publication window lapses and another worker reclaims the unit.
            host.World.Clock.Advance(TimeSpan.FromMinutes(5));
            await host.LeaseAsync("plates-02");
        });
        using (scope)
        {
            var result = await service.CompleteAsync(unit.AnalysisId, unit.Capability, built.Request, CancellationToken.None);
            Assert.Equal(PlateAnalysis.StaleAttemptCode, result.Code);
        }

        await using var db = host.World.Read();
        Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
        Assert.Equal(PlateAnalysisStatus.Running, (await db.PlateAnalyses.AsNoTracking().SingleAsync()).Status);
    }

    [Fact]
    public async Task AnAmbiguousPublicationCommitPublishesNothingAndItsReplayPublishesExactlyOnce()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 2, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var built = PlateCompletionBuilder.Build(unit.Lease);
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        // Phase C writes every row and takes the barrier, then the commit is lost (an I/O failure in place of
        // its success): the publication transaction never commits.
        var (service, scope) = host.CompletionService(beforeCommit: () => throw new IOException("simulated loss of the commit"));
        using (scope)
        {
            var result = await service.CompleteAsync(unit.AnalysisId, unit.Capability, built.Request, CancellationToken.None);
            Assert.Equal((503, "plate_publication_ambiguous"), (result.HttpStatus, result.Code));
        }

        // Nothing partial is visible, read in one snapshot.
        Assert.Equal((0L, 0L, 0L), await PublishedStateAsync());
        Assert.Equal("Pending", (await host.ReadinessAsync((await host.UnitAsync(unit.AnalysisId)).ProcessingRunId)).GetProperty("state").GetString());

        // The worker replays the identical body: exactly one publication, and a second replay changes nothing.
        using (var completed = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var published = await PublishedStateAsync();
        // 2 outcomes, 4 plate observations, 8 kept readings, 2 Track texts (each Track reads one text on both crops).
        Assert.Equal((1L, 1L, 2L + 4L + 8L + 2L), published);
        var first = await host.UnitAsync(unit.AnalysisId);
        Assert.Equal(PlateAnalysisStatus.Completed, first.Status);

        using (var replay = await host.CompleteAsync(unit, built.Request))
        {
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
            Assert.Equal("completed", (await replay.Content.ReadFromJsonAsync<PlateCompleteResponse>())!.Status);
        }

        Assert.Equal(published, await PublishedStateAsync());
        var again = await host.UnitAsync(unit.AnalysisId);
        Assert.Equal((first.VisibilitySequence, first.CompletedAtUtc, first.PredictionArtifactId),
            (again.VisibilitySequence, again.CompletedAtUtc, again.PredictionArtifactId));
    }

    /// <summary>(published units, PlatePredictions artefacts, plate fact rows) in one snapshot.</summary>
    private async Task<(long Units, long Artefacts, long Facts)> PublishedStateAsync()
    {
        await using var connection = new Npgsql.NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new Npgsql.NpgsqlCommand("""
            SELECT (SELECT count(*) FROM plate_analyses WHERE status = 'Completed' AND visibility_sequence IS NOT NULL),
                   (SELECT count(*) FROM artifacts WHERE artifact_type = 'PlatePredictions'),
                   (SELECT count(*) FROM plate_track_outcomes) + (SELECT count(*) FROM plate_observations)
                 + (SELECT count(*) FROM plate_readings) + (SELECT count(*) FROM plate_track_texts)
            """, connection);
        await using var reader = await command.ExecuteReaderAsync();
        await reader.ReadAsync();
        return (reader.GetInt64(0), reader.GetInt64(1), reader.GetInt64(2));
    }

    [Fact]
    public async Task APublicationConstraintViolationIsRefusedForGoodAndPublishesNothing()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        // Stand-in for a platform defect: every outcome row now violates a CHECK constraint (SQLSTATE 23514).
        await using (var db = host.World.Read())
            await db.Database.ExecuteSqlRawAsync("ALTER TABLE plate_track_outcomes ADD CONSTRAINT ck_test_refuse_all CHECK (false) NOT VALID");

        using (var refused = await host.UploadAndCompleteAsync(unit, PlateCompletionBuilder.Build(unit.Lease)))
        {
            // Deterministic: replaying the same body cannot succeed, so it is not a transient 503.
            Assert.Equal(HttpStatusCode.UnprocessableEntity, refused.StatusCode);
            Assert.Equal(Mavi.Infrastructure.Plates.PlateCompletionService.PersistenceRefusedCode, await CodeAsync(refused));
        }

        await using (var db = host.World.Read())
        {
            Assert.Equal(PlateAnalysisStatus.Running, (await db.PlateAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.PlateObservations.AsNoTracking().ToListAsync());
            Assert.DoesNotContain(await db.Artifacts.AsNoTracking().ToListAsync(), x => x.ArtifactType == ArtifactType.PlatePredictions);
        }
    }

    [Fact]
    public async Task AQueuedUnitWithNoPermittedAttemptLeftIsFailedByTheSweep()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        // Requeued after attempt 3 under a higher limit, now above the configured MaximumAttempts (3): no claim can take it.
        await using (var db = host.World.Read())
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE plate_analyses SET attempt_count = 3, first_claimed_at_utc = {T0} WHERE status = 'Queued'");
        Assert.Equal(HttpStatusCode.NoContent, (await host.PostLeaseAsync("plates-01")).StatusCode);

        Assert.Equal(1, (await host.SweepAsync()).ExhaustedFailed);
        await using (var db = host.World.Read())
        {
            var unit = await db.PlateAnalyses.AsNoTracking().SingleAsync();
            Assert.Equal((PlateAnalysisStatus.Failed, PlateAnalysis.AttemptsExhaustedCode), (unit.Status, unit.FailureCode));
        }
    }

    [Fact]
    public async Task EvidenceThatDisagreesWithItsRecordIsAnAuthoritativeIntegrityIncident()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 2, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();

        // At rest, one crop lost a byte; another is gone.
        var shortened = run.Track(0).Observations[0];
        await File.WriteAllBytesAsync(host.World.EvidencePath(shortened.StorageKey), shortened.Bytes[..^1]);
        var missing = run.Track(1).Observations[0];
        File.Delete(host.World.EvidencePath(missing.StorageKey));

        using (var integrity = await host.EvidenceAsync(unit, shortened.ObservationId))
            Assert.Equal("plate_evidence_integrity_failed", await CodeAsync(integrity));
        using (var gone = await host.EvidenceAsync(unit, missing.ObservationId))
            Assert.Equal("plate_evidence_missing", await CodeAsync(gone));

        // The worker reports both Tracks Unavailable with the authoritative reasons; nothing is guessed.
        var built = PlateCompletionBuilder.Build(unit.Lease, (track, _) =>
            PlateCropSpec.Unavailable(unit.Lease.Tracks[track].TrackId == run.Track(0).TrackId ? "evidence_integrity_failed" : "evidence_missing"));
        using var completed = await host.UploadAndCompleteAsync(unit, built);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);

        await using (var db = host.World.Read())
        {
            var outcomes = await db.PlateTrackOutcomes.AsNoTracking().ToDictionaryAsync(x => x.TrackId);
            Assert.Equal("evidence_integrity_failed", outcomes[run.Track(0).TrackId].Reason);
            Assert.Equal("evidence_missing", outcomes[run.Track(1).TrackId].Reason);
            Assert.Empty(await db.PlateObservations.AsNoTracking().ToListAsync());
        }

        var health = host.Factory.Services.GetRequiredService<PlateIntegrityMonitor>().Current;
        Assert.Equal(2, health.EvidenceReadIncidents);
        Assert.Equal(2, health.CompletionIncidents);
        var json = await host.Client.GetFromJsonAsync<JsonElement>("/api/health");
        Assert.Equal(2, json.GetProperty("details").GetProperty("plateIntegrity").GetProperty("completionIncidents").GetInt64());
    }

    [Fact]
    public async Task AnUnavailableEvidenceClaimThatTheObjectAtRestContradictsPublishesNothing()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();

        // The crop is intact at rest, but the worker reports it missing.
        var built = PlateCompletionBuilder.Build(unit.Lease, (_, _) => PlateCropSpec.Unavailable("evidence_missing"));
        using (var refused = await host.UploadAndCompleteAsync(unit, built))
        {
            Assert.Equal(HttpStatusCode.UnprocessableEntity, refused.StatusCode);
            Assert.Equal(PlateContractRules.EvidenceClaimContradictedCode, await CodeAsync(refused));
        }

        await using (var db = host.World.Read())
        {
            Assert.Equal(PlateAnalysisStatus.Running, (await db.PlateAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
            Assert.DoesNotContain(await db.Artifacts.AsNoTracking().ToListAsync(), x => x.ArtifactType == ArtifactType.PlatePredictions);
        }

        Assert.Equal(0, host.Factory.Services.GetRequiredService<PlateIntegrityMonitor>().Current.CompletionIncidents);
        // The worker fails the attempt as retryable; the next attempt re-reads the evidence.
        Assert.True(PlateContractRules.FailureCodeRetryable[PlateContractRules.EvidenceClaimContradictedCode]);
        using (var failed = await host.FailAsync(unit, PlateContractRules.EvidenceClaimContradictedCode))
            Assert.Equal("requeued", (await failed.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());
    }

    [Theory]
    [InlineData("missing at rest, claimed corrupt", true, "evidence_integrity_failed")]
    [InlineData("shortened at rest, claimed missing", false, "evidence_missing")]
    public async Task AClaimMustNameWhatTheObjectAtRestShows(string scenario, bool deleteIt, string claimedReason)
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var crop = run.Track(0).Observations[0];
        if (deleteIt)
            File.Delete(host.World.EvidencePath(crop.StorageKey));
        else
            await File.WriteAllBytesAsync(host.World.EvidencePath(crop.StorageKey), crop.Bytes[..^1]);

        var built = PlateCompletionBuilder.Build(unit.Lease, (_, _) => PlateCropSpec.Unavailable(claimedReason));
        using var refused = await host.UploadAndCompleteAsync(unit, built);
        Assert.True(HttpStatusCode.UnprocessableEntity == refused.StatusCode, scenario);
        Assert.Equal(PlateContractRules.EvidenceClaimContradictedCode, await CodeAsync(refused));
        Assert.Equal(0, host.Factory.Services.GetRequiredService<PlateIntegrityMonitor>().Current.CompletionIncidents);
    }

    [Fact]
    public async Task AnIncidentConfirmedBeforeAnAmbiguousCommitIsCountedOnceAcrossTheReplay()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 2, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var missing = run.Track(0).Observations[0];
        File.Delete(host.World.EvidencePath(missing.StorageKey));
        var built = PlateCompletionBuilder.Build(unit.Lease, (track, _) => unit.Lease.Tracks[track].TrackId == run.Track(0).TrackId
            ? PlateCropSpec.Unavailable("evidence_missing")
            : PlateCropSpec.Scored(PlateCompletionBuilder.DefaultProposal));
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        var monitor = host.Factory.Services.GetRequiredService<PlateIntegrityMonitor>();

        var (service, scope) = host.CompletionService(beforeCommit: () => throw new IOException("simulated loss of the commit"));
        using (scope)
            Assert.Equal("plate_publication_ambiguous", (await service.CompleteAsync(unit.AnalysisId, unit.Capability, built.Request, CancellationToken.None)).Code);
        // The commit may have happened, so the confirmed incident is already counted.
        Assert.Equal(1, monitor.Current.CompletionIncidents);

        using (var replay = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using (var again = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, again.StatusCode);
        Assert.Equal(1, monitor.Current.CompletionIncidents);
    }

    [Fact]
    public async Task AConstraintViolationOnTheUnitsOwnUpdateIsRefusedForGoodAndTheWorkerReportsAPlatformRefusal()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        // Stand-in for a platform defect in the unit's own publication update (SQLSTATE 23514).
        await using (var db = host.World.Read())
            await db.Database.ExecuteSqlRawAsync("ALTER TABLE plate_analyses ADD CONSTRAINT ck_test_never_completed CHECK (status <> 'Completed') NOT VALID");

        using (var refused = await host.UploadAndCompleteAsync(unit, PlateCompletionBuilder.Build(unit.Lease)))
        {
            Assert.Equal(HttpStatusCode.UnprocessableEntity, refused.StatusCode);
            Assert.Equal(Mavi.Infrastructure.Plates.PlateCompletionService.PersistenceRefusedCode, await CodeAsync(refused));
        }

        await using (var db = host.World.Read())
        {
            Assert.Equal(PlateAnalysisStatus.Running, (await db.PlateAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
        }

        // The worker reports the platform's refusal with its own non-retryable code, not plate_output_invalid.
        Assert.False(PlateContractRules.FailureCodeRetryable["plate_publication_refused"]);
        using (var failed = await host.FailAsync(unit, "plate_publication_refused"))
            Assert.Equal("failed", (await failed.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());
        Assert.Equal("plate_publication_refused", (await host.UnitAsync(unit.AnalysisId)).FailureCode);
    }

    [Fact]
    public async Task IntegrityIncidentsAreCountedOnlyForAPublicationAndOncePerCrop()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var missing = run.Track(0).Observations[0];
        File.Delete(host.World.EvidencePath(missing.StorageKey));
        var monitor = host.Factory.Services.GetRequiredService<PlateIntegrityMonitor>();

        var built = PlateCompletionBuilder.Build(unit.Lease, (_, _) => PlateCropSpec.Unavailable("evidence_missing"));
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        // A completion refused after the artefact check (its digest disagrees with the staged bytes) counts nothing.
        var payload = built.Request.Payload!;
        var wrong = built.Request with
        {
            Payload = payload with { PredictionArtifact = payload.PredictionArtifact! with { Sha256 = new string('0', 64) } },
        };
        using (var refused = await host.CompleteAsync(unit, wrong))
            Assert.False(refused.IsSuccessStatusCode);
        Assert.Equal(0, monitor.Current.CompletionIncidents);

        using (var completed = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Equal(1, monitor.Current.CompletionIncidents);

        // The committed replay publishes nothing new and counts nothing new.
        using (var replay = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        Assert.Equal(1, monitor.Current.CompletionIncidents);
        await using var db = host.World.Read();
        Assert.Equal("evidence_missing", (await db.PlateTrackOutcomes.AsNoTracking().SingleAsync()).Reason);
    }

    [Fact]
    public async Task ATransientFailureIsRetriedAndATerminalOneFailsTheRunsReadiness()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var first = await host.LeaseAsync();
        using (var transient = await host.FailAsync(first, "plate_evidence_transport_failed", "connection reset"))
            Assert.Equal("requeued", (await transient.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());

        var second = await host.LeaseAsync();
        Assert.Equal(2, second.Attempt);
        using (var terminal = await host.FailAsync(second, "plate_output_invalid", "detector emitted 3 proposals"))
            Assert.Equal("failed", (await terminal.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());

        var readiness = await host.ReadinessAsync(run.RunId);
        Assert.Equal("Failed", readiness.GetProperty("state").GetString());
        Assert.Equal("plate_output_invalid", readiness.GetProperty("detail").GetString());
    }

    [Fact]
    public async Task AnArtefactThatDisagreesWithTheCompletionPublishesNothing()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var honest = PlateCompletionBuilder.Build(unit.Lease);
        // The artefact records a different raw text than the completion's facts.
        var tampered = Encoding.UTF8.GetBytes(Encoding.UTF8.GetString(honest.Predictions).Replace("KA01AB1284", "KA01AB1285", StringComparison.Ordinal));
        var request = honest.Request with
        {
            Payload = honest.Request.Payload! with
            {
                PredictionArtifact = new PlateArtifactDescriptorContract(PlateContractRules.PredictionsMediaType, tampered.LongLength,
                    Convert.ToHexStringLower(SHA256.HashData(tampered))),
            },
        };
        using var completed = await host.UploadAndCompleteAsync(unit, new BuiltPlateCompletion(tampered, request));
        Assert.Equal("plate_predictions_invalid", await CodeAsync(completed));

        await using var db = host.World.Read();
        Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
        Assert.Equal(0, await db.Artifacts.AsNoTracking().CountAsync(x => x.ArtifactType == ArtifactType.PlatePredictions));
    }

    [Fact]
    public async Task AnUploadIsVerifiedAgainstItsDeclaredDigest()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        using var mismatch = await host.UploadAsync(unit, Encoding.UTF8.GetBytes("{}\n"), new string('0', 64));
        Assert.Equal(PlateContractRules.ArtifactIntegrityFailedCode, await CodeAsync(mismatch));
    }

    [Fact]
    public async Task ANewIdentitySupersedesOnlyOnCompletionAndRollbackReDerivesTheDefault()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        var identityA = host.PreferredFingerprint;
        var unitA = await host.LeaseAsync();
        using (var publishedA = await host.UploadAndCompleteAsync(unitA, PlateCompletionBuilder.Build(unitA.Lease)))
            Assert.Equal(HttpStatusCode.OK, publishedA.StatusCode);

        // Identity B (another OCR pack), activated later: history is Stale until explicitly re-analysed, never automatically.
        host.World.Clock.Advance(TimeSpan.FromMinutes(1));
        await host.RestartWithAsync(identityB: true);
        await host.RunCycleAsync();
        Assert.NotEqual(identityA, host.PreferredFingerprint);
        var stale = await host.ReadinessAsync(run.RunId);
        Assert.Equal("Stale", stale.GetProperty("state").GetString());
        Assert.Equal("preferred_identity_not_analysed", stale.GetProperty("detail").GetString());

        using (var requested = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }))
        {
            Assert.Equal(HttpStatusCode.Accepted, requested.StatusCode);
            Assert.Equal(1, (await requested.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("queued").GetInt32());
        }

        // Still Stale while B runs: A's facts are not current under B, and B has none yet.
        var unitB = await host.LeaseAsync();
        Assert.Equal("Stale", (await host.ReadinessAsync(run.RunId)).GetProperty("state").GetString());
        using (var publishedB = await host.UploadAndCompleteAsync(unitB, PlateCompletionBuilder.Build(unitB.Lease)))
            Assert.Equal(HttpStatusCode.OK, publishedB.StatusCode);
        Assert.Equal(PlateAnalysisStatus.Superseded, (await host.UnitAsync(unitA.AnalysisId)).Status);
        var ready = await host.ReadinessAsync(run.RunId);
        Assert.Equal("Ready", ready.GetProperty("state").GetString());
        Assert.Equal(unitB.AnalysisId, ready.GetProperty("defaultAnalysisId").GetGuid());

        // Rollback to A: no new unit, no rewritten label — A's facts are the default again.
        await host.RestartWithAsync(identityB: false);
        var rolledBack = await host.ReadinessAsync(run.RunId);
        Assert.Equal("Ready", rolledBack.GetProperty("state").GetString());
        Assert.Equal(unitA.AnalysisId, rolledBack.GetProperty("defaultAnalysisId").GetGuid());
    }

    [Fact]
    public async Task ReanalysisIsExplicitBoundedAndIdempotent()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0,
            configuration: new Dictionary<string, string?> { ["Plates:MaximumRunsPerReanalysisRequest"] = "2" });
        // Three historical runs, completed before the identity was activated: never queued automatically.
        var runs = new List<SeededRun>();
        for (var index = 0; index < 3; index++) runs.Add(await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddMinutes(-10 + index)));
        var personOnly = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: T0.AddMinutes(-5));
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
        Assert.Equal("historical_run_not_queued", (await host.ReadinessAsync(runs[0].RunId)).GetProperty("detail").GetString());
        Assert.Equal("NotApplicable", (await host.ReadinessAsync(personOnly.RunId)).GetProperty("state").GetString());

        // Exactly one scope; at most the configured number of runs; never partially.
        using (var both = await host.ReanalysisAsync(new { processingRunIds = new[] { runs[0].RunId }, cameraId = host.World.CameraId, fromUtc = T0.AddDays(-1), toUtc = T0 }))
            Assert.Equal("plate_reanalysis_scope_invalid", await CodeAsync(both));
        using (var tooMany = await host.ReanalysisAsync(new { processingRunIds = runs.Select(run => run.RunId).ToArray() }))
            Assert.Equal("plate_reanalysis_scope_invalid", await CodeAsync(tooMany));
        using (var window = await host.ReanalysisAsync(new { cameraId = host.World.CameraId, fromUtc = T0.AddDays(-1), toUtc = T0.AddDays(1) }))
            Assert.Equal("plate_reanalysis_too_many_runs", await CodeAsync(window));
        await using (var db = host.World.Read())
            Assert.Equal(0, await db.PlateAnalyses.CountAsync());
        using (var unknown = await host.ReanalysisAsync(new { processingRunIds = new[] { Guid.NewGuid() } }))
            Assert.Equal(HttpStatusCode.NotFound, unknown.StatusCode);

        using (var first = await host.ReanalysisAsync(new { processingRunIds = new[] { runs[0].RunId, personOnly.RunId } }))
        {
            var body = await first.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal((2, 1, 0, 1), (body.GetProperty("runsMatched").GetInt32(), body.GetProperty("queued").GetInt32(),
                body.GetProperty("alreadyQueued").GetInt32(), body.GetProperty("notEligible").GetInt32()));
        }

        using (var again = await host.ReanalysisAsync(new { processingRunIds = new[] { runs[0].RunId } }))
        {
            var body = await again.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal((0, 1), (body.GetProperty("queued").GetInt32(), body.GetProperty("alreadyQueued").GetInt32()));
        }

        Assert.Equal("Pending", (await host.ReadinessAsync(runs[0].RunId)).GetProperty("state").GetString());
    }

    [Fact]
    public async Task ReanalysisRequiresAnOperatorAndEveryRefusalIsAudited()
    {
        // ADR-010 (owner decision S3-2): the operator policy replaced the interim operator key. An anonymous request is
        // challenged and a Windows account that is not an operator is forbidden; each refusal reaches the handler's
        // audit (event 2126) and queues nothing. A form-shaped request never binds: the framework refuses it (415)
        // before the handler, so it is neither queued nor audited.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddMinutes(-10));
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);

        using (var anonymous = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }, user: null))
        {
            Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
            Assert.Contains("Negotiate", anonymous.Headers.WwwAuthenticate.ToString(), StringComparison.Ordinal);
        }

        using (var outsider = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }, "HOST\\mallory", groups: "HOST\\Guests"))
        {
            Assert.Equal(HttpStatusCode.Forbidden, outsider.StatusCode);
            Assert.Equal(PlateReanalysisAuthorisation.ForbiddenCode, await CodeAsync(outsider));
        }

        using (var form = new HttpRequestMessage(HttpMethod.Post, "/api/plates/reanalysis")
               {
                   Content = new FormUrlEncodedContent([new KeyValuePair<string, string>("processingRunIds", run.RunId.ToString())]),
               })
        {
            TestOperatorIdentity.As(form, TestOperatorIdentity.Operator, TestOperatorIdentity.OperatorSid);
            using var formShaped = await host.Client.SendAsync(form);
            Assert.Equal(HttpStatusCode.UnsupportedMediaType, formShaped.StatusCode);
        }

        await using (var db = host.World.Read())
        {
            Assert.Equal(0, await db.PlateAnalyses.CountAsync());
            Assert.Equal(0, await db.AuditEntries.CountAsync());
        }
        Assert.Equal(1, host.Logs.Entries.Count(entry =>
            entry.EventId.Id == 2126 && entry.Message.Contains(PlateReanalysisAuthorisation.UnauthorisedCode, StringComparison.Ordinal)));
        Assert.Equal(1, host.Logs.Entries.Count(entry =>
            entry.EventId.Id == 2126 && entry.Message.Contains(PlateReanalysisAuthorisation.ForbiddenCode, StringComparison.Ordinal)));

        // A member of the operator group is an operator; the accepted request is attributed to their account.
        using (var member = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }, "HOST\\bob",
                   sid: "S-1-5-21-1-2-3-1002", groups: TestOperatorIdentity.OperatorGroup))
        {
            Assert.Equal(HttpStatusCode.Accepted, member.StatusCode);
            Assert.Equal(1, (await member.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("queued").GetInt32());
        }

        await using (var db = host.World.Read())
        {
            var entry = Assert.Single(await db.AuditEntries.ToListAsync());
            Assert.Equal(("S-1-5-21-1-2-3-1002", "HOST\\bob", "windows-negotiate"),
                (entry.OperatorId, entry.OperatorDisplayName, entry.IdentitySource));
            Assert.Equal(("plates.reanalysis-requested", "plate-reanalysis", "runs"), (entry.Action, entry.SubjectType, entry.SubjectId));
            Assert.Equal(host.World.Clock.GetUtcNow(), entry.RecordedAtUtc);
        }
    }

    [Fact]
    public async Task AReanalysisTheLifecycleRefusesLeavesNoAuditEntry()
    {
        // The audit entry and the queueing commit together: a request that queues nothing records no attributable action.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);

        using (var unknown = await host.ReanalysisAsync(new { processingRunIds = new[] { Guid.NewGuid() } }))
            Assert.Equal((HttpStatusCode.NotFound, "processing_run_not_found"), (unknown.StatusCode, await CodeAsync(unknown)));

        await using var db = host.World.Read();
        Assert.Equal(0, await db.AuditEntries.CountAsync());
        Assert.Equal(1, host.Logs.Entries.Count(entry =>
            entry.EventId.Id == 2126 && entry.Message.Contains("processing_run_not_found", StringComparison.Ordinal)));
    }

    [Fact]
    public async Task OverlappingRequestsForOneRunQueueItOnceAndBothAreRecorded()
    {
        // Each request queues inside its audit transaction, so the second insert of a run waits on the first request's
        // uncommitted row and then meets the unique index. The gate holds both requests at their first save until both
        // have passed the "already queued?" check, so the conflict is certain: it must roll back to its savepoint
        // (not abort the transaction), count the run as already queued and still commit the request's audit entry.
        var gate = new SaveGate(2);
        await using var host = await PlateApiHost.CreateAsync(fixture, T0, configureDbContext: options => options.AddInterceptors(gate));
        var run = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddMinutes(-10));

        var responses = await Task.WhenAll(
            host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }),
            host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } }));
        try
        {
            Assert.All(responses, response => Assert.Equal(HttpStatusCode.Accepted, response.StatusCode));
            var bodies = await Task.WhenAll(responses.Select(response => response.Content.ReadFromJsonAsync<JsonElement>()));
            Assert.Equal(1, bodies.Sum(body => body.GetProperty("queued").GetInt32()));
            Assert.Equal(1, bodies.Sum(body => body.GetProperty("alreadyQueued").GetInt32()));
        }
        finally
        {
            foreach (var response in responses)
                response.Dispose();
        }

        await using var db = host.World.Read();
        Assert.Equal(1, await db.PlateAnalyses.CountAsync());
        Assert.Equal(2, await db.AuditEntries.CountAsync(entry => entry.Action == "plates.reanalysis-requested"));
    }

    /// <summary>Holds the first plate-analysis insert of each of <c>parties</c> requests until all of them reach it.</summary>
    private sealed class SaveGate(int parties) : Microsoft.EntityFrameworkCore.Diagnostics.SaveChangesInterceptor
    {
        private readonly TaskCompletionSource _all = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _arrived;

        public override async ValueTask<Microsoft.EntityFrameworkCore.Diagnostics.InterceptionResult<int>> SavingChangesAsync(
            Microsoft.EntityFrameworkCore.Diagnostics.DbContextEventData eventData,
            Microsoft.EntityFrameworkCore.Diagnostics.InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            var inserting = eventData.Context!.ChangeTracker.Entries<Mavi.Domain.Plates.PlateAnalysis>()
                .Any(entry => entry.State == EntityState.Added);
            if (inserting && !_all.Task.IsCompleted)
            {
                if (Interlocked.Increment(ref _arrived) >= parties)
                    _all.TrySetResult();
                await _all.Task.WaitAsync(TimeSpan.FromSeconds(30), cancellationToken);
            }

            return result;
        }
    }

    [Theory]
    [InlineData("disabled")]
    [InlineData("windows-negotiate")]
    public async Task ReanalysisFailsClosedWithoutAnOperatorIdentity(string mode)
    {
        // Identity:Mode disabled (the default outside the PoC), or Windows identity with no operator configured.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0, configuration: new Dictionary<string, string?>
        {
            ["Identity:Mode"] = mode,
            ["Identity:Operators:AuthorizedUsers:0"] = string.Empty,
            ["Identity:Operators:AuthorizedGroups:0"] = string.Empty,
        });
        var run = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddMinutes(-10));

        using var refused = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } });

        Assert.Equal(HttpStatusCode.Forbidden, refused.StatusCode);
        Assert.Equal(PlateReanalysisAuthorisation.NotConfiguredCode, await CodeAsync(refused));
        await using var db = host.World.Read();
        Assert.Equal(0, await db.PlateAnalyses.CountAsync());
        Assert.Equal(1, host.Logs.Entries.Count(entry =>
            entry.EventId.Id == 2126 && entry.Message.Contains(PlateReanalysisAuthorisation.NotConfiguredCode, StringComparison.Ordinal)));
    }

    [Fact]
    public async Task WithPlatesDisabledTheAuthorityLoopKeepsRunningAndGovernsWhatExists()
    {
        // PoC S3, C4.2: Plates:Enabled=false no longer halts the authority loop. Nothing new is activated or queued
        // (automatically or on request), but the hosted loop itself, not a test-driven cycle, keeps iterating: it fails
        // a unit past its deadline and, on a later iteration, reclaims its staging, so disabling plates never strands
        // a lease or its bytes.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host, persons: 0, vehicles: 1, crops: 1);
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        var unit = await host.LeaseAsync();
        using (var staged = await host.UploadAsync(unit, PlateCompletionBuilder.Build(unit.Lease).Predictions))
            Assert.Equal(HttpStatusCode.OK, staged.StatusCode);

        await host.RestartWithAsync(identityB: false, configuration: new Dictionary<string, string?>
        {
            ["Plates:Enabled"] = "false",
            // The loop's timer is real time (the test clock only moves the platform's notion of "now").
            ["Plates:ReconcileIntervalSeconds"] = "1",
        });
        // Disabled analysis queues nothing on request either.
        using (var disabled = await host.ReanalysisAsync(new { processingRunIds = new[] { unit.Lease.ProcessingRunId } }))
            Assert.Equal((HttpStatusCode.Conflict, "plate_analysis_disabled"), (disabled.StatusCode, await CodeAsync(disabled)));
        // The refusal is audited (event 2126) and records no attributable action.
        Assert.Equal(1, host.Logs.Entries.Count(entry =>
            entry.EventId.Id == 2126 && entry.Message.Contains("plate_analysis_disabled", StringComparison.Ordinal)));
        await using (var audited = host.World.Read())
            Assert.Equal(0, await audited.AuditEntries.CountAsync());
        // A run that would be queued automatically if analysis were enabled.
        var eligible = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: host.World.Clock.GetUtcNow().AddSeconds(1));
        host.World.Clock.Advance(TimeSpan.FromHours(6) + TimeSpan.FromMinutes(5));

        var staging = Path.Combine(host.World.MediaRoot, PlateStagingLayout.RootDirectoryName, unit.AnalysisId.ToString("D"));
        Assert.True(Directory.Exists(staging));

        // Only the hosted loop runs from here on: no cycle is driven by the test.
        var loop = host.Factory.Services.GetRequiredService<PlateHostedService>();
        await loop.StartAsync(CancellationToken.None);
        try
        {
            var giveUpAtUtc = DateTime.UtcNow.AddSeconds(30);
            while ((await host.UnitAsync(unit.AnalysisId)).Status != PlateAnalysisStatus.Failed && DateTime.UtcNow < giveUpAtUtc)
                await Task.Delay(100);
            var failed = await host.UnitAsync(unit.AnalysisId);
            Assert.Equal((PlateAnalysisStatus.Failed, PlateAnalysis.DeadlineExceededCode), (failed.Status, failed.FailureCode));

            // A later iteration of the same loop, once the staging grace has passed, reclaims the unit's staging.
            host.World.Clock.Advance(TimeSpan.FromMinutes(16));
            giveUpAtUtc = DateTime.UtcNow.AddSeconds(30);
            while (Directory.Exists(staging) && DateTime.UtcNow < giveUpAtUtc)
                await Task.Delay(100);
            Assert.False(Directory.Exists(staging), "the hosted loop kept running and reclaimed the staging");
        }
        finally
        {
            await loop.StopAsync(CancellationToken.None);
        }

        Assert.Contains(host.Logs.Entries, entry => entry.EventId.Id == 2133);
        Assert.DoesNotContain(host.Logs.Entries, entry => entry.EventId.Id == 2132);
        await using var db = host.World.Read();
        Assert.Equal(0, await db.PlateAnalyses.CountAsync(item => item.ProcessingRunId == eligible.RunId));
    }

    [Fact]
    public async Task ACropAbstainedForAnOcrOutputFaultKeepsItsProposalsAndTheRestOfTheRunPublishes()
    {
        // The worker abstains a crop whose recogniser emitted two equal readings (no strict rank order):
        // ocr_output_invalid, its proposals kept without a plate. One bad crop never fails the run.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 0, vehicles: 2, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var faulty = (Track: 0, Crop: 0);
        var built = PlateCompletionBuilder.Build(unit.Lease, (track, crop) => (track, crop) == faulty
            ? PlateCropSpec.AbstainedWithProposals("ocr_output_invalid", PlateCompletionBuilder.DefaultProposal,
                new PlateProposal(120, 20, 50, 12, 0.4, []))
            : PlateCropSpec.Scored(PlateCompletionBuilder.DefaultProposal));

        using (var completed = await host.UploadAndCompleteAsync(unit, built))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Equal("Ready", (await host.ReadinessAsync(run.RunId)).GetProperty("state").GetString());

        await using var db = host.World.Read();
        var outcomes = await db.PlateTrackOutcomes.AsNoTracking().ToListAsync();
        Assert.Equal(2, outcomes.Count);
        Assert.All(outcomes, outcome => Assert.Equal(PlateTrackOutcomeKind.Analysed, outcome.Outcome));
        // Three crops read a plate; the abstained crop has no plate observation.
        var faultyCrop = unit.Lease.Tracks[faulty.Track].Observations[faulty.Crop].ObservationId;
        var observations = await db.PlateObservations.AsNoTracking().ToListAsync();
        Assert.Equal(3, observations.Count);
        Assert.DoesNotContain(observations, item => item.SourceObservationId == faultyCrop);
        // The sealed artefact keeps the abstained crop's two proposals.
        var analysis = await db.PlateAnalyses.AsNoTracking().SingleAsync();
        var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == analysis.PredictionArtifactId);
        using var sealedPredictions = JsonDocument.Parse(await File.ReadAllBytesAsync(host.World.EvidencePath(artifact.StorageKey)));
        var crop = sealedPredictions.RootElement.GetProperty("tracks").EnumerateArray().SelectMany(track => track.GetProperty("crops").EnumerateArray())
            .Single(item => item.GetProperty("observationId").GetGuid() == faultyCrop);
        Assert.Equal(("abstained", "ocr_output_invalid", 2), (crop.GetProperty("status").GetString(), crop.GetProperty("reason").GetString(),
            crop.GetProperty("detections").GetArrayLength()));
    }

    [Fact]
    public async Task APublishedAnalysisHasExactlyOneOutcomeForEveryLeasedVehicleTrack()
    {
        // Owner decision 2026-10-13: "Ready with a Vehicle Track that has no outcome" must be impossible.
        await using var host = await PlateApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 1, vehicles: 3, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        // Track 0 analysed, track 1 unavailable (every crop missing at rest), track 2 analysed.
        var gone = run.Tracks.Single(x => x.TrackId == unit.Lease.Tracks[1].TrackId);
        foreach (var observation in gone.Observations)
            File.Delete(host.World.EvidencePath(observation.StorageKey));
        var built = PlateCompletionBuilder.Build(unit.Lease,
            (track, _) => track == 1 ? PlateCropSpec.Unavailable("evidence_missing") : PlateCropSpec.Scored(PlateCompletionBuilder.DefaultProposal));
        using (var uploaded = await host.UploadAsync(unit, built.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        var payload = built.Request.Payload!;
        var tracks = payload.Tracks!;
        PlateCompleteRequest With(IReadOnlyList<PlateTrackResultContract> replaced) =>
            built.Request with { Payload = payload with { Tracks = replaced } };

        // A completion that leaves a leased Track without an outcome, or gives one Track two, is refused
        // before anything is published.
        foreach (var broken in new[]
                 {
                     With([tracks[0], tracks[2]]),
                     With([tracks[0], tracks[0], tracks[2]]),
                     With([tracks[0], tracks[1] with { TrackId = run.Tracks.Single(x => x.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Person).TrackId }, tracks[2]]),
                     With([tracks[0], tracks[1] with { Outcome = null }, tracks[2]]),
                 })
        {
            using var refused = await host.CompleteAsync(unit, broken);
            Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
            var code = await CodeAsync(refused);
            Assert.True(code is "plate_track_coverage_invalid" or "plate_track_outcome_invalid", code);
            await using var db = host.World.Read();
            Assert.Equal(PlateAnalysisStatus.Running, (await db.PlateAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
            Assert.NotEqual("Ready", (await host.ReadinessAsync(run.RunId)).GetProperty("state").GetString());
        }

        using (var completed = await host.CompleteAsync(unit, built.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Equal("Ready", (await host.ReadinessAsync(run.RunId)).GetProperty("state").GetString());

        await using (var db = host.World.Read())
        {
            var vehicles = run.Tracks.Where(x => x.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Vehicle).Select(x => x.TrackId).ToHashSet();
            var outcomes = await db.PlateTrackOutcomes.AsNoTracking().Where(x => x.AnalysisId == unit.AnalysisId).ToListAsync();
            // A bijection: one outcome per leased Vehicle Track, none for anything else.
            Assert.Equal(vehicles.Count, outcomes.Count);
            Assert.Equal(vehicles, outcomes.Select(x => x.TrackId).ToHashSet());
            Assert.Equal(2, outcomes.Count(x => x.Outcome == PlateTrackOutcomeKind.Analysed));
            Assert.Equal("evidence_missing", Assert.Single(outcomes, x => x.Outcome == PlateTrackOutcomeKind.Unavailable).Reason);
        }
    }

    [Fact]
    public async Task APlateCrashOrExhaustionLeavesTheRunTracksAndAttributeUnitsUntouched()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0,
            configuration: new Dictionary<string, string?> { ["Plates:MaximumAttempts"] = "1" });
        var run = await ActivateAndSeedAsync(host, persons: 1, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        // An attribute unit of the same run, queued under its own plane.
        await using (var db = host.World.Read())
        {
            db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(run.RunId, VisualAttributeTestIdentity.Fields(), host.World.Clock.GetUtcNow()));
            await db.SaveChangesAsync();
        }

        (ProcessingRunStatus Status, long? Visibility, int Tracks, int Observations) Snapshot(Mavi.Infrastructure.Persistence.MaviDbContext db) => (
            db.ProcessingRuns.AsNoTracking().Single(x => x.Id == run.RunId).Status,
            db.ProcessingRuns.AsNoTracking().Single(x => x.Id == run.RunId).VisibilitySequence,
            db.Tracks.AsNoTracking().Count(x => x.ProcessingRunId == run.RunId),
            db.Observations.AsNoTracking().Count());
        (ProcessingRunStatus, long?, int, int) before;
        await using (var db = host.World.Read()) before = Snapshot(db);

        // The worker takes the lease and dies (no heartbeat, no failure call): the only attempt is exhausted.
        var unit = await host.LeaseAsync();
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        Assert.Equal(1, (await host.SweepAsync()).ExhaustedFailed);
        Assert.Equal(PlateAnalysisStatus.Failed, (await host.UnitAsync(unit.AnalysisId)).Status);

        await using (var db = host.World.Read())
        {
            Assert.Equal(before, Snapshot(db));
            Assert.Equal(VisualAttributeAnalysisStatus.Queued, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.PlateTrackOutcomes.AsNoTracking().ToListAsync());
        }

        Assert.Equal("Failed", (await host.ReadinessAsync(run.RunId)).GetProperty("state").GetString());
    }

    [Fact]
    public async Task WithoutAReleaseReadinessIsNotConfiguredAndNothingIsQueued()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, T0, configured: false);
        var run = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0);
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
        var readiness = await host.ReadinessAsync(run.RunId);
        Assert.Equal("NotConfigured", readiness.GetProperty("state").GetString());
        Assert.Equal("plate_release_not_configured", readiness.GetProperty("detail").GetString());
        using var reanalysis = await host.ReanalysisAsync(new { processingRunIds = new[] { run.RunId } });
        Assert.Equal("plate_not_configured", await CodeAsync(reanalysis));
    }

    [Theory]
    [InlineData("Development", null, false)]
    [InlineData("Testing", null, false)]
    [InlineData("Production", null, true)]
    [InlineData("Staging", null, true)]
    // A platform built for poc-single-host runs only the plan-D4 release, never the fixture.
    [InlineData("PoC", "poc-single-host", true)]
    public void TheDevelopmentOnlyFixtureIsRefusedOutsideDevelopmentAndTesting(string environment, string? profile, bool refused)
    {
        var definition = Mavi.Application.Modules.Plates.Release.PlateReleaseParser.Parse(
            PlateReleaseFixture.BindingBytes(identityB: false),
            () => File.ReadAllBytes(PlateReleaseFixture.PipelineProfile),
            name => File.ReadAllBytes(Path.Combine(PlateReleaseFixture.FixtureDirectory, name))).Definition!;
        var host = new FixedEnvironment(environment);
        if (refused)
            Assert.Equal(PlateReleaseStartup.FixtureForbiddenCode,
                Assert.Throws<InvalidOperationException>(() => PlateReleaseStartup.RequireAllowed(definition, host, profile)).Message);
        else
            PlateReleaseStartup.RequireAllowed(definition, host, profile);
    }

    [Theory]
    [InlineData("Development", null, false)]
    [InlineData("Testing", null, false)]
    [InlineData("Production", null, true)]
    [InlineData("Staging", null, true)]
    // The profile is the build's (MaviDeploymentProfile), never configuration: an ordinary build is refused.
    [InlineData("PoC", null, true)]
    // PoC S3 (C4.1): a platform built for poc-single-host (ADR-020, Development evidence class) binds the pilot pair.
    [InlineData("PoC", "poc-single-host", false)]
    public void TheCommittedDevelopmentPilotReleaseIsRefusedOutsideDevelopmentTestingAndThePocProfile(string environment, string? profile, bool refused)
    {
        // Issue #225: the real-model pilot profile is developmentOnly, so Production refuses it exactly as the fixture.
        var root = VisualAttributeReleaseFixture.Root;
        var profileDirectory = Path.Combine(root, "src", "vision", "config", "plates");
        var definition = Mavi.Application.Modules.Plates.Release.PlateReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(root, "src", "vision", "config", "components", "development-plates-onnx-pilot-v1.json")),
            () => File.ReadAllBytes(Path.Combine(profileDirectory, "development-plates-onnx-pilot-v1.json")),
            name => File.ReadAllBytes(Path.Combine(profileDirectory, name))).Definition!;
        // The PoC allowance names exactly this identity; re-deriving it here keeps the constant honest.
        Assert.Equal(PlateReleaseStartup.PocPlateIdentityFingerprint, definition.Identity.Fingerprint);
        var host = new FixedEnvironment(environment);
        if (refused)
            Assert.Equal(PlateReleaseStartup.FixtureForbiddenCode,
                Assert.Throws<InvalidOperationException>(() => PlateReleaseStartup.RequireAllowed(definition, host, profile)).Message);
        else
            PlateReleaseStartup.RequireAllowed(definition, host, profile);
    }

    private sealed class FixedEnvironment(string name) : Microsoft.Extensions.Hosting.IHostEnvironment
    {
        public string EnvironmentName { get; set; } = name;
        public string ApplicationName { get; set; } = "Mavi.Api";
        public string ContentRootPath { get; set; } = string.Empty;
        public Microsoft.Extensions.FileProviders.IFileProvider ContentRootFileProvider { get; set; } = null!;
    }
}
