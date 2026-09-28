using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Media;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The attribute control plane over real HTTP (S2b plan §9–§13): header-only capability,
/// evidence authorisation and integrity, upload staging, completion and route bounds.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    /// <summary>A host with the preferred identity activated and one queued run.</summary>
    private async Task<(VisualAttributeApiHost Host, SeededRun Run)> HostWithQueuedRunAsync(int persons = 2, int vehicles = 1, int observations = 2)
    {
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var run = await host.World.SeedRunAsync(persons, vehicles, observations, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        return (host, run);
    }

    // --- Lease ------------------------------------------------------------------------------

    [Fact]
    public async Task TheCapabilityTravelsOnlyInTheResponseHeader()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;

        using var response = await host.PostLeaseAsync("attributes-01");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var capability = Assert.Single(response.Headers.GetValues(VisualAttributeContractRules.CapabilityHeader));
        Assert.Equal(43, capability.Length);
        Assert.True(response.Headers.CacheControl?.NoStore);
        var body = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain(capability, body, StringComparison.Ordinal);
        Assert.DoesNotContain("leaseToken", body, StringComparison.OrdinalIgnoreCase);
        var lease = await response.Content.ReadFromJsonAsync<VisualAttributeLeaseContract>();
        Assert.Equal(run.RunId, lease!.ProcessingRunId);
        Assert.Equal(3, lease.Tracks.Count);
        Assert.All(lease.Tracks, track => Assert.Equal(2, track.Observations.Count));

        // Nothing is left to lease: no body, no header.
        using var empty = await host.PostLeaseAsync("attributes-02");
        Assert.Equal(HttpStatusCode.NoContent, empty.StatusCode);
        Assert.False(empty.Headers.Contains(VisualAttributeContractRules.CapabilityHeader));
    }

    [Fact]
    public async Task ALeaseRequestCarryingACapabilityOrABodyTokenIsRefused()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var body = new { schemaVersion = VisualAttributeContractRules.SchemaVersion, workerId = "attributes-01", identityFingerprint = host.PreferredFingerprint };

        using (var withHeader = await host.SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/lease", new string('A', 43), body))
        {
            Assert.Equal(HttpStatusCode.BadRequest, withHeader.StatusCode);
            Assert.Equal("visual_attribute_capability_unexpected", await VisualAttributeApiHost.ProblemCodeAsync(withHeader));
        }

        using (var withBodyToken = await host.SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/lease", null, new
        {
            schemaVersion = VisualAttributeContractRules.SchemaVersion, workerId = "attributes-01",
            identityFingerprint = host.PreferredFingerprint, leaseToken = new string('A', 43),
        }))
            Assert.Equal(HttpStatusCode.BadRequest, withBodyToken.StatusCode);

        // Neither refused request consumed the unit.
        await using var db = host.World.Read();
        Assert.Equal(0, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).AttemptCount);
    }

    [Fact]
    public async Task AWorkerOfAnotherIdentityLeasesNothing()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;

        using var response = await host.PostLeaseAsync("attributes-01", new string('9', 64));

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        await using var db = host.World.Read();
        Assert.Equal(0, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).AttemptCount);
    }

    // --- Heartbeat and fail -----------------------------------------------------------------

    [Fact]
    public async Task AHeartbeatNeedsTheHeaderCapabilityAndNeverTheBody()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();

        using (var missing = await host.SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/heartbeat",
            null, new
            {
                schemaVersion = VisualAttributeContractRules.SchemaVersion, analysisId = unit.AnalysisId, workerId = unit.WorkerId, attemptCount = unit.Attempt,
            }))
        {
            Assert.Equal(HttpStatusCode.BadRequest, missing.StatusCode);
            Assert.Equal("visual_attribute_capability_invalid", await VisualAttributeApiHost.ProblemCodeAsync(missing));
        }

        using (var bodyToken = await host.SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/heartbeat",
            unit.Capability, new
            {
                schemaVersion = VisualAttributeContractRules.SchemaVersion, analysisId = unit.AnalysisId, workerId = unit.WorkerId,
                attemptCount = unit.Attempt, leaseToken = unit.Capability,
            }))
        {
            Assert.Equal(HttpStatusCode.BadRequest, bodyToken.StatusCode);
            Assert.DoesNotContain(unit.Capability, await bodyToken.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }

        using (var wrong = await host.HeartbeatAsync(unit, capability: new string('B', 42) + "A"))
        {
            Assert.Equal(HttpStatusCode.Conflict, wrong.StatusCode);
            Assert.DoesNotContain(unit.Capability, await wrong.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }

        host.World.Clock.Advance(TimeSpan.FromSeconds(30));
        using var extended = await host.HeartbeatAsync(unit);
        Assert.Equal(HttpStatusCode.OK, extended.StatusCode);
        // The capability is issued once, at lease; nothing ever echoes it back.
        Assert.False(extended.Headers.Contains(VisualAttributeContractRules.CapabilityHeader));
        Assert.DoesNotContain(unit.Capability, await extended.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        var response = await extended.Content.ReadFromJsonAsync<VisualAttributeHeartbeatResponse>();
        Assert.True(response!.LeaseExpiresAtUtc > unit.Lease.LeaseExpiresAtUtc);
    }

    [Fact]
    public async Task ARetryableFailureRequeuesAndItsDiagnosticsNeverCarryTheCapability()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();

        using (var leaking = await host.FailAsync(unit, "visual_attribute_inference_failed", $"boom {unit.Capability}"))
            Assert.Equal(HttpStatusCode.BadRequest, leaking.StatusCode);

        using var failed = await host.FailAsync(unit, "visual_attribute_inference_failed", "inference raised");
        Assert.Equal(HttpStatusCode.OK, failed.StatusCode);
        Assert.Equal("requeued", (await failed.Content.ReadFromJsonAsync<VisualAttributeFailResponse>())!.Outcome);

        var again = await host.LeaseAsync("attributes-02");
        Assert.Equal(2, again.Attempt);
        Assert.NotEqual(unit.Capability, again.Capability);
    }

    // --- Evidence -----------------------------------------------------------------------------

    [Fact]
    public async Task EvidenceIsServedWithItsRecordedSizeAndOnlyToTheLeasedRun()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var observation = run.Track(0).Observations[0];

        using (var served = await host.EvidenceAsync(unit, observation.ObservationId))
        {
            Assert.Equal(HttpStatusCode.OK, served.StatusCode);
            Assert.Equal(observation.Bytes, await served.Content.ReadAsByteArrayAsync());
            Assert.Equal(observation.Bytes.Length, served.Content.Headers.ContentLength);
            Assert.Equal("image/jpeg", served.Content.Headers.ContentType?.MediaType);
            Assert.True(served.Headers.CacheControl?.NoStore);
        }

        // Cross-run IDOR: another visible run's accepted crop, with this unit's valid capability.
        var other = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        using (var foreign = await host.EvidenceAsync(unit, other.Track(0).Observations[0].ObservationId))
        {
            Assert.Equal(HttpStatusCode.Conflict, foreign.StatusCode);
            Assert.Equal("visual_attribute_evidence_forbidden", await VisualAttributeApiHost.ProblemCodeAsync(foreign));
        }

        // Another unit's id with this capability.
        using (var otherUnit = await host.EvidenceAsync(unit, observation.ObservationId, analysisId: Guid.CreateVersion7()))
            Assert.Equal(HttpStatusCode.NotFound, otherUnit.StatusCode);

        // A capability in the query string is not a capability.
        using (var queryToken = await host.Client.GetAsync(
            $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/evidence/{observation.ObservationId}?leaseToken={unit.Capability}"))
            Assert.Equal(HttpStatusCode.BadRequest, queryToken.StatusCode);

        // An expired lease reads nothing.
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        using (var expired = await host.EvidenceAsync(unit, observation.ObservationId))
            Assert.Equal(HttpStatusCode.Conflict, expired.StatusCode);

        // Every read, served or refused, is audited; no audit line carries the capability.
        Assert.Single(host.Logs.Entries, entry => entry.EventId.Id == 2000);
        Assert.True(host.Logs.Entries.Count(entry => entry.EventId.Id == 2001) >= 3);
        Assert.DoesNotContain(unit.Capability, host.AllLogText(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task AnAcceptedObjectThatDisagreesWithItsRecordIsAnAuthoritativeIntegrityFailure()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var grown = run.Track(0).Observations[0];
        var missing = run.Track(0).Observations[1];
        var path = host.World.EvidencePath(grown.StorageKey);
        File.SetAttributes(path, FileAttributes.Normal);
        await File.WriteAllBytesAsync(path, [.. grown.Bytes, 0x00]);
        File.SetAttributes(host.World.EvidencePath(missing.StorageKey), FileAttributes.Normal);
        File.Delete(host.World.EvidencePath(missing.StorageKey));

        using (var wrongSize = await host.EvidenceAsync(unit, grown.ObservationId))
        {
            // Refused before any body byte: never a truncated or padded 200.
            Assert.Equal(HttpStatusCode.UnprocessableEntity, wrongSize.StatusCode);
            Assert.Equal("visual_attribute_evidence_integrity_failed", await VisualAttributeApiHost.ProblemCodeAsync(wrongSize));
        }

        using (var gone = await host.EvidenceAsync(unit, missing.ObservationId))
        {
            Assert.Equal(HttpStatusCode.UnprocessableEntity, gone.StatusCode);
            Assert.Equal("visual_attribute_evidence_missing", await VisualAttributeApiHost.ProblemCodeAsync(gone));
        }

        var integrity = host.Factory.Services.GetRequiredService<VisualAttributeIntegrityMonitor>().Current;
        Assert.Equal(2, integrity.EvidenceReadIncidents);
        // Audited as integrity incidents (Error), never with the capability.
        Assert.Equal(2, host.Logs.Entries.Count(entry => entry.EventId.Id == 2002 && entry.Level == Microsoft.Extensions.Logging.LogLevel.Error));
        Assert.DoesNotContain(unit.Capability, host.AllLogText(), StringComparison.Ordinal);
    }

    // --- Upload -------------------------------------------------------------------------------

    [Fact]
    public async Task AnUploadIsStagedOnceAndOnlyTheSameBytesReplay()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = AttributeCompletionBuilder.Build(unit);

        using (var stored = await host.UploadAsync(unit, completion.Predictions))
        {
            Assert.Equal(HttpStatusCode.OK, stored.StatusCode);
            Assert.Contains("\"stored\"", await stored.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }

        using (var replay = await host.UploadAsync(unit, completion.Predictions))
        {
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
            Assert.Contains("\"already_stored\"", await replay.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }

        var different = AttributeCompletionBuilder.Build(unit, value: "light").Predictions;
        using (var conflict = await host.UploadAsync(unit, different))
            Assert.Equal(HttpStatusCode.Conflict, conflict.StatusCode);

        var staged = Path.Combine(host.World.MediaRoot, AttributeStagingLayout.StagingKey(unit.AnalysisId, unit.Attempt).Replace('/', Path.DirectorySeparatorChar));
        Assert.Equal(completion.Predictions, await File.ReadAllBytesAsync(staged));
    }

    [Fact]
    public async Task AnUploadIsVerifiedAgainstItsDeclaredDigestAndLease()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = AttributeCompletionBuilder.Build(unit);

        using (var mismatch = await host.UploadAsync(unit, completion.Predictions, declaredSha256: new string('0', 64)))
        {
            Assert.Equal(HttpStatusCode.UnprocessableEntity, mismatch.StatusCode);
            Assert.Equal(VisualAttributeContractRules.ArtifactIntegrityFailedCode, await VisualAttributeApiHost.ProblemCodeAsync(mismatch));
        }

        // Another attempt's upload with this capability.
        using (var otherAttempt = await host.UploadAsync(unit, completion.Predictions, attempt: unit.Attempt + 1))
            Assert.Equal(HttpStatusCode.Conflict, otherAttempt.StatusCode);

        Assert.False(Directory.Exists(Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, unit.AnalysisId.ToString("D"),
            AttributeStagingLayout.AttemptDirectoryName(unit.Attempt + 1))));
    }

    // --- Completion ---------------------------------------------------------------------------

    [Fact]
    public async Task ACompletionPublishesFactsAndTheSealedArtefactAndTheRunBecomesReady()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 2, vehicles: 1, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var unavailableTrack = run.Track(1).TrackId;
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailable: id => id == unavailableTrack ? "evidence_integrity_failed" : null,
            unknown: new HashSet<string> { "fixture-person-upper" });

        using var response = await host.UploadAndCompleteAsync(unit, completion);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var text = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain(unit.Capability, text, StringComparison.Ordinal);
        var body = await response.Content.ReadFromJsonAsync<VisualAttributeCompleteResponse>();
        Assert.Equal("completed", body!.Status);
        Assert.Equal(2, body.TracksAnalysed);
        Assert.Equal(1, body.TracksUnavailable);

        await using (var db = host.World.Read())
        {
            var analysis = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync();
            Assert.Equal(VisualAttributeAnalysisStatus.Completed, analysis.Status);
            Assert.NotNull(analysis.VisibilitySequence);
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == analysis.PredictionArtifactId);
            Assert.Equal(ArtifactType.AttributePredictions, artifact.ArtifactType);
            Assert.Equal(AttributeStagingLayout.AcceptedKey(analysis.Id, completion.Sha256), artifact.StorageKey);
            Assert.Equal(completion.Predictions, await File.ReadAllBytesAsync(host.World.EvidencePath(artifact.StorageKey)));

            var outcomes = await db.VisualAttributeTrackOutcomes.AsNoTracking().Where(x => x.AnalysisId == analysis.Id).ToListAsync();
            Assert.Equal(3, outcomes.Count);
            Assert.Equal("evidence_integrity_failed", outcomes.Single(x => x.TrackId == unavailableTrack).Reason);
            var attributes = await db.VisualAttributes.AsNoTracking().Where(x => x.AnalysisId == analysis.Id).ToListAsync();
            // Person: two rows (one Unknown); vehicle: one; the Unavailable person: none.
            Assert.Equal(3, attributes.Count);
            Assert.Single(attributes, x => x.Outcome == VisualAttributeOutcome.Unknown);
            Assert.All(attributes.Where(x => x.Outcome == VisualAttributeOutcome.Observed), x => Assert.NotNull(x.SupportingObservationId));
            Assert.DoesNotContain(unit.Capability, analysis.ProvenanceJson!, StringComparison.Ordinal);
        }

        using var readiness = await host.Client.GetAsync($"/api/processing/runs/{run.RunId}/visual-attributes");
        Assert.Equal(HttpStatusCode.OK, readiness.StatusCode);
        Assert.Contains("\"Ready\"", await readiness.Content.ReadAsStringAsync(), StringComparison.Ordinal);

        // One incident per corrupt crop: the Unavailable Track reported both of its crops.
        var integrity = host.Factory.Services.GetRequiredService<VisualAttributeIntegrityMonitor>().Current;
        Assert.Equal(2, integrity.CompletionIncidents);

        // The capability reached no log line on the whole path; the audit trail did record the work.
        var logs = host.AllLogText();
        Assert.DoesNotContain(unit.Capability, logs, StringComparison.Ordinal);
        Assert.Contains(host.Logs.Entries, entry => entry.EventId.Id == 2003);
        Assert.Contains(host.Logs.Entries, entry => entry.EventId.Id == 1990);
    }

    [Fact]
    public async Task AnExactReplayAfterExpiryIsAnsweredFromTheCommittedDigestAndADifferentOneConflicts()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = AttributeCompletionBuilder.Build(unit);
        using (var first = await host.UploadAndCompleteAsync(unit, completion))
            Assert.Equal(HttpStatusCode.OK, first.StatusCode);

        // The response was lost; the lease has long expired.
        host.World.Clock.Advance(TimeSpan.FromHours(2));
        using (var replay = await host.CompleteAsync(unit, completion.Request))
        {
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
            Assert.Equal("completed", (await replay.Content.ReadFromJsonAsync<VisualAttributeCompleteResponse>())!.Status);
        }

        // Same bytes, another device: provenance is part of the completion.
        using (var otherDevice = await host.CompleteAsync(unit, AttributeCompletionBuilder.Build(unit, actualDevice: "cuda:0").Request))
        {
            Assert.Equal(HttpStatusCode.Conflict, otherDevice.StatusCode);
            Assert.Equal("visual_attribute_completion_conflict", await VisualAttributeApiHost.ProblemCodeAsync(otherDevice));
        }

        // The right digest with a wrong capability authenticates nothing.
        using (var wrongCapability = await host.CompleteAsync(unit, completion.Request, capability: new string('C', 42) + "A"))
            Assert.Equal(HttpStatusCode.Conflict, wrongCapability.StatusCode);

        await using var db = host.World.Read();
        Assert.Equal(1, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.AttributePredictions));
    }

    [Fact]
    public async Task ACompletionWhoseArtefactDisagreesWithItsRowsPublishesNothing()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var dark = AttributeCompletionBuilder.Build(unit);
        var light = AttributeCompletionBuilder.Build(unit, value: "light");
        using (var uploaded = await host.UploadAsync(unit, dark.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        // Rows say "light", the staged artefact decided "dark"; the descriptor names the staged bytes.
        var mismatched = light.Request with
        {
            Payload = light.Request.Payload! with
            {
                PredictionArtifact = new VisualAttributeArtifactDescriptorContract(VisualAttributeContractRules.PredictionsMediaType,
                    dark.Predictions.Length, dark.Sha256),
            },
        };
        using var response = await host.CompleteAsync(unit, mismatched);

        Assert.Equal(HttpStatusCode.UnprocessableEntity, response.StatusCode);
        await using var db = host.World.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Running, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
        Assert.False(await db.VisualAttributeTrackOutcomes.AnyAsync());
        Assert.False(Directory.Exists(Path.Combine(host.World.EvidenceRoot, "attributes")));
    }

    private static JsonArray WithoutFirst(JsonArray observations) =>
        new(observations.Skip(1).Select(item => item!.DeepClone()).ToArray());

    /// <summary>Completes with an artefact the worker built wrongly; nothing may be published.</summary>
    private static async Task AssertArtefactRefusedAsync(VisualAttributeApiHost host, LeasedUnit unit, BuiltCompletion completion)
    {
        using var response = await host.UploadAndCompleteAsync(unit, completion);

        Assert.Equal(HttpStatusCode.UnprocessableEntity, response.StatusCode);
        Assert.Equal(AttributePredictionsValidator.InvalidCode, await VisualAttributeApiHost.ProblemCodeAsync(response));
        await using var db = host.World.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Running, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
        Assert.False(await db.VisualAttributeTrackOutcomes.AnyAsync());
    }

    [Fact]
    public async Task AnArtefactThatOmitsALeasedCropFromAnAnalysedTrackPublishesNothing()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var track = run.Track(0);
        var supporting = track.Observations[1].ObservationId;
        // Scored from the second crop only; the first, usable crop is silently left out.
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailableObservation: id => id == track.Observations[0].ObservationId ? "evidence_decode_failed" : null,
            artefactObservations: (_, observations) => WithoutFirst(observations));
        Assert.All(completion.Request.Payload!.Tracks!.Single().Attributes!, row => Assert.Equal(supporting, row.SupportingObservationId));

        await AssertArtefactRefusedAsync(host, unit, completion);
    }

    [Fact]
    public async Task AnArtefactThatOmitsEveryLeasedCropOfAnUnavailableTrackPublishesNothing()
    {
        var (host, _) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        // "Evidence missing" with no observation to show for it: the usable crops were never reported.
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailable: _ => "evidence_missing",
            artefactObservations: (_, _) => []);

        await AssertArtefactRefusedAsync(host, unit, completion);
    }

    [Fact]
    public async Task AnUnavailableTrackMustGiveAReasonItsObservationsReport()
    {
        var (host, _) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        // The Track claims an integrity failure no crop reported.
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailable: _ => "evidence_integrity_failed",
            artefactObservations: (_, observations) =>
            {
                foreach (var observation in observations) observation!["reason"] = "evidence_decode_failed";
                return observations;
            });

        await AssertArtefactRefusedAsync(host, unit, completion);
    }

    [Fact]
    public async Task ACropThatFailedItsIntegrityCheckOnAnAnalysedTrackIsAnOperatorIncident()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var track = run.Track(0);
        // One crop's bytes disagree with their record; the Track is still analysed from the other.
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailableObservation: id => id == track.Observations[0].ObservationId ? "evidence_integrity_failed" : null);

        using var response = await host.UploadAndCompleteAsync(unit, completion);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        await using (var db = host.World.Read())
            Assert.Null((await db.VisualAttributeTrackOutcomes.AsNoTracking().SingleAsync()).Reason);
        var integrity = host.Factory.Services.GetRequiredService<VisualAttributeIntegrityMonitor>().Current;
        Assert.Equal(1, integrity.CompletionIncidents);
        Assert.Equal(unit.AnalysisId, integrity.LastIncidentAnalysisId);
    }

    [Fact]
    public async Task ACropThatCouldNotBeDecodedIsNotAnIntegrityIncident()
    {
        var (host, run) = await HostWithQueuedRunAsync(persons: 1, vehicles: 0, observations: 2);
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var track = run.Track(0);
        var completion = AttributeCompletionBuilder.Build(unit,
            unavailableObservation: id => id == track.Observations[0].ObservationId ? "evidence_decode_failed" : null);

        using var response = await host.UploadAndCompleteAsync(unit, completion);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(0, host.Factory.Services.GetRequiredService<VisualAttributeIntegrityMonitor>().Current.CompletionIncidents);
    }

    // --- Startup ---------------------------------------------------------------------------

    [Theory]
    [InlineData("Production", true)]
    [InlineData("Staging", true)]
    [InlineData("Development", false)]
    [InlineData("Testing", false)]
    public void TheDevelopmentOnlyFixtureStartsOnlyInDevelopmentOrTesting(string environment, bool refused)
    {
        var definition = VisualAttributeReleaseFixture.Definition();
        Assert.True(definition.DevelopmentOnly);
        var host = new StartupEnvironment { EnvironmentName = environment };
        if (!refused)
        {
            Mavi.Api.Startup.VisualAttributeReleaseStartup.RequireAllowed(definition, host);
            return;
        }

        var exception = Assert.Throws<InvalidOperationException>(() => Mavi.Api.Startup.VisualAttributeReleaseStartup.RequireAllowed(definition, host));
        Assert.Equal(Mavi.Api.Startup.VisualAttributeReleaseStartup.FixtureForbiddenCode, exception.Message);
        // A definition that is not Development-only is not this rule's to refuse.
        Mavi.Api.Startup.VisualAttributeReleaseStartup.RequireAllowed(definition with { DevelopmentOnly = false }, host);
    }

    private sealed class StartupEnvironment : Microsoft.Extensions.Hosting.IHostEnvironment
    {
        public string EnvironmentName { get; set; } = "Production";
        public string ApplicationName { get; set; } = "Mavi.Api";
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public Microsoft.Extensions.FileProviders.IFileProvider ContentRootFileProvider { get; set; } =
            new Microsoft.Extensions.FileProviders.NullFileProvider();
    }

    // --- Route bounds (plan §9): cap accepted, cap+1 refused before the endpoint ---------------

    [Theory]
    [InlineData("lease", VisualAttributeContractRules.MaximumLeaseRequestBodyBytes)]
    [InlineData("{id}/heartbeat", VisualAttributeContractRules.MaximumHeartbeatRequestBodyBytes)]
    [InlineData("{id}/fail", VisualAttributeContractRules.MaximumFailRequestBodyBytes)]
    [InlineData("{id}/complete", VisualAttributeContractRules.MaximumCompletionRequestBodyBytes)]
    [InlineData("{id}/predictions", VisualAttributeContractRules.MaximumPredictionArtifactBytes)]
    public async Task EveryControlRouteRefusesItsCapPlusOne(string route, long cap)
    {
        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        var path = $"{VisualAttributeContractRules.RoutePrefix}/{route.Replace("{id}", Guid.CreateVersion7().ToString("D"), StringComparison.Ordinal)}";
        var method = route.EndsWith("predictions", StringComparison.Ordinal) ? HttpMethod.Put : HttpMethod.Post;

        using var over = await host.Client.SendAsync(new HttpRequestMessage(method, path) { Content = new PaddedContent(cap + 1) });
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, over.StatusCode);

        // At the cap the bound admits the body; the endpoint then judges it (not 413).
        using var at = await host.Client.SendAsync(new HttpRequestMessage(method, path) { Content = new PaddedContent(cap) });
        Assert.NotEqual(HttpStatusCode.RequestEntityTooLarge, at.StatusCode);
    }

    [Fact]
    public async Task EvidenceAndUnknownAttributeRoutesAdmitNoBody()
    {
        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        var path = $"{VisualAttributeContractRules.RoutePrefix}/{Guid.CreateVersion7()}/evidence/{Guid.CreateVersion7()}";
        using var response = await host.Client.SendAsync(new HttpRequestMessage(HttpMethod.Get, path) { Content = new PaddedContent(1) });
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
    }

    /// <summary>A body of an exact declared length, streamed (never materialised at 64 MiB).</summary>
    private sealed class PaddedContent : HttpContent
    {
        private readonly long _length;

        public PaddedContent(long length)
        {
            _length = length;
            Headers.ContentType = new MediaTypeHeaderValue("application/json");
        }

        protected override async Task SerializeToStreamAsync(Stream stream, System.Net.TransportContext? context)
        {
            var buffer = Encoding.ASCII.GetBytes(new string(' ', 64 * 1024));
            for (var remaining = _length; remaining > 0; remaining -= buffer.Length)
                await stream.WriteAsync(buffer.AsMemory(0, (int)Math.Min(buffer.Length, remaining)));
        }

        protected override bool TryComputeLength(out long length)
        {
            length = _length;
            return true;
        }
    }
}
