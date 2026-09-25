using System.Diagnostics;
using System.Globalization;
using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Finalization;
using Microsoft.Extensions.DependencyInjection;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The finalizer at scale, as a diagnostic (F3 plan §15.4): a hand-off of N Tracks with real
/// staged objects, finalized through the real executor, lifecycle and store, with seal, graph
/// and publication timings and the working set before and after. Not a qualification verdict
/// and asserted against no bound: F4 freezes the bounds. The default shape keeps the quality
/// gate fast; <c>MAVI_F3_TIMING_TRACKS=10000</c> opts into the contract envelope.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationTimingTests(ITestOutputHelper output)
{
    private const string TracksVariable = "MAVI_F3_TIMING_TRACKS";

    [Fact]
    public async Task FinalizationTimingsAreMeasuredThroughTheRealExecutor()
    {
        var trackCount = int.TryParse(Environment.GetEnvironmentVariable(TracksVariable), NumberStyles.None, CultureInfo.InvariantCulture, out var configured)
            && configured is > 0 and <= WorkerContractRules.MaximumCompletionTracks
            ? configured
            : 200;

        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync(lease => StagedRequestAsync(world, lease, trackCount));
        Assert.Equal(trackCount, handOff.Ack.TracksSubmitted);
        var rssBefore = Process.GetCurrentProcess().WorkingSet64;
        var claim = (await world.ClaimAsync())!;

        var wall = Stopwatch.StartNew();
        var outcome = await world.Factory.Services.GetRequiredService<VisionFinalizationExecutor>().ExecuteAsync(claim, world.Policy, CancellationToken.None);
        wall.Stop();
        var rssAfter = Process.GetCurrentProcess().WorkingSet64;

        Assert.Equal(VisionFinalizationExecutionKind.Published, outcome.Kind);
        Assert.Equal(trackCount * 5, outcome.Sealing.Created);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(claim.JobId)).Status);
        Assert.Equal(trackCount, await world.TrackCountAsync(claim.ProcessingRunId));
        var published = Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1504);

        output.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"F3 finalization diagnostic (not a qualification verdict): tracks={trackCount}, objects={outcome.Sealing.Total}, " +
            $"executorWall={wall.Elapsed.TotalMilliseconds:F1} ms, rssBefore={rssBefore / (1024 * 1024)} MiB, rssAfter={rssAfter / (1024 * 1024)} MiB; {published.Message}"));
    }

    /// <summary>N Tracks with all four roles, every crop and trajectory really staged for this lease.</summary>
    private static async Task<VisionJobCompleteRequest> StagedRequestAsync(FinalizationWorld world, VisionJobLeaseContract lease, int trackCount)
    {
        var store = world.Factory.Services.GetRequiredService<IMediaStore>();
        var prefix = $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}";
        var roles = FinalizationWorld.AllRoles;

        var tracks = new List<VisionTrackResultContract>(trackCount);
        var roleBytes = new long[roles.Length];
        for (var index = 0; index < trackCount; index++)
        {
            var trackId = $"person-{index + 1:000000}";
            var observations = new List<VisionTrackObservationContract>();
            for (var rank = 0; rank < roles.Length; rank++)
            {
                var key = $"{prefix}/evidence/{trackId}-{roles[rank]}.jpg";
                var stored = await store.WriteAsync(key, new MemoryStream(Encoding.UTF8.GetBytes($"crop-{trackId}-{roles[rank]}")), CancellationToken.None);
                roleBytes[rank] += stored.SizeBytes;
                observations.Add(new VisionTrackObservationContract(
                    roles[rank], rank, 250 + rank * 250, rank, .88, .8 - rank * .1, .8 - rank * .1,
                    new VisionBoundingBoxContract(.1, .2, .3, .4),
                    new VisionArtifactDescriptorContract(key, "image/jpeg", stored.SizeBytes, stored.Sha256)));
            }

            var trajectoryKey = $"{prefix}/trajectories/{trackId}.msgpack";
            var trajectory = await store.WriteAsync(trajectoryKey, new MemoryStream(Encoding.UTF8.GetBytes($"trajectory-{trackId}")), CancellationToken.None);
            tracks.Add(new VisionTrackResultContract(
                trackId, "person", 0, 1000, 4, .85, .9, null,
                new VisionArtifactDescriptorContract(trajectoryKey, "application/msgpack", trajectory.SizeBytes, trajectory.Sha256),
                observations));
        }

        VisionEvidenceRoleAccountingContract Role(int rank) => new(trackCount, trackCount, 0, roleBytes[rank], roleBytes[rank]);
        return new VisionJobCompleteRequest(
            WorkerContractRules.CompletionSchemaVersionV31, lease.JobId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
            4, 1250, VisionResultCompletionApiTests.Provenance(), tracks,
            new VisionEvidenceAccountingContract(Role(0), Role(1), Role(2), Role(3)));
    }
}
