using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Finalization;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The crash and fault matrix end to end (F3 plan §11; slice 9), driven through the host and the
/// executor as the application wires them: process loss at every point, two hosts, the janitor
/// racing a Finalizing job, worker independence, and the truthful status surface.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationRecoveryTests
{
    // -- worker independence (row 1) ---------------------------------------------------------

    [Fact]
    public async Task WorkerDeathImmediatelyAfterHandOffDoesNotMatter()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        // The worker process is gone: no heartbeat, no cleanup, no replay, ever.
        world.Clock.Advance(TimeSpan.FromHours(1)); // long past the worker lease

        await world.Host().RunCycleAsync(CancellationToken.None);

        var (job, run, video) = await world.StateAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);
        Assert.Equal(1, await world.TrackCountAsync(run.Id));

        // A late replay from a resurrected worker answers completed with the published facts.
        using var replay = await handOff.Client.PostAsJsonAsync($"/api/vision/jobs/{handOff.Lease.JobId}/complete", handOff.Request);
        var ack = (await replay.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("completed", ack.State);
        Assert.Equal(job.CompletedAtUtc, ack.CompletedAtUtc);
        Assert.Equal(handOff.Ack.AcceptedAtUtc, ack.AcceptedAtUtc);
    }

    // -- process loss at every point (rows 2, 6, 7, 12, 16) ----------------------------------

    [Fact]
    public async Task HostDiesBeforeTheFirstClaimAndTheNextHostFinalizes()
    {
        using var first = await FinalizationWorld.CreateAsync();
        var handOff = await first.HandOffAsync();
        using var second = await FinalizationWorld.CreateAsync(sharedWith: first);

        await second.Host().RunCycleAsync(CancellationToken.None);

        Assert.Equal(VisionJobStatus.Completed, (await second.JobAsync(handOff.Lease.JobId)).Status);
        Assert.Equal(1, (await second.JobAsync(handOff.Lease.JobId)).FinalizationAttemptCount);
    }

    [Fact]
    public async Task HostDiesBeforeTheFirstSealAndTheReclaimSealsEverything()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        _ = await world.ClaimAsync(); // claimed, then dead before any IO
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        await world.Host().RunCycleAsync(CancellationToken.None);

        var job = await world.JobAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(2, job.FinalizationAttemptCount);
        Assert.Contains(world.Logs.Entries, x => x.EventId.Id == 1504 && x.Message.Contains("5 created", StringComparison.Ordinal));
    }

    [Fact]
    public async Task HostDiesMidSealAndTheReclaimAdoptsWhatWasSealed()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var dead = (await world.ClaimAsync())!;
        var inputs = (await world.WithLifecycleAsync(l => l.LoadInputsAsync(dead, CancellationToken.None)))!;
        var result = world.Factory.Services.GetRequiredService<VisionResultValidator>().Validate(dead.JobId, VisionFinalizationPayloadCodec.Decode(inputs.Payload!.Payload), inputs.VideoDurationMs);
        var sealer = world.Factory.Services.GetRequiredService<IAcceptedEvidenceStore>();
        foreach (var unit in EvidenceSealingPlan.Build(dead.JobId, result).Take(2))
            await sealer.SealAsync(unit.SourceStorageKey, unit.AcceptedStorageKey, unit.ExpectedSizeBytes, unit.ExpectedSha256, CancellationToken.None);
        var partial = world.EvidenceFiles();
        Assert.Equal(2, partial.Length);
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        await world.Host().RunCycleAsync(CancellationToken.None);

        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);
        Assert.Contains(world.Logs.Entries, x => x.EventId.Id == 1504 && x.Message.Contains("3 created", StringComparison.Ordinal) && x.Message.Contains("2 adopted", StringComparison.Ordinal));
        Assert.All(partial, file => Assert.Contains(file, world.EvidenceFiles()));
        Assert.Equal(0, world.Sealer.Deletes);
    }

    [Fact]
    public async Task HostDiesAfterAllSealsBeforePublicationAndTheReclaimAdoptsAndPublishes()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var dead = (await world.ClaimAsync())!;
        _ = await world.PrepareAsync(dead); // everything sealed, graph built, then the process died
        var files = world.EvidenceFiles();
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        await world.Host().RunCycleAsync(CancellationToken.None);

        var (job, run, _) = await world.StateAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
        Assert.Equal(files, world.EvidenceFiles());
        Assert.Contains(world.Logs.Entries, x => x.EventId.Id == 1504 && x.Message.Contains("0 created", StringComparison.Ordinal) && x.Message.Contains("5 adopted", StringComparison.Ordinal));
        Assert.Equal(1L, await world.VisibilityAllocationsAsync());
    }

    [Fact]
    public async Task ProcessDiesAfterCommitBeforeCleanupAndALaterCycleCleansThePayload()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);
        Assert.Equal(VisionFinalizationTransitionKind.Published, (await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None))).Kind);
        Assert.Equal(1, await world.PayloadCountAsync()); // died right here

        await world.Host().RunCycleAsync(CancellationToken.None);

        Assert.Equal(0, await world.PayloadCountAsync());
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);
        Assert.Equal(1L, await world.VisibilityAllocationsAsync());
    }

    // -- two hosts (row 19) --------------------------------------------------------------------

    [Fact]
    public async Task TwoHostsRacingOneJobProduceExactlyOnePublication()
    {
        using var first = await FinalizationWorld.CreateAsync();
        using var second = await FinalizationWorld.CreateAsync(sharedWith: first);
        var handOff = await first.HandOffAsync();

        await Task.WhenAll(first.Host().RunCycleAsync(CancellationToken.None), second.Host().RunCycleAsync(CancellationToken.None));

        var (job, run, _) = await first.StateAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(1, job.FinalizationAttemptCount);
        Assert.Equal(1, await first.TrackCountAsync(run.Id));
        Assert.Equal(1L, await first.VisibilityAllocationsAsync());
        var claimed = first.Logs.Entries.Count(x => x.EventId.Id == 1502) + second.Logs.Entries.Count(x => x.EventId.Id == 1502);
        Assert.Equal(1, claimed);
        Assert.Equal(1, first.Logs.Entries.Count(x => x.EventId.Id == 1504) + second.Logs.Entries.Count(x => x.EventId.Id == 1504));
    }

    [Fact]
    public async Task TwoHostsShareTwoJobsWithoutOverlap()
    {
        using var first = await FinalizationWorld.CreateAsync();
        using var second = await FinalizationWorld.CreateAsync(sharedWith: first);
        var a = await first.HandOffAsync(cameraCode: "CAM-A");
        var b = await first.HandOffAsync(cameraCode: "CAM-B");

        await Task.WhenAll(first.Host().RunCycleAsync(CancellationToken.None), second.Host().RunCycleAsync(CancellationToken.None));

        Assert.Equal(VisionJobStatus.Completed, (await first.JobAsync(a.Lease.JobId)).Status);
        Assert.Equal(VisionJobStatus.Completed, (await first.JobAsync(b.Lease.JobId)).Status);
        Assert.Equal(2L, await first.VisibilityAllocationsAsync());
        Assert.Equal(2, first.Logs.Entries.Count(x => x.EventId.Id == 1502) + second.Logs.Entries.Count(x => x.EventId.Id == 1502));
    }

    // -- the janitor racing a Finalizing job (row 9 avoided) -----------------------------------

    [Fact]
    public async Task JanitorCyclesDuringFinalizingNeverRemoveTheInputAndTheFinalizerSucceeds()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        world.Clock.Advance(TimeSpan.FromDays(2)); // far beyond any grace

        using (var scope = world.Factory.Services.CreateScope())
        {
            var janitor = scope.ServiceProvider.GetRequiredService<IStagingJanitor>();
            var cycle = await janitor.RunCycleAsync(CancellationToken.None);
            Assert.Equal(0, cycle.Removed);
        }

        Assert.True(Directory.Exists(world.StagingAttemptPath(handOff.Lease)));
        // The deadline (6 h) has passed by now: reconciliation exhausts rather than publishes,
        // which is the honest outcome; what matters here is that the janitor did not decide it.
        world.Clock.Advance(TimeSpan.FromMinutes(-2880 + 10)); // back to 10 minutes after the hand-off
        await world.Host().RunCycleAsync(CancellationToken.None);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);
    }

    [Fact]
    public async Task JanitorReclaimsTheAttemptOnlyAfterTheFinalizerIsDoneAndGraceHasPassed()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        await world.Host().RunCycleAsync(CancellationToken.None);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);

        using var scope = world.Factory.Services.CreateScope();
        var janitor = scope.ServiceProvider.GetRequiredService<IStagingJanitor>();
        Assert.Equal(0, (await janitor.RunCycleAsync(CancellationToken.None)).Removed);
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        Assert.Equal(1, (await janitor.RunCycleAsync(CancellationToken.None)).Removed);
        Assert.False(Directory.Exists(world.StagingAttemptPath(handOff.Lease)));
        // Accepted evidence is untouched by the janitor.
        Assert.Equal(5, world.EvidenceFiles().Length);
    }

    // -- status and UI truthfulness (F3 plan §19 I11) -----------------------------------------

    [Fact]
    public async Task StatusShowsFinalizingUntilPublicationThenCompletedWithCounts()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        _ = await world.ClaimAsync();
        world.Clock.Advance(TimeSpan.FromMinutes(1));

        var before = await StatusAsync(handOff);
        Assert.Equal("Running", before.GetProperty("status").GetString());
        Assert.Equal("finalizing", before.GetProperty("phase").GetString());
        Assert.Equal(0, before.GetProperty("tracksCreated").GetInt32());
        Assert.Equal(JsonValueKind.Null, before.GetProperty("completedAtUtc").ValueKind);

        world.Clock.Advance(TimeSpan.FromMinutes(6));
        await world.Host().RunCycleAsync(CancellationToken.None);

        var after = await StatusAsync(handOff);
        Assert.Equal("Completed", after.GetProperty("status").GetString());
        Assert.Equal("completed", after.GetProperty("phase").GetString());
        Assert.Equal(1, after.GetProperty("tracksCreated").GetInt32());
        Assert.Equal(world.Clock.GetUtcNow(), after.GetProperty("completedAtUtc").GetDateTimeOffset());
    }

    [Fact]
    public async Task FinalizationFailureIsNotLabelledAsAnInferenceFailure()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        File.Delete(Path.Combine(world.StagingAttemptPath(handOff.Lease), "evidence", "person-000001-representative.jpg"));

        await world.Host().RunCycleAsync(CancellationToken.None);

        var status = await StatusAsync(handOff);
        Assert.Equal("Failed", status.GetProperty("status").GetString());
        Assert.Equal("failed", status.GetProperty("phase").GetString());
        var (job, run, _) = await world.StateAsync(handOff.Lease.JobId);
        Assert.Equal("vision_finalization_staging_missing", run.ErrorCode);
        Assert.StartsWith(VisionJob.FinalizationFailureCodePrefix, job.FailureCode!, StringComparison.Ordinal);
        Assert.DoesNotContain("detector", job.FailureCode, StringComparison.Ordinal);
        Assert.DoesNotContain("tracker", job.FailureCode, StringComparison.Ordinal);
    }

    // -- the final permitted claimant dies (row 17) through the host --------------------------

    [Fact]
    public async Task FinalPermittedClaimantDiesAndTheHostExhaustsTheJob()
    {
        using var world = await FinalizationWorld.CreateAsync(options: new VisionFinalizationOptions { Enabled = true, MaximumFinalizationAttempts = 1, ClaimSeconds = 300, ClaimExtensionSeconds = 300 });
        var handOff = await world.HandOffAsync();
        _ = await world.ClaimAsync(world.Factory.Services.GetRequiredService<Microsoft.Extensions.Options.IOptions<VisionFinalizationOptions>>().Value.ToPolicy());
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        await world.Host().RunCycleAsync(CancellationToken.None);

        var (job, run, video) = await world.StateAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal("vision_finalization_exhausted", job.FailureCode);
        Assert.Equal(ProcessingRunStatus.Failed, run.Status);
        Assert.Equal(VideoProcessingStatus.Failed, video.ProcessingStatus);
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1508);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        var status = await StatusAsync(handOff);
        Assert.Equal("failed", status.GetProperty("phase").GetString());
    }

    private static async Task<JsonElement> StatusAsync(FinalizationWorld.HandOff handOff)
    {
        using var response = await handOff.Client.GetAsync($"/api/videos/{handOff.Lease.VideoAssetId}/processing");
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("latestRun").Clone();
    }
}
