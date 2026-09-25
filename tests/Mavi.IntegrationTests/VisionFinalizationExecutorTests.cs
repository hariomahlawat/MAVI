using System.Net.Http.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Finalization;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The executor (F3 plan §6.3–§6.7, §9, §10.3; slice 6): payload revalidation, bounded sealing
/// with claim extension, the deadline mid-seal, every failure class, adoption on retry, and
/// the rule that nothing here ever deletes accepted evidence.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationExecutorTests
{
    private static readonly string[] F3Sources =
    [
        "src/platform/Mavi.Infrastructure/Finalization/VisionFinalizationExecutor.cs",
        "src/platform/Mavi.Infrastructure/Persistence/Repositories/VisionFinalizationLifecycle.cs",
        "src/platform/Mavi.Infrastructure/Persistence/Repositories/FinalizationGraphPersistence.cs",
        "src/platform/Mavi.Application/Modules/Intelligence/EvidenceSealingPlan.cs",
        "src/platform/Mavi.Application/Modules/Intelligence/FinalizationGraphBuilder.cs",
        "src/platform/Mavi.Application/Modules/Intelligence/IVisionFinalizationLifecycle.cs",
        "src/platform/Mavi.Api/Finalization/VisionFinalizationHostedService.cs",
    ];

    // -- the happy path -------------------------------------------------------------------------

    [Fact]
    public async Task HandOffThenExecutionPublishesTheGraphAndLogsNoSecret()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        world.Clock.Advance(TimeSpan.FromSeconds(3));

        var outcome = await ExecuteAsync(world, claim);

        Assert.Equal(VisionFinalizationExecutionKind.Published, outcome.Kind);
        Assert.Equal(5, outcome.Sealing.Created);
        Assert.Equal(0, outcome.Sealing.Adopted);
        Assert.Equal(5, outcome.Sealing.Total);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
        Assert.Equal(5, world.EvidenceFiles().Length);
        Assert.True(Directory.Exists(world.StagingAttemptPath(handOff.Lease)), "staging is retained for the janitor");
        Assert.Equal(0, world.Sealer.Deletes);

        var published = Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1504);
        Assert.Contains("5 created", published.Message, StringComparison.Ordinal);
        AssertNoSecretsInLogs(world, claim, handOff);

        // The worker's replay of the hand-off now answers completed.
        using var replay = await handOff.Client.PostAsJsonAsync($"/api/vision/jobs/{claim.JobId}/complete", handOff.Request);
        var ack = (await replay.Content.ReadFromJsonAsync<Mavi.Contracts.Worker.VisionJobFinalizationResponse>())!;
        Assert.Equal("completed", ack.State);
        Assert.Equal(job.CompletedAtUtc, ack.CompletedAtUtc);
    }

    // -- payload integrity (F3 plan §6.4) -----------------------------------------------------

    [Fact]
    public async Task PayloadMissingFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        await world.ExecuteSqlAsync("DELETE FROM vision_finalization_payloads WHERE job_id = $1", claim.JobId);

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_payload_missing", handOff);
        Assert.Equal(0, world.Sealer.Seals);
    }

    [Fact]
    public async Task PayloadTamperedFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        // Flip one byte of the retained bytea; the recorded SHA-256 no longer matches.
        await world.ExecuteSqlAsync(
            "UPDATE vision_finalization_payloads SET payload = set_byte(payload, 3, (get_byte(payload, 3) + 1) % 256) WHERE job_id = $1", claim.JobId);

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_payload_integrity_failed", handOff);
    }

    [Fact]
    public async Task PayloadInvalidFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        // Bytes that hash correctly (length and sha256 rewritten) but do not decode.
        var garbage = System.Text.Encoding.UTF8.GetBytes("{\"schemaVersion\":\"3.1\",\"jobId\":\"not-a-guid\"}");
        await world.ExecuteSqlAsync(
            "UPDATE vision_finalization_payloads SET payload = $1, payload_length = $2, payload_sha256 = $3 WHERE job_id = $4",
            garbage, (long)garbage.Length, Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(garbage)), claim.JobId);

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_payload_invalid", handOff);
    }

    [Fact]
    public async Task PayloadOfAnotherJobFailsTheBinding()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var first = await world.HandOffAsync(cameraCode: "CAM-1");
        var second = await world.HandOffAsync(cameraCode: "CAM-2");
        // Give the first job the second job's bytes, rewriting the row's own integrity facts so
        // only the binding check can catch it.
        await world.ExecuteSqlAsync(
            "UPDATE vision_finalization_payloads p SET payload = o.payload, payload_length = o.payload_length, payload_sha256 = o.payload_sha256, completion_digest = o.completion_digest" +
            " FROM vision_finalization_payloads o WHERE p.job_id = $1 AND o.job_id = $2", first.Lease.JobId, second.Lease.JobId);
        var claim = (await world.ClaimAsync())!;
        Assert.Equal(first.Lease.JobId, claim.JobId);

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_payload_invalid", first);
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(second.Lease.JobId)).Status);
    }

    [Fact]
    public async Task DigestMismatchAgainstTheJobFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        await world.ExecuteSqlAsync("UPDATE vision_jobs SET completion_digest = $1 WHERE id = $2", new string('b', 64), handOff.Lease.JobId);
        var claim = (await world.ClaimAsync())!;

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_payload_integrity_failed", handOff);
        Assert.Equal(0, world.Sealer.Seals);
    }

    // -- staging validation and evidence conflicts (F3 plan §6.5, §9.1) ---------------------

    [Fact]
    public async Task StagingMissingFailsAfterSealingBeganAndLogsOrphans()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        // Crops seal first; the trajectory is the last unit of the track.
        File.Delete(Path.Combine(world.StagingAttemptPath(handOff.Lease), "trajectories", "person-000001.msgpack"));

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_staging_missing", handOff);
        Assert.Equal("trajectories unit 0", (await world.JobAsync(claim.JobId)).FailureDetails);
        Assert.Equal(4, outcome.Sealing.Created);
        Assert.Equal(4, world.EvidenceFiles().Length); // the crops stay: orphans, never deleted
        var orphans = Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1509);
        Assert.Contains("4 accepted objects created", orphans.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task StagingTamperedFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        File.WriteAllText(Path.Combine(world.StagingAttemptPath(handOff.Lease), "evidence", "person-000001-representative.jpg"), "tampered-after-hand-off");

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_staging_integrity_failed", handOff);
        Assert.Empty(world.EvidenceFiles());
    }

    [Fact]
    public async Task StagingEscapeFailsDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var crop = Path.Combine(world.StagingAttemptPath(handOff.Lease), "evidence", "person-000001-representative.jpg");
        var outside = Path.Combine(Path.GetTempPath(), $"mavi-escape-{Guid.NewGuid():N}.jpg");
        File.Copy(crop, outside);
        try
        {
            File.Delete(crop);
            File.CreateSymbolicLink(crop, outside);

            var outcome = await ExecuteAsync(world, claim);

            await AssertFailedAsync(world, claim, outcome, "vision_finalization_staging_integrity_failed", handOff);
            Assert.DoesNotContain(outside, world.AllLogText(), StringComparison.Ordinal);
        }
        finally
        {
            File.Delete(outside);
        }
    }

    [Fact]
    public async Task ConflictingAcceptedObjectFailsClosedAndIsNeverTouched()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, _) = await PlanOnlyAsync(world, claim);
        var trajectory = EvidenceSealingPlan.Build(claim.JobId, result).Single(x => x.Category == EvidenceSealingPlan.TrajectoriesCategory);
        var destination = Path.Combine(world.Factory.EvidenceRoot, trajectory.AcceptedStorageKey.Replace("evidence/", string.Empty, StringComparison.Ordinal).Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.WriteAllText(destination, "someone else's bytes");

        var outcome = await ExecuteAsync(world, claim);

        await AssertFailedAsync(world, claim, outcome, "vision_finalization_evidence_conflict", handOff);
        Assert.Equal("someone else's bytes", File.ReadAllText(destination));
        Assert.Equal(0, world.Sealer.Deletes);
    }

    // -- adoption, transient IO, extension, loss and the deadline mid-seal -------------------

    [Fact]
    public async Task RetryAdoptsIdenticalAcceptedObjectsWithoutDeletingAnything()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var stale = (await world.ClaimAsync())!;
        var (_, _) = await world.PrepareAsync(stale); // seals every object under the stale claim
        var filesBefore = world.EvidenceFiles();
        Assert.Equal(5, filesBefore.Length);
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        var live = (await world.ClaimAsync())!;

        var outcome = await ExecuteAsync(world, live);

        Assert.Equal(VisionFinalizationExecutionKind.Published, outcome.Kind);
        Assert.Equal(0, outcome.Sealing.Created);
        Assert.Equal(5, outcome.Sealing.Adopted);
        Assert.Equal(filesBefore, world.EvidenceFiles());
        Assert.Equal(0, world.Sealer.Deletes);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);
    }

    [Fact]
    public async Task TransientIoIsNotedTheClaimReleasedAndTheNextClaimPublishes()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        world.Sealer.ThrowIoOnSeal = 3;

        var outcome = await ExecuteAsync(world, claim);

        Assert.Equal(VisionFinalizationExecutionKind.Transient, outcome.Kind);
        Assert.Equal("vision_finalization_io_transient", outcome.Code);
        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal("vision_finalization_io_transient", job.FinalizationLastErrorCode);
        Assert.Null(job.FailureCode);
        Assert.Equal(FinalizationClaimState.Expired, job.FinalizationClaimStateAt(world.Clock.GetUtcNow()));
        Assert.Equal(2, world.EvidenceFiles().Length);
        var transient = Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1506);
        Assert.Contains("IOException", transient.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("/this/path/must/never/be/logged", world.AllLogText(), StringComparison.Ordinal);

        var next = (await world.ClaimAsync())!;
        Assert.Equal(2, next.FinalizationAttemptCount);
        var retry = await ExecuteAsync(world, next);
        Assert.Equal(VisionFinalizationExecutionKind.Published, retry.Kind);
        Assert.Equal(2, retry.Sealing.Adopted);
        Assert.Equal(3, retry.Sealing.Created);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);
        Assert.Equal(0, world.Sealer.Deletes);
    }

    [Fact]
    public async Task LiveClaimIsExtendedAfterEveryBatch()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var policy = world.Policy with { SealingBatchSize = 2 };
        var extendedAt = new List<DateTimeOffset?>();
        world.Clock.Advance(TimeSpan.FromSeconds(1)); // so the pre-IO extension changes the expiry and is a visible UPDATE
        world.Sql.Clear();
        world.Sealer.BeforeSeal = async call =>
        {
            world.Clock.Advance(TimeSpan.FromSeconds(10));
            extendedAt.Add((await world.JobAsync(claim.JobId)).FinalizationClaimExtendedAtUtc);
        };

        var outcome = await ExecuteAsync(world, claim, policy);

        Assert.Equal(VisionFinalizationExecutionKind.Published, outcome.Kind);
        // 5 objects in batches of 2: one extension before IO, then after batches 1, 2 and 3.
        var extensions = world.Sql.Commands.Count(x =>
            x.Contains("UPDATE vision_jobs SET", StringComparison.Ordinal) &&
            x.Contains("finalization_claim_extended_at_utc", StringComparison.Ordinal) &&
            !x.Contains("finalization_attempt_count", StringComparison.Ordinal) &&
            !x.Contains("completed_at_utc", StringComparison.Ordinal));
        Assert.True(extensions == 4, $"expected 4 extension updates, saw {extensions}:\n" + string.Join("\n---\n", world.Sql.Commands.Where(x => x.Contains("UPDATE vision_jobs", StringComparison.Ordinal))));
        // Seen from inside the seals: the extension time advances after each batch.
        Assert.Equal(extendedAt[0], extendedAt[1]);
        Assert.True(extendedAt[2] > extendedAt[1], "extended after batch 1");
        Assert.Equal(extendedAt[2], extendedAt[3]);
        Assert.True(extendedAt[4] > extendedAt[3], "extended after batch 2");
    }

    [Fact]
    public async Task ClaimLostMidSealStopsWithoutWritingAndTheLiveClaimantPublishes()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var stale = (await world.ClaimAsync())!;
        var policy = world.Policy with { SealingBatchSize = 2 };
        VisionFinalizationClaim? live = null;
        world.Sealer.BeforeSeal = async call =>
        {
            if (call == 3)
            {
                // Another host reclaims after the stale claim's expiry, between batches 1 and 2.
                world.Clock.Advance(TimeSpan.FromMinutes(6));
                live = await world.ClaimAsync(policy);
                Assert.NotNull(live);
            }
        };

        var outcome = await ExecuteAsync(world, stale, policy);

        Assert.Equal(VisionFinalizationExecutionKind.Lost, outcome.Kind);
        Assert.Equal(4, world.Sealer.Seals); // batch 2 sealed (harmless create-once IO), then the extension found the claim lost
        var job = await world.JobAsync(stale.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Null(job.FailureCode);
        Assert.Null(job.FinalizationLastErrorCode);
        Assert.True(job.FinalizationOwnedBy(live!.ClaimToken.Span, world.Clock.GetUtcNow()));
        Assert.Equal(0, await world.TrackCountAsync(handOff.Lease.ProcessingRunId));
        world.Sealer.BeforeSeal = null;

        var published = await ExecuteAsync(world, live!, policy);
        Assert.Equal(VisionFinalizationExecutionKind.Published, published.Kind);
        Assert.Equal(4, published.Sealing.Adopted);
        Assert.Equal(1, published.Sealing.Created);
        Assert.Equal(0, world.Sealer.Deletes);
    }

    [Fact]
    public async Task ExecutorStopsSealingWhenTheDeadlineIsReached()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);
        world.Clock.Advance(deadline.AddMinutes(-2) - world.Clock.GetUtcNow());
        var claim = (await world.ClaimAsync())!;
        var policy = world.Policy with { SealingBatchSize = 2 };
        world.Sealer.BeforeSeal = call =>
        {
            if (call == 2)
                world.Clock.Advance(TimeSpan.FromMinutes(2)); // the deadline passes inside batch 1
            return Task.CompletedTask;
        };

        var outcome = await ExecuteAsync(world, claim, policy);

        Assert.Equal(VisionFinalizationExecutionKind.DeadlineReached, outcome.Kind);
        Assert.Equal(2, world.Sealer.Seals);
        Assert.Equal(2, outcome.Sealing.Created);
        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Null(job.FailureCode);
        Assert.True(job.FinalizationOwnedBy(claim.ClaimToken.Span, world.Clock.GetUtcNow()), "the claim is not revoked; it expires on its own");
        Assert.Equal(0, await world.TrackCountAsync(claim.ProcessingRunId));
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1513);

        // Nobody can claim again; once the claim expires, reconciliation exhausts.
        Assert.Null(await world.ClaimAsync(policy));
        world.Clock.Advance(TimeSpan.FromMinutes(5));
        Assert.Equal(1, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None))).Exhausted);
        Assert.Equal("vision_finalization_exhausted", (await world.JobAsync(claim.JobId)).FailureCode);
        Assert.Equal(2, world.EvidenceFiles().Length); // orphans remain
    }

    [Fact]
    public async Task ExecutorPublishesAfterTheDeadlineIfSealingWasComplete()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);
        world.Clock.Advance(deadline.AddMinutes(-2) - world.Clock.GetUtcNow());
        var claim = (await world.ClaimAsync())!;
        var policy = world.Policy with { SealingBatchSize = 2 };
        world.Sealer.BeforeSeal = call =>
        {
            if (call == 5)
                world.Clock.Advance(TimeSpan.FromMinutes(2)); // the deadline passes inside the last batch
            return Task.CompletedTask;
        };

        var outcome = await ExecuteAsync(world, claim, policy);

        Assert.Equal(VisionFinalizationExecutionKind.Published, outcome.Kind);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(claim.JobId)).Status);
        Assert.DoesNotContain(world.Logs.Entries, x => x.EventId.Id == 1513);
    }

    [Fact]
    public async Task HostShutdownMidSealWritesNothing()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        using var cancellation = new CancellationTokenSource();
        world.Sealer.BeforeSeal = call =>
        {
            if (call == 3)
                cancellation.Cancel();
            return Task.CompletedTask;
        };

        var outcome = await ExecuteAsync(world, claim, cancellationToken: cancellation.Token);

        Assert.Equal(VisionFinalizationExecutionKind.Cancelled, outcome.Kind);
        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Null(job.FailureCode);
        Assert.Null(job.FinalizationLastErrorCode);
        Assert.True(job.FinalizationOwnedBy(claim.ClaimToken.Span, world.Clock.GetUtcNow()));
        Assert.Equal(0, await world.TrackCountAsync(claim.ProcessingRunId));
    }

    // -- accounting survives a database transient after sealing began (F3 plan §10.9) --------

    [Fact]
    public async Task DatabaseTransientAfterSealingBeganKeepsTheSealingAccounting()
    {
        var fault = new FinalizationWorld.DatabaseFault();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(fault));
        await world.HandOffAsync();
        var policy = world.Policy with { SealingBatchSize = 2 };
        var armAt = 0;
        world.Sealer.BeforeSeal = call =>
        {
            // After batch 1 (2 objects) the claim extension is the next database write.
            if (call == armAt)
                fault.ArmOnCommandContaining("finalization_claim_extended_at_utc");
            return Task.CompletedTask;
        };

        // The shared test database is reset per test without clearing the connection pool, so a
        // pooled connection can raise a genuine transient before any object is sealed. The
        // executor is designed to survive exactly that, and it is not what this test measures:
        // the injected fault must have fired, otherwise the execution is repeated on a new claim.
        VisionFinalizationExecutionOutcome outcome;
        var attempts = 0;
        do
        {
            var claim = (await world.ClaimAsync(policy))!;
            world.Clock.Advance(TimeSpan.FromSeconds(1)); // every extension changes the expiry
            armAt = world.Sealer.Seals + 2;
            outcome = await ExecuteAsync(world, claim, policy);
            attempts++;
        }
        while (!fault.Tripped && attempts < 3);
        Assert.True(fault.Tripped, "the injected extension fault fired");

        Assert.Equal(VisionFinalizationExecutionKind.Transient, outcome.Kind);
        Assert.Equal("vision_finalization_db_transient", outcome.Code);
        Assert.Equal(2, outcome.Sealing.Created);
        Assert.Equal(0, outcome.Sealing.Adopted);
        Assert.Equal(5, outcome.Sealing.Total);
        Assert.Equal(2, world.EvidenceFiles().Length);
        Assert.Equal(0, world.Sealer.Deletes);
        var transient = world.Logs.Entries.Last(x => x.EventId.Id == 1506);
        Assert.Contains("2 created", transient.Message, StringComparison.Ordinal);
        Assert.Contains("NpgsqlException", transient.Message, StringComparison.Ordinal);
        // The finalizer's own events (1500–1514) carry the exception type only. EF Core's
        // command logger records the provider message separately; that category is not F3's.
        var finalizerLog = string.Join('\n', world.Logs.Entries.Where(x => x.EventId.Id is >= 1500 and <= 1514).Select(x => x.Message));
        Assert.DoesNotContain("/this/path/must/never/be/logged", finalizerLog, StringComparison.Ordinal);
        var jobId = (await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None))).FinalizingJobs;
        Assert.Equal(1, jobId);

        // The next claim adopts the two objects and publishes.
        var retry = await ExecuteAsync(world, (await world.ClaimAsync(policy))!, policy);
        Assert.Equal(VisionFinalizationExecutionKind.Published, retry.Kind);
        Assert.Equal(2, retry.Sealing.Adopted);
        Assert.Equal(3, retry.Sealing.Created);
    }

    // -- publication ambiguity through the executor (F3 plan §10.2) --------------------------

    [Fact]
    public async Task AmbiguousCommitThatSucceededEndsAsLostAndIsNotRepublished()
    {
        var faults = new VisionFinalizationPublicationTests.CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        faults.Arm(failAfterCommit: true);

        var outcome = await ExecuteAsync(world, claim);

        Assert.Equal(VisionFinalizationExecutionKind.Lost, outcome.Kind);
        var (job, run, _) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Null(job.FinalizationLastErrorCode);
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
        Assert.Null(await world.ClaimAsync());
    }

    [Fact]
    public async Task AmbiguousCommitThatFailedIsNotedAndTheRetryPublishesOnce()
    {
        var faults = new VisionFinalizationPublicationTests.CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        faults.Arm(failBeforeCommit: true);

        var outcome = await ExecuteAsync(world, claim);

        Assert.Equal(VisionFinalizationExecutionKind.Transient, outcome.Kind);
        Assert.Equal("vision_finalization_publication_ambiguous", outcome.Code);
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(claim.JobId)).Status);
        var files = world.EvidenceFiles();

        var retry = await ExecuteAsync(world, (await world.ClaimAsync())!);
        Assert.Equal(VisionFinalizationExecutionKind.Published, retry.Kind);
        Assert.Equal(5, retry.Sealing.Adopted);
        Assert.Equal(files, world.EvidenceFiles());
        Assert.Equal(1, await world.TrackCountAsync(claim.ProcessingRunId));
    }

    [Fact]
    public async Task ADatabaseFaultDuringPublicationIsATransientRetry()
    {
        var faults = new VisionFinalizationPublicationTests.CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        faults.Arm(failOnInsert: true);

        var outcome = await ExecuteAsync(world, claim);

        Assert.Equal(VisionFinalizationExecutionKind.Transient, outcome.Kind);
        Assert.Equal("vision_finalization_db_transient", outcome.Code);
        Assert.Equal("vision_finalization_db_transient", (await world.JobAsync(claim.JobId)).FinalizationLastErrorCode);
        Assert.Equal(VisionFinalizationExecutionKind.Published, (await ExecuteAsync(world, (await world.ClaimAsync())!)).Kind);
    }

    // -- the no-delete rule ----------------------------------------------------------------

    [Fact]
    public void NoAsynchronousFinalizationSourceReferencesAcceptedEvidenceDeletion()
    {
        var root = RepositoryRoot();
        foreach (var relative in F3Sources)
        {
            var path = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
            Assert.True(File.Exists(path), relative);
            Assert.DoesNotContain("DeleteAcceptedAsync", File.ReadAllText(path), StringComparison.Ordinal);
        }

        // The synchronous store keeps its compensation; that is the one place the call belongs.
        Assert.Contains("DeleteAcceptedAsync", File.ReadAllText(Path.Combine(root, "src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingResultStore.cs")), StringComparison.Ordinal);
    }

    // -- helpers --------------------------------------------------------------------------

    internal static Task<VisionFinalizationExecutionOutcome> ExecuteAsync(
        FinalizationWorld world, VisionFinalizationClaim claim, VisionFinalizationPolicy? policy = null, CancellationToken cancellationToken = default) =>
        world.Factory.Services.GetRequiredService<VisionFinalizationExecutor>().ExecuteAsync(claim, policy ?? world.Policy, cancellationToken);

    private static async Task<(ValidatedVisionResult Result, VisionFinalizationInputs Inputs)> PlanOnlyAsync(FinalizationWorld world, VisionFinalizationClaim claim)
    {
        var inputs = (await world.WithLifecycleAsync(l => l.LoadInputsAsync(claim, CancellationToken.None)))!;
        var request = VisionFinalizationPayloadCodec.Decode(inputs.Payload!.Payload);
        return (world.Factory.Services.GetRequiredService<VisionResultValidator>().Validate(claim.JobId, request, inputs.VideoDurationMs), inputs);
    }

    private static async Task AssertFailedAsync(FinalizationWorld world, VisionFinalizationClaim claim, VisionFinalizationExecutionOutcome outcome, string code, FinalizationWorld.HandOff handOff)
    {
        Assert.Equal(VisionFinalizationExecutionKind.Failed, outcome.Kind);
        Assert.Equal(code, outcome.Code);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal(code, job.FailureCode);
        Assert.Equal(code, job.FinalizationLastErrorCode);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Equal(ProcessingRunStatus.Failed, run.Status);
        Assert.Equal(code, run.ErrorCode);
        Assert.StartsWith("vision_finalization_", run.ErrorCode, StringComparison.Ordinal);
        Assert.Null(run.VisibilitySequence);
        Assert.Equal(VideoProcessingStatus.Failed, video.ProcessingStatus);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        Assert.Equal(0L, await world.VisibilityAllocationsAsync());
        Assert.Equal(0, world.Sealer.Deletes);
        Assert.True(Directory.Exists(world.StagingAttemptPath(handOff.Lease)), "staging is never removed by the finalizer");
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1505);
        AssertNoSecretsInLogs(world, claim, handOff);
        var next = await world.ClaimAsync();
        Assert.True(next is null || next.JobId != claim.JobId, "a failed job is never claimable again");
    }

    internal static void AssertNoSecretsInLogs(FinalizationWorld world, VisionFinalizationClaim claim, FinalizationWorld.HandOff handOff)
    {
        var text = world.AllLogText();
        Assert.DoesNotContain(Convert.ToBase64String(claim.ClaimToken.ToArray()), text, StringComparison.Ordinal);
        Assert.DoesNotContain(Convert.ToHexString(claim.ClaimToken.Span), text, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(handOff.Lease.LeaseToken, text, StringComparison.Ordinal);
        Assert.DoesNotContain(world.Factory.MediaRoot, text, StringComparison.Ordinal);
        Assert.DoesNotContain(world.Factory.EvidenceRoot, text, StringComparison.Ordinal);
        Assert.DoesNotContain("staging/", text, StringComparison.Ordinal);
        Assert.DoesNotContain("evidence/", text, StringComparison.Ordinal);
        Assert.DoesNotContain("Exception:", text, StringComparison.Ordinal);
    }

    private static string RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new DirectoryNotFoundException("MAVI.sln not found.");
    }
}
