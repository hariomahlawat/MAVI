using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Text;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Plates;
using Microsoft.EntityFrameworkCore;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The synchronous plate completion at the supported bound, measured the way the attribute plane's
/// was (S2b implementation record §5.2). Lease, upload and completion of N Vehicle Tracks × 4 accepted
/// crops go through the real HTTP routes under the bounded v1 profile (2 proposals, 1 plate,
/// 3 readings) at its row-worst admitted shape (the most rows and work; not the byte-worst artefact, whose
/// fit is guaranteed by the worst-case bound vector, not by this test):
/// <list type="bullet">
/// <item>every crop scored with both proposals;</item>
/// <item>one plate read with three readings above the floor;</item>
/// <item>every raw text at the maximum 32 code units, each escaped as <c>\uXXXX</c>;</item>
/// <item>one distinct Track text per plate.</item>
/// </list>
/// Phase and barrier timings come from the publication log (event 2100). <c>MAVI_PLATE_TIMING_TRACKS=10000</c>
/// opts into the contract bound; the default keeps the quality gate fast. The figures are recorded in
/// <c>docs/qualification/stage4/2026-10-13-plate-completion-at-the-track-bound.md</c>. This test asserts
/// the artefact is within its worst-case bound and the 64 MiB cap, and the 15 s request budget that
/// ADR-006 §7 applies to completion requests.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateCompletionTimingTests(PostgresFixture fixture, ITestOutputHelper output)
{
    private const string TracksVariable = "MAVI_PLATE_TIMING_TRACKS";
    private static readonly TimeSpan RequestBudget = TimeSpan.FromSeconds(15);

    /// <summary>
    /// A 32-code-unit raw text unique to (Track, crop, reading). It uses fullwidth digits and capitals:
    /// each is escaped as <c>\uXXXX</c> (the worst-case encoding), and each normalises (NFKC) to one ASCII
    /// alphanumeric, so every plate is read and yields a distinct Track text.
    /// </summary>
    private static string WorstRawText(int track, int crop, int reading)
    {
        var value = ((long)track * 4 + crop) * 3 + reading;
        var text = new StringBuilder(PlateContractRules.MaximumRawTextLength);
        for (var position = 0; position < PlateContractRules.MaximumRawTextLength; position++)
        {
            var digit = (int)(value % 36);
            value /= 36;
            text.Insert(0, (char)(digit < 10 ? 0xFF10 + digit : 0xFF21 + digit - 10));
        }

        return text.ToString();
    }

    [Fact]
    public async Task AWorstShapeCompletionAtTheTrackBoundIsMeasured()
    {
        var trackCount = int.TryParse(Environment.GetEnvironmentVariable(TracksVariable), NumberStyles.None, CultureInfo.InvariantCulture, out var configured)
            && configured is > 0 and <= PlateContractRules.MaximumAnalysisTracks
            ? configured
            : 200;

        await using var host = await PlateApiHost.CreateAsync(fixture, new DateTimeOffset(2026, 10, 13, 12, 0, 0, TimeSpan.Zero));
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var seeding = Stopwatch.StartNew();
        await host.World.SeedRunAsync(0, trackCount, 4, writeFiles: false, completedAtUtc: host.World.Clock.GetUtcNow());
        seeding.Stop();
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);

        var leaseWall = Stopwatch.StartNew();
        using var leaseResponse = await host.PostLeaseAsync("plates-01");
        var leaseBytes = (await leaseResponse.Content.ReadAsByteArrayAsync()).LongLength;
        leaseWall.Stop();
        Assert.Equal(HttpStatusCode.OK, leaseResponse.StatusCode);
        Assert.InRange(leaseBytes, 1, PlateContractRules.MaximumLeaseResponseBytes);
        var lease = (await System.Net.Http.Json.HttpContentJsonExtensions.ReadFromJsonAsync<PlateLeaseContract>(leaseResponse.Content))!;
        var unit = new LeasedPlateUnit(lease, Assert.Single(leaseResponse.Headers.GetValues(PlateContractRules.CapabilityHeader)), "plates-01");
        Assert.Equal(trackCount, lease.Tracks.Count);

        var completion = PlateCompletionBuilder.Build(lease, (track, crop) => PlateCropSpec.Scored(
            new PlateProposal(40, 100, 60, 15, 0.9,
                [(WorstRawText(track, crop, 0), 0.9), (WorstRawText(track, crop, 1), 0.8), (WorstRawText(track, crop, 2), 0.7)]),
            new PlateProposal(120, 20, 50, 12, 0.8, [])));
        var bound = PlateContractRules.WorstCasePredictionArtifactBytes(
            PlateContractRules.MaximumDetectionsPerCrop, PlateContractRules.MaximumPlatesPerCrop, PlateContractRules.MaximumReadingsPerPlate);
        var requestBytes = System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(completion.Request, System.Text.Json.JsonSerializerOptions.Web).LongLength;
        Assert.True(completion.Predictions.LongLength <= bound, $"artefact {completion.Predictions.LongLength} B over its bound {bound} B");
        Assert.True(completion.Predictions.LongLength <= PlateContractRules.MaximumPredictionArtifactBytes);
        Assert.True(requestBytes <= PlateContractRules.MaximumCompletionRequestBodyBytes);

        var uploadWall = Stopwatch.StartNew();
        using (var uploaded = await host.UploadAsync(unit, completion.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        uploadWall.Stop();

        // Process memory during the completion request alone: the working set sampled every 10 ms against
        // its value just before, and the managed bytes allocated meanwhile (platform and client share it).
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();
        using var process = Process.GetCurrentProcess();
        process.Refresh();
        var workingSetBefore = process.WorkingSet64;
        var peakWorkingSet = workingSetBefore;
        using var sampling = new CancellationTokenSource();
        var sampler = Task.Run(async () =>
        {
            using var sampled = Process.GetCurrentProcess();
            while (!sampling.IsCancellationRequested)
            {
                sampled.Refresh();
                peakWorkingSet = Math.Max(peakWorkingSet, sampled.WorkingSet64);
                try
                {
                    await Task.Delay(10, sampling.Token);
                }
                catch (OperationCanceledException)
                {
                }
            }
        });
        var allocatedBefore = GC.GetTotalAllocatedBytes(precise: true);
        var completeWall = Stopwatch.StartNew();
        using (var completed = await host.CompleteAsync(unit, completion.Request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        completeWall.Stop();
        var allocated = GC.GetTotalAllocatedBytes(precise: true) - allocatedBefore;
        await sampling.CancelAsync();
        await sampler;

        int outcomes, observations, readings, texts;
        await using (var db = host.World.Read())
        {
            outcomes = await db.PlateTrackOutcomes.CountAsync(x => x.AnalysisId == unit.AnalysisId);
            observations = await db.PlateObservations.CountAsync(x => x.AnalysisId == unit.AnalysisId);
            readings = await db.PlateReadings.CountAsync();
            texts = await db.PlateTrackTexts.CountAsync(x => x.AnalysisId == unit.AnalysisId);
            // ADR-018: the COPY publication (untouched) gets every text's Track start from the trigger.
            Assert.Equal(0L, await db.Database.SqlQuery<long>(
                $"SELECT count(*) AS \"Value\" FROM plate_track_texts x JOIN tracks t ON t.id = x.track_id WHERE x.analysis_id = {unit.AnalysisId} AND x.track_start_timestamp_utc IS DISTINCT FROM t.start_timestamp_utc")
                .SingleAsync());
        }

        Assert.Equal((trackCount, trackCount * 4, trackCount * 12, trackCount * 4), (outcomes, observations, readings, texts));
        var published = Assert.Single(host.Logs.Entries, entry => entry.EventId.Id == 2100);
        output.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"S4 plate completion measurement: tracks={trackCount}, crops={trackCount * 4}, " +
            $"rows: outcomes={outcomes}, plateObservations={observations}, readings={readings}, trackTexts={texts}; " +
            $"leaseResponseBytes={leaseBytes}, leaseWall={leaseWall.Elapsed.TotalMilliseconds:F1} ms, " +
            $"artefactBytes={completion.Predictions.LongLength} (bound {bound}, cap {PlateContractRules.MaximumPredictionArtifactBytes}), " +
            $"uploadWall={uploadWall.Elapsed.TotalMilliseconds:F1} ms, completionBodyBytes={requestBytes}, " +
            $"completionWall={completeWall.Elapsed.TotalMilliseconds:F1} ms, " +
            $"workingSetBefore={workingSetBefore / 1048576.0:F1} MiB, peakWorkingSetDuringCompletion={peakWorkingSet / 1048576.0:F1} MiB " +
            $"(+{(peakWorkingSet - workingSetBefore) / 1048576.0:F1} MiB), managedAllocatedDuringCompletion={allocated / 1048576.0:F1} MiB, " +
            $"seeding={seeding.Elapsed.TotalSeconds:F1} s; {published.Message}"));

        Assert.True(completeWall.Elapsed < RequestBudget, $"completion took {completeWall.Elapsed}");
        Assert.Equal(WorkerContractRules.MaximumCompletionTracks, PlateContractRules.MaximumAnalysisTracks);
    }
}
