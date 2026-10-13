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
    [InlineData("Development", false)]
    [InlineData("Testing", false)]
    [InlineData("Production", true)]
    [InlineData("Staging", true)]
    public void TheDevelopmentOnlyFixtureIsRefusedOutsideDevelopmentAndTesting(string environment, bool refused)
    {
        var definition = Mavi.Application.Modules.Plates.Release.PlateReleaseParser.Parse(
            PlateReleaseFixture.BindingBytes(identityB: false),
            () => File.ReadAllBytes(PlateReleaseFixture.PipelineProfile),
            name => File.ReadAllBytes(Path.Combine(PlateReleaseFixture.FixtureDirectory, name))).Definition!;
        var host = new FixedEnvironment(environment);
        if (refused)
            Assert.Equal(PlateReleaseStartup.FixtureForbiddenCode,
                Assert.Throws<InvalidOperationException>(() => PlateReleaseStartup.RequireAllowed(definition, host)).Message);
        else
            PlateReleaseStartup.RequireAllowed(definition, host);
    }

    private sealed class FixedEnvironment(string name) : Microsoft.Extensions.Hosting.IHostEnvironment
    {
        public string EnvironmentName { get; set; } = name;
        public string ApplicationName { get; set; } = "Mavi.Api";
        public string ContentRootPath { get; set; } = string.Empty;
        public Microsoft.Extensions.FileProviders.IFileProvider ContentRootFileProvider { get; set; } = null!;
    }
}
