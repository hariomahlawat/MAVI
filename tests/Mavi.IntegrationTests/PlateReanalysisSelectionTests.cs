using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The run selection of an explicit plate re-analysis request (owner decision 2026-10-13):
/// window mode queues only the latest completed, visible run of each overlapping video — the highest
/// visibility sequence, which is unique — and applies the request bound after that selection; run-list
/// mode queues exactly the supplied runs and never substitutes newer ones; every request audits the exact
/// selected run ids.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateReanalysisSelectionTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);

    /// <summary>Another completed run of the same video, made visible (or not) after every earlier one.</summary>
    private static async Task<Guid> RerunAsync(PlateApiHost host, Guid existingRunId, bool visible = true, int vehicles = 1)
    {
        await using var db = host.World.Read();
        var videoId = await db.ProcessingRuns.AsNoTracking().Where(run => run.Id == existingRunId).Select(run => run.VideoAssetId).SingleAsync();
        var completed = T0.AddMinutes(-30);
        var run = ProcessingRun.Create(videoId, "phase1-detection-tracking-v1", "{}", completed.AddMinutes(-5));
        run.MarkRunning("vision-01", completed.AddMinutes(-4));
        run.MarkCompleted(100, vehicles, 1_000, completed);
        db.ProcessingRuns.Add(run);
        for (var number = 1; number <= vehicles; number++)
            db.Tracks.Add(Track.Create(run.Id, videoId, number, ObjectClass.Vehicle, 0, 4_000, T0.AddHours(-1), 4, 0.8, 0.9, completed));
        await db.SaveChangesAsync();
        if (visible)
        {
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE processing_runs SET visibility_sequence = nextval('processing_visibility_sequence') WHERE id = {run.Id}");
        }

        return run.Id;
    }

    private static async Task<PlateApiHost> HostAsync(PostgresFixture fixture, int maximumRuns = 100)
    {
        var host = await PlateApiHost.CreateAsync(fixture, T0,
            configuration: new Dictionary<string, string?> { ["Plates:MaximumRunsPerReanalysisRequest"] = maximumRuns.ToString(System.Globalization.CultureInfo.InvariantCulture) });
        return host;
    }

    private static object Window(PlateApiHost host) => new { cameraId = host.World.CameraId, fromUtc = T0.AddDays(-1), toUtc = T0.AddDays(1) };

    private static async Task<List<Guid>> QueuedRunsAsync(PlateApiHost host)
    {
        await using var db = host.World.Read();
        return await db.PlateAnalyses.AsNoTracking().Select(unit => unit.ProcessingRunId).ToListAsync();
    }

    private static List<Guid> Selected(JsonElement body) =>
        body.GetProperty("selectedRunIds").EnumerateArray().Select(item => item.GetGuid()).ToList();

    [Fact]
    public async Task WindowModeQueuesOnlyTheLatestVisibleRunOfEachVideo()
    {
        await using var host = await HostAsync(fixture);
        var videoA = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        var videoB = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        var latestA = await RerunAsync(host, videoA.RunId);
        // A still newer run of video A that was never made visible is not "latest visible".
        await RerunAsync(host, videoA.RunId, visible: false);
        await host.RunCycleAsync();

        using var response = await host.ReanalysisAsync(Window(host));
        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        // Ordered by recording start, then video: A was seeded first.
        Assert.Equal([latestA, videoB.RunId], Selected(body));
        Assert.Equal(2, body.GetProperty("queued").GetInt32());
        Assert.Equal(new HashSet<Guid> { latestA, videoB.RunId }, (await QueuedRunsAsync(host)).ToHashSet());

        // The audit names the exact selection.
        var audit = host.Logs.Entries.Single(entry => entry.EventId.Id == 2125).Message;
        Assert.Contains($"{latestA},{videoB.RunId}", audit, StringComparison.Ordinal);
    }

    [Fact]
    public async Task TheBoundAppliesAfterThePerVideoSelection()
    {
        await using var host = await HostAsync(fixture, maximumRuns: 2);
        var videoA = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        await RerunAsync(host, videoA.RunId);
        var latestA = await RerunAsync(host, videoA.RunId);
        var videoB = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        await host.RunCycleAsync();

        // Four runs overlap the window, but only two are selected: within the bound.
        using (var accepted = await host.ReanalysisAsync(Window(host)))
        {
            Assert.Equal(HttpStatusCode.Accepted, accepted.StatusCode);
            Assert.Equal([latestA, videoB.RunId], Selected(await accepted.Content.ReadFromJsonAsync<JsonElement>()));
        }

        // A third video takes the selection over the bound: refused as a whole, nothing more queued.
        await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        using (var refused = await host.ReanalysisAsync(Window(host)))
            Assert.Equal("plate_reanalysis_too_many_runs", await VisualAttributeApiHost.ProblemCodeAsync(refused));
        Assert.Equal(2, (await QueuedRunsAsync(host)).Count);
        // A refused request is audited too: its scope and refusal code.
        Assert.Contains("camera-window", Assert.Single(host.Logs.Entries, entry => entry.EventId.Id == 2126).Message, StringComparison.Ordinal);
        Assert.Contains("plate_reanalysis_too_many_runs", host.Logs.Entries.Single(entry => entry.EventId.Id == 2126).Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ALatestRunWithoutVehiclesIsNotEligibleAndNoOlderRunIsSubstituted()
    {
        await using var host = await HostAsync(fixture);
        var video = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        var latest = await RerunAsync(host, video.RunId, vehicles: 0);
        await host.RunCycleAsync();

        using var response = await host.ReanalysisAsync(Window(host));
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal([latest], Selected(body));
        Assert.Equal((0, 1), (body.GetProperty("queued").GetInt32(), body.GetProperty("notEligible").GetInt32()));
        Assert.Empty(await QueuedRunsAsync(host));
    }

    [Fact]
    public async Task RunListModeQueuesExactlyTheSuppliedRunsNeverNewerOnes()
    {
        await using var host = await HostAsync(fixture);
        var video = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        await RerunAsync(host, video.RunId);
        await host.RunCycleAsync();

        using var response = await host.ReanalysisAsync(new { processingRunIds = new[] { video.RunId } });
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal([video.RunId], Selected(body));
        Assert.Equal([video.RunId], await QueuedRunsAsync(host));
    }

    [Fact]
    public async Task VisibilitySequencesAreUniqueSoLatestHasNoTie()
    {
        await using var host = await HostAsync(fixture);
        var video = await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: T0.AddHours(-2));
        var other = await RerunAsync(host, video.RunId, visible: false);
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "UPDATE processing_runs SET visibility_sequence = (SELECT visibility_sequence FROM processing_runs WHERE id = $1) WHERE id = $2", connection);
        command.Parameters.AddWithValue(video.RunId);
        command.Parameters.AddWithValue(other);
        var exception = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
        Assert.Equal("ux_processing_runs_visibility_sequence", exception.ConstraintName);
    }
}
