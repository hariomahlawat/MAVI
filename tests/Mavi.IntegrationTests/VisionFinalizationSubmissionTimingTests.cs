using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>
/// F2 diagnostic timing of the completion 3.1 hand-off (S1.4 B3 asynchronous finalization plan
/// §14.1). It measures validation, payload encoding, PostgreSQL persistence and total wall time
/// through the real store, and prints them. It is <b>not</b> the B3-A qualification: that is
/// F4's authoritative measurement at the frozen SHA on a qualified host, and nothing here is a
/// PASS. It only proves the measurement exists and that the path has no synchronous sealing.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationSubmissionTimingTests(ITestOutputHelper output)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];
    private const string TracksVariable = "MAVI_F2_TIMING_TRACKS";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    [Fact]
    public async Task HandOffTimingsAreMeasuredThroughTheRealStore()
    {
        // Default shape keeps the quality gate fast; the full contract envelope
        // (10,000 Tracks x 4 observations) is opted into with MAVI_F2_TIMING_TRACKS=10000.
        var trackCount = int.TryParse(Environment.GetEnvironmentVariable(TracksVariable), NumberStyles.None, CultureInfo.InvariantCulture, out var configured)
            && configured is > 0 and <= WorkerContractRules.MaximumCompletionTracks
            ? configured
            : 500;

        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = WorstShapeRequest(lease, trackCount);
        var bodyBytes = JsonSerializer.SerializeToUtf8Bytes(request, Json).LongLength;

        VisionFinalizationSubmissionResult result;
        var wall = Stopwatch.StartNew();
        using (var scope = factory.Services.CreateScope())
        {
            var store = scope.ServiceProvider.GetRequiredService<IVisionFinalizationSubmissionStore>();
            result = await store.SubmitAsync(lease.JobId, lease.WorkerId, lease.LeaseToken, request, CancellationToken.None);
        }
        wall.Stop();

        Assert.True(result.IsSuccess, result.ErrorCode);
        Assert.Equal("finalizing", result.State);
        Assert.Equal(trackCount, result.TracksSubmitted);
        var timings = Assert.IsType<VisionFinalizationSubmissionTimings>(result.Timings);
        Assert.True(timings.Validation > TimeSpan.Zero);
        Assert.True(timings.PayloadEncoding > TimeSpan.Zero);
        Assert.True(timings.Persistence > TimeSpan.Zero);
        Assert.True(timings.Total >= timings.Validation + timings.PayloadEncoding + timings.Persistence);

        long payloadLength;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            payloadLength = await db.VisionFinalizationPayloads.Select(x => x.PayloadLength).SingleAsync();
        }

        output.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"F2 hand-off diagnostic (not a qualification verdict): tracks={trackCount}, requestBody={bodyBytes:N0} B, " +
            $"retainedPayload={payloadLength:N0} B, validation={timings.Validation.TotalMilliseconds:F1} ms, " +
            $"encoding={timings.PayloadEncoding.TotalMilliseconds:F1} ms, persistence={timings.Persistence.TotalMilliseconds:F1} ms, " +
            $"total={timings.Total.TotalMilliseconds:F1} ms, storeWall={wall.Elapsed.TotalMilliseconds:F1} ms"));

        // The same body replays idempotently through HTTP, and the replay validates without persisting.
        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        Assert.Equal("finalizing", (await replay.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!.State);
    }

    // Declared sizes stay small: the run-level evidence quotas (plan §7) bound the *sum* of
    // crop and trajectory bytes, so the contract maximum of Tracks cannot carry cap-sized
    // artefacts. The document size, which is what the hand-off pays for, does not depend on them.
    private const long CropBytes = 2048;

    /// <summary>
    /// <paramref name="trackCount"/> Tracks, each with all four roles and the longest canonical
    /// numbers and track ids (the WorkerContractV3Tests worst document shape), keyed to this
    /// lease. Nothing is staged: the 3.1 hand-off validates keys and bounds and seals nothing.
    /// </summary>
    private static VisionJobCompleteRequest WorstShapeRequest(VisionJobLeaseContract lease, int trackCount)
    {
        var prefix = $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}";
        const double longDouble = 0.12345678901234568;
        var sha = new string('f', 64);
        // The same per-Track shape the single-Track hand-off tests use, at the byte caps, times trackCount.
        var tracks = Enumerable.Range(0, trackCount).Select(index =>
        {
            var trackId = new string('a', 58) + index.ToString("D6", CultureInfo.InvariantCulture);
            return new VisionTrackResultContract(
                trackId, "vehicle", 0, 1000, 4, longDouble, longDouble, null,
                new VisionArtifactDescriptorContract($"{prefix}/trajectories/{trackId}.msgpack", "application/msgpack", 4096, sha),
                [.. Roles.Select((role, rank) => new VisionTrackObservationContract(
                    role, rank, 250 + rank * 250, rank, longDouble, longDouble, longDouble,
                    new VisionBoundingBoxContract(longDouble, longDouble, longDouble, longDouble),
                    new VisionArtifactDescriptorContract($"{prefix}/evidence/{trackId}-{role}.jpg", "image/jpeg", CropBytes, sha)))]);
        }).ToArray();
        VisionEvidenceRoleAccountingContract Role(long cropBytes) =>
            new(trackCount, trackCount, 0, (long)trackCount * cropBytes, (long)trackCount * cropBytes);
        return new VisionJobCompleteRequest(
            WorkerContractRules.CompletionSchemaVersionV31, lease.JobId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
            4, 1250, VisionResultCompletionApiTests.Provenance(), tracks,
            new VisionEvidenceAccountingContract(Role(CropBytes), Role(CropBytes), Role(CropBytes), Role(CropBytes)));
    }
}
