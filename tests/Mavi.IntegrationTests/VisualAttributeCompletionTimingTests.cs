using System.Diagnostics;
using System.Globalization;
using System.Net;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Attributes;
using Microsoft.EntityFrameworkCore;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The synchronous attribute completion at scale (S2b plan §13): lease, upload and completion
/// of N person Tracks × 4 accepted crops — the worst lease shape and the fixture's worst row
/// shape — through the real HTTP routes, with phase and barrier timings from the publication
/// log. <c>MAVI_S2B_TIMING_TRACKS=10000</c> opts into the contract bound; the default keeps
/// the quality gate fast. The decision the 10,000-Track numbers support is recorded in the
/// implementation record §5; this test asserts only the 15 s lease-bound request budget
/// ADR-006 §7 applies to completion requests.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeCompletionTimingTests(PostgresFixture fixture, ITestOutputHelper output)
{
    private const string TracksVariable = "MAVI_S2B_TIMING_TRACKS";
    private static readonly TimeSpan RequestBudget = TimeSpan.FromSeconds(15);

    /// <summary>The worst row shape the schema bounds admit: the per-class maximum of 8 attribute types.</summary>
    private static readonly IReadOnlyDictionary<string, string[]> WorstRows = new Dictionary<string, string[]>
    {
        ["person"] = Enumerable.Range(0, VisualAttributeContractRules.MaximumAttributeTypesPerObjectClass).Select(index => $"w-person-{index}").ToArray(),
        ["vehicle"] = ["w-vehicle-0"],
    };

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ASynchronousCompletionAtTheTrackBoundIsMeasured(bool worstRowShape)
    {
        var types = worstRowShape ? WorstRows : AttributeCompletionBuilder.TypesByClass;
        var profileDirectory = Path.Combine(Path.GetTempPath(), $"mavi-va-profile-{Guid.NewGuid():N}");
        var profile = worstRowShape ? VisualAttributeReleaseFixture.WriteProfile(profileDirectory, WorstRows) : null;
        var trackCount = int.TryParse(Environment.GetEnvironmentVariable(TracksVariable), NumberStyles.None, CultureInfo.InvariantCulture, out var configured)
            && configured is > 0 and <= WorkerContractRules.MaximumCompletionTracks
            ? configured
            : 200;

        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, new DateTimeOffset(2026, 9, 28, 12, 0, 0, TimeSpan.Zero),
            pipelineProfile: profile);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var seeding = Stopwatch.StartNew();
        var run = await host.World.SeedRunAsync(trackCount, 0, 4, completedAtUtc: host.World.Clock.GetUtcNow());
        seeding.Stop();
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);

        var leaseWall = Stopwatch.StartNew();
        using var leaseResponse = await host.PostLeaseAsync("attributes-01");
        var leaseBytes = (await leaseResponse.Content.ReadAsByteArrayAsync()).LongLength;
        leaseWall.Stop();
        Assert.Equal(HttpStatusCode.OK, leaseResponse.StatusCode);
        Assert.InRange(leaseBytes, 1, VisualAttributeContractRules.MaximumLeaseResponseBytes);
        var unit = await ReadLeaseAsync(leaseResponse);
        Assert.Equal(trackCount, unit.Lease.Tracks.Count);

        var completion = AttributeCompletionBuilder.Build(unit, typesByClass: types);
        var rowsPerTrack = types["person"].Length;
        var requestBytes = AttributeCompletionBuilder.Serialize(completion.Request).Length;
        var uploadWall = Stopwatch.StartNew();
        using (var uploaded = await host.UploadAsync(unit, completion.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        uploadWall.Stop();

        var completeWall = Stopwatch.StartNew();
        using (var completed = await host.CompleteAsync(unit, completion.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        completeWall.Stop();

        await using (var db = host.World.Read())
            Assert.Equal(trackCount * rowsPerTrack, await db.VisualAttributes.CountAsync(x => x.AnalysisId == unit.AnalysisId));
        var published = Assert.Single(host.Logs.Entries, entry => entry.EventId.Id == 1990);
        output.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"S2b completion measurement: shape={(worstRowShape ? "worst-rows" : "fixture")}, tracks={trackCount}, crops={trackCount * 4}, rows={trackCount * rowsPerTrack}, " +
            $"leaseResponseBytes={leaseBytes}, leaseWall={leaseWall.Elapsed.TotalMilliseconds:F1} ms, " +
            $"artefactBytes={completion.Predictions.Length}, uploadWall={uploadWall.Elapsed.TotalMilliseconds:F1} ms, " +
            $"completionBodyBytes={requestBytes}, completionWall={completeWall.Elapsed.TotalMilliseconds:F1} ms, " +
            $"seeding={seeding.Elapsed.TotalSeconds:F1} s; {published.Message}"));

        Assert.True(completeWall.Elapsed < RequestBudget, $"completion took {completeWall.Elapsed}");
        _ = run;
        if (Directory.Exists(profileDirectory)) Directory.Delete(profileDirectory, recursive: true);
    }

    private static async Task<LeasedUnit> ReadLeaseAsync(HttpResponseMessage response)
    {
        var lease = await System.Net.Http.Json.HttpContentJsonExtensions.ReadFromJsonAsync<VisualAttributeLeaseContract>(response.Content);
        return new LeasedUnit(lease!, Assert.Single(response.Headers.GetValues(VisualAttributeContractRules.CapabilityHeader)), "attributes-01");
    }
}
