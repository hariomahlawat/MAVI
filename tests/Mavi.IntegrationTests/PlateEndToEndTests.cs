using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The Stage-4 fixture end to end (plan §7 PR-3 acceptance): the real <c>mavi_vision.plates.main</c>
/// process, composed from a derived Development overlay through the real resolver, against the real
/// platform on a real socket — lease, concurrent heartbeat, authorised evidence reads with byte
/// verification, decode, fixture detection and recognition, canonical artefact upload, three-phase
/// completion and publication — ending with the run's plate readiness <c>Ready</c>. Then a worker process
/// killed mid-attempt is shown to cost only its own lease: the lease expires and is reclaimed, a new attempt
/// completes, no partial plate fact is ever visible, and the run, its Tracks, Observations and attribute
/// unit are untouched. Skipped (never passed) without the worker's Python environment.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateEndToEndTests(PostgresFixture fixture, ITestOutputHelper output)
{
    private static readonly string VisionRoot = Path.Combine(VisualAttributeReleaseFixture.Root, "src", "vision");

    /// <summary>A 160x120 JPEG (one light band on grey) that Pillow decodes; every crop of the world uses it.</summary>
    private static readonly byte[] CropJpeg = Convert.FromBase64String(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAB4AKADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDnqKKKokKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAPSvCP/ItWn/A//Q2rYrH8I/8AItWn/A//AENq2KhlBRRRSAKKKKACqes/8gW+/wCveT/0E1cqnrP/ACBb7/r3k/8AQTQB5TRRRWhIUUUUAFFFFABRRRQAUUUUAFFFFAFmHUb6CIRQXtzHGvRUlYAfgDT/AO1tT/6CN3/3/b/GqdFAFz+1tT/6CN3/AN/2/wAaP7W1P/oI3f8A3/b/ABqnRQBc/tbU/wDoI3f/AH/b/Gj+1tT/AOgjd/8Af9v8ap0UAXP7W1P/AKCN3/3/AG/xpH1PUZEZJL+6ZGGGVpmII9DzVSigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q==");

    [AttributeWorkerFact]
    public async Task TheFixtureWorkerPublishesARunThroughTheRealLeasePlaneAndItIsReady()
    {
        var python = Environment.GetEnvironmentVariable(AttributeWorkerFactAttribute.PythonVariable)!;
        var overlayDirectory = Path.Combine(Path.GetTempPath(), $"mavi-plate-e2e-{Guid.NewGuid():N}");
        var overlay = await ComposeOverlayAsync(python, overlayDirectory);

        using var world = await VisualAttributeWorld.CreateAsync(fixture, DateTimeOffset.UtcNow);
        var logs = new VisionFinalizationSubmissionApiTests.CapturingLoggerProvider();
        await using var factory = new ApiTestFactory
        {
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
            PlateComponentBindingPath = overlay.GetProperty("componentBindingPath").GetString(),
            PlatePipelineProfilePath = overlay.GetProperty("pipelineProfilePath").GetString(),
            OverrideServices = services => services.AddSingleton<Microsoft.Extensions.Logging.ILoggerProvider>(logs),
        };
        factory.UseKestrel(0);
        factory.StartServer();
        using var client = factory.CreateClient();
        var cycle = factory.Services.GetRequiredService<Mavi.Api.Plates.PlateHostedService>();
        await cycle.RunCycleAsync(CancellationToken.None);

        // One person Track (not applicable) and two Vehicle Tracks with two decodable crops each;
        // one vehicle crop is gone from the evidence root (an authoritative evidence_missing).
        await Task.Delay(20);
        var run = await world.SeedRunAsync(1, 2, 2, completedAtUtc: DateTimeOffset.UtcNow, cropBytes: (_, _) => CropJpeg);
        var vehicles = run.Tracks.Where(track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Vehicle).ToList();
        var removed = vehicles[1].Observations[1];
        File.SetAttributes(world.EvidencePath(removed.StorageKey), FileAttributes.Normal);
        File.Delete(world.EvidencePath(removed.StorageKey));
        Assert.Equal(1, (await cycle.RunCycleAsync(CancellationToken.None)).Queued);

        var stdout = new StringBuilder();
        var worker = StartWorker(python, client.BaseAddress!, overlay, stdout, "plates-e2e-01");
        PlateAnalysis? unit = null;
        try
        {
            var deadline = Stopwatch.StartNew();
            while (deadline.Elapsed < TimeSpan.FromSeconds(90))
            {
                await using var db = world.Read();
                unit = await db.PlateAnalyses.AsNoTracking().SingleAsync();
                if (unit.Status is PlateAnalysisStatus.Completed or PlateAnalysisStatus.Failed || worker.HasExited) break;
                await Task.Delay(250);
            }
        }
        finally
        {
            if (!worker.HasExited) worker.Kill(entireProcessTree: true);
            await worker.WaitForExitAsync();
            output.WriteLine(stdout.ToString());
            if (Directory.Exists(overlayDirectory)) Directory.Delete(overlayDirectory, recursive: true);
        }

        Assert.NotNull(unit);
        Assert.Equal(PlateAnalysisStatus.Completed, unit.Status);
        Assert.Equal(1, unit.AttemptCount);
        // Both Vehicle Tracks had at least one scored crop; the missing crop is an unavailable crop, not a Track.
        Assert.Equal(2, unit.TracksAnalysed);

        await using (var db = world.Read())
        {
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == unit.PredictionArtifactId);
            Assert.Equal(ArtifactType.PlatePredictions, artifact.ArtifactType);
            var bytes = await File.ReadAllBytesAsync(world.EvidencePath(artifact.StorageKey));
            Assert.Equal(artifact.Sha256, Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes)));
            using var predictions = JsonDocument.Parse(bytes);
            var crops = predictions.RootElement.GetProperty("tracks").EnumerateArray().SelectMany(track => track.GetProperty("crops").EnumerateArray()).ToList();
            Assert.Equal(4, crops.Count);
            Assert.Equal("evidence_missing", crops.Single(crop => crop.GetProperty("observationId").GetGuid() == removed.ObservationId)
                .GetProperty("reason").GetString());
            // Every relational reading is a platform normalisation of the worker's raw text.
            var readings = await db.PlateReadings.AsNoTracking().ToListAsync();
            Assert.All(readings, reading => Assert.Equal(
                Mavi.Application.Modules.Plates.PlateNormalisation.Normalise(reading.RawText).Normalised, reading.NormalisedText));
            using var provenance = JsonDocument.Parse(unit.ProvenanceJson!);
            Assert.Equal("plates", provenance.RootElement.GetProperty("roleId").GetString());
            Assert.Equal(overlay.GetProperty("modelPackId").GetString(),
                provenance.RootElement.GetProperty("capabilities")[0].GetProperty("modelPackId").GetString());
        }

        var readiness = await client.GetFromJsonAsync<JsonElement>($"/api/processing/runs/{run.RunId}/plates");
        Assert.Equal("Ready", readiness.GetProperty("state").GetString());
        // Three crops were served and audited; the capability reached no log line of either process.
        Assert.Equal(3, logs.Entries.Count(entry => entry.EventId.Id == 2120));
        var tokenPattern = new System.Text.RegularExpressions.Regex("(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])");
        Assert.DoesNotMatch(tokenPattern, stdout.ToString());
        Assert.DoesNotMatch(tokenPattern, string.Join('\n', logs.Entries.Select(entry => entry.Message)));
    }

    [AttributeWorkerFact]
    public async Task AWorkerKilledMidAttemptCostsOnlyItsLeaseAndNoPartialFactIsEverVisible()
    {
        var python = Environment.GetEnvironmentVariable(AttributeWorkerFactAttribute.PythonVariable)!;
        var overlayDirectory = Path.Combine(Path.GetTempPath(), $"mavi-plate-crash-{Guid.NewGuid():N}");
        var overlay = await ComposeOverlayAsync(python, overlayDirectory);

        // The platform runs on a mutable clock so the minimum (60 s) lease can expire without waiting;
        // it starts at the real time, so the worker's own wall-clock lease guard agrees with it.
        using var world = await VisualAttributeWorld.CreateAsync(fixture, DateTimeOffset.UtcNow);
        var gate = new CompletionGate();
        await using var factory = new ApiTestFactory
        {
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
            Clock = world.Clock,
            PlateComponentBindingPath = overlay.GetProperty("componentBindingPath").GetString(),
            PlatePipelineProfilePath = overlay.GetProperty("pipelineProfilePath").GetString(),
            OverrideServices = services => services.AddSingleton<Microsoft.AspNetCore.Hosting.IStartupFilter>(gate),
        };
        factory.UseKestrel(0);
        factory.StartServer();
        using var client = factory.CreateClient();
        var cycle = factory.Services.GetRequiredService<Mavi.Api.Plates.PlateHostedService>();
        await cycle.RunCycleAsync(CancellationToken.None);

        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var run = await world.SeedRunAsync(1, 2, 2, completedAtUtc: world.Clock.GetUtcNow(), cropBytes: (_, _) => CropJpeg);
        Assert.Equal(1, (await cycle.RunCycleAsync(CancellationToken.None)).Queued);
        // An attribute unit of the same run, under its own plane.
        await using (var db = world.Read())
        {
            db.VisualAttributeAnalyses.Add(Mavi.Domain.VisualAttributes.VisualAttributeAnalysis.Queue(
                run.RunId, VisualAttributeTestIdentity.Fields(), world.Clock.GetUtcNow()));
            await db.SaveChangesAsync();
        }

        var before = await ReadPlatformFactsAsync();

        // Every plate fact table and the unit's publication, read in one statement (one snapshot),
        // sampled throughout: a fact row is never visible unless its unit is published, and the fact
        // count is only ever zero or the final count.
        using var watching = new CancellationTokenSource();
        var samples = new System.Collections.Concurrent.ConcurrentBag<(long Facts, long Published)>();
        var watcher = Task.Run(async () =>
        {
            await using var connection = new Npgsql.NpgsqlConnection(fixture.ConnectionString);
            await connection.OpenAsync();
            while (!watching.IsCancellationRequested)
            {
                await using (var command = new Npgsql.NpgsqlCommand("""
                    SELECT (SELECT count(*) FROM plate_track_outcomes) + (SELECT count(*) FROM plate_observations)
                         + (SELECT count(*) FROM plate_readings) + (SELECT count(*) FROM plate_track_texts),
                           (SELECT count(*) FROM plate_analyses WHERE status = 'Completed' AND visibility_sequence IS NOT NULL)
                    """, connection))
                await using (var reader = await command.ExecuteReaderAsync())
                {
                    await reader.ReadAsync();
                    samples.Add((reader.GetInt64(0), reader.GetInt64(1)));
                }

                await Task.Delay(50);
            }
        });

        var stdout = new StringBuilder();
        Process? first = null;
        Process? second = null;
        try
        {
            // Attempt 1 runs to its completion call (evidence read, artefact uploaded to staging) and is
            // killed there, holding a live lease, before the platform has seen the completion.
            first = StartWorker(python, client.BaseAddress!, overlay, stdout, "plates-e2e-01");
            await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(90));
            PlateAnalysis attempt1;
            await using (var db = world.Read())
                attempt1 = await db.PlateAnalyses.AsNoTracking().SingleAsync();
            Assert.Equal((PlateAnalysisStatus.Running, 1, "plates-e2e-01"), (attempt1.Status, attempt1.AttemptCount, attempt1.LeaseOwner));
            Assert.True(attempt1.LeaseExpiresAtUtc > world.Clock.GetUtcNow());
            var staged = Path.Combine(world.MediaRoot, "staging-plates", attempt1.Id.ToString(), "attempt-0001");
            Assert.True(Directory.Exists(staged) && Directory.EnumerateFiles(staged, "*", SearchOption.AllDirectories).Any(),
                "the killed attempt had staged its predictions artefact");

            first.Kill(entireProcessTree: true);
            await first.WaitForExitAsync();
            // The platform saw the connection die; attempt 1's completion was never processed.
            await gate.Abandoned.Task.WaitAsync(TimeSpan.FromSeconds(30));

            // Still attempt 1's lease, unexpired: nothing published, nobody else can take it yet.
            await using (var db = world.Read())
            {
                var unit = await db.PlateAnalyses.AsNoTracking().SingleAsync();
                Assert.Equal((PlateAnalysisStatus.Running, 1, (long?)null, (Guid?)null),
                    (unit.Status, unit.AttemptCount, unit.VisibilitySequence, unit.PredictionArtifactId));
            }

            Assert.Equal("Pending", (await client.GetFromJsonAsync<JsonElement>($"/api/processing/runs/{run.RunId}/plates")).GetProperty("state").GetString());
            Assert.Equal(before, await ReadPlatformFactsAsync());

            // The lease expires; a new worker reclaims the unit as attempt 2 and completes it.
            world.Clock.Advance(attempt1.LeaseExpiresAtUtc!.Value - world.Clock.GetUtcNow() + TimeSpan.FromSeconds(1));
            second = StartWorker(python, client.BaseAddress!, overlay, stdout, "plates-e2e-02");
            PlateAnalysis? unitAfter = null;
            var deadline = Stopwatch.StartNew();
            while (deadline.Elapsed < TimeSpan.FromSeconds(90))
            {
                await using var db = world.Read();
                unitAfter = await db.PlateAnalyses.AsNoTracking().SingleAsync();
                if (unitAfter.Status is PlateAnalysisStatus.Completed or PlateAnalysisStatus.Failed || second.HasExited) break;
                await Task.Delay(250);
            }

            Assert.NotNull(unitAfter);
            Assert.Equal((PlateAnalysisStatus.Completed, 2), (unitAfter.Status, unitAfter.AttemptCount));
            Assert.NotNull(unitAfter.VisibilitySequence);
            Assert.Equal(2, unitAfter.TracksAnalysed);
        }
        finally
        {
            foreach (var worker in new[] { first, second })
            {
                if (worker is null) continue;
                if (!worker.HasExited) worker.Kill(entireProcessTree: true);
                await worker.WaitForExitAsync();
            }

            await watching.CancelAsync();
            await watcher;
            output.WriteLine(stdout.ToString());
            if (Directory.Exists(overlayDirectory)) Directory.Delete(overlayDirectory, recursive: true);
        }

        long finalFacts;
        await using (var db = world.Read())
        {
            Assert.Equal(2, await db.PlateTrackOutcomes.CountAsync());
            finalFacts = await db.PlateTrackOutcomes.CountAsync() + await db.PlateObservations.CountAsync()
                + await db.PlateReadings.CountAsync() + await db.PlateTrackTexts.CountAsync();
            // Exactly one accepted predictions artefact (attempt 2's), sealed and verified.
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.ArtifactType == ArtifactType.PlatePredictions);
            var bytes = await File.ReadAllBytesAsync(world.EvidencePath(artifact.StorageKey));
            Assert.Equal(artifact.Sha256, Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes)));
        }

        // No partial fact was ever visible: facts only with a published unit, and only the full set.
        Assert.Contains(samples, sample => sample.Facts == 0);
        Assert.All(samples, sample => Assert.True(sample.Facts == 0 || (sample.Published == 1 && sample.Facts == finalFacts),
            $"partial or unpublished plate facts were visible: {sample.Facts} rows, {sample.Published} published units"));

        // The run, its Tracks, Observations and the attribute plane are byte-for-byte unchanged.
        Assert.Equal(before, await ReadPlatformFactsAsync());
        Assert.Equal("Ready", (await client.GetFromJsonAsync<JsonElement>($"/api/processing/runs/{run.RunId}/plates")).GetProperty("state").GetString());

        async Task<string> ReadPlatformFactsAsync()
        {
            await using var connection = new Npgsql.NpgsqlConnection(fixture.ConnectionString);
            await connection.OpenAsync();
            var digests = new List<string>();
            foreach (var table in new[] { "processing_runs", "tracks", "observations", "visual_attribute_analyses", "visual_attributes" })
            {
                await using var command = new Npgsql.NpgsqlCommand(
                    $"SELECT count(*) || ':' || coalesce(md5(string_agg(row_to_json(t)::text, '|' ORDER BY t.id)), '') FROM {table} t", connection);
                digests.Add($"{table}={await command.ExecuteScalarAsync()}");
            }

            return string.Join(' ', digests);
        }
    }

    /// <summary>Holds the first plate completion request until its client goes away; never forwards it.</summary>
    private sealed class CompletionGate : Microsoft.AspNetCore.Hosting.IStartupFilter
    {
        private int _taken;

        public TaskCompletionSource Reached { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public TaskCompletionSource Abandoned { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public Action<Microsoft.AspNetCore.Builder.IApplicationBuilder> Configure(Action<Microsoft.AspNetCore.Builder.IApplicationBuilder> next) => app =>
        {
            Microsoft.AspNetCore.Builder.UseExtensions.Use(app, async (context, forward) =>
            {
                var path = context.Request.Path.Value ?? string.Empty;
                if (Microsoft.AspNetCore.Http.HttpMethods.IsPost(context.Request.Method) &&
                    path.StartsWith(Mavi.Contracts.Worker.Plates.PlateContractRules.RoutePrefix, StringComparison.Ordinal) &&
                    path.EndsWith("/complete", StringComparison.Ordinal) &&
                    Interlocked.Exchange(ref _taken, 1) == 0)
                {
                    Reached.TrySetResult();
                    try
                    {
                        await Task.Delay(Timeout.Infinite, context.RequestAborted);
                    }
                    catch (OperationCanceledException)
                    {
                    }

                    Abandoned.TrySetResult();
                    return;
                }

                await forward(context);
            });
            next(app);
        };
    }


    private static async Task<JsonElement> ComposeOverlayAsync(string python, string directory)
    {
        var start = new ProcessStartInfo(python, ["-m", "tests.plate_overlay", directory])
        {
            WorkingDirectory = VisionRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        using var process = Process.Start(start)!;
        var text = await process.StandardOutput.ReadToEndAsync();
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        Assert.True(process.ExitCode == 0, error);
        return JsonDocument.Parse(text).RootElement.Clone();
    }

    private static Process StartWorker(string python, Uri baseAddress, JsonElement overlay, StringBuilder stdout, string workerId)
    {
        var start = new ProcessStartInfo(python, ["-m", "mavi_vision.plates.main"])
        {
            WorkingDirectory = VisionRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.Environment["MAVI_API_BASE_URL"] = baseAddress.ToString().TrimEnd('/');
        start.Environment["MAVI_WORKER_ID"] = workerId;
        start.Environment["MAVI_COMPONENT_BINDING_PATH"] = overlay.GetProperty("componentBindingPath").GetString();
        start.Environment["MAVI_PIPELINE_PROFILE_PATH"] = overlay.GetProperty("pipelineProfilePath").GetString();
        start.Environment["MAVI_OVERLAY_ROOT"] = overlay.GetProperty("overlayRoot").GetString();
        start.Environment["MAVI_MODEL_ROOT"] = overlay.GetProperty("modelRoot").GetString();
        start.Environment["MAVI_POLL_INTERVAL_SECONDS"] = "0.25";
        start.Environment["MAVI_HEARTBEAT_INTERVAL_SECONDS"] = "2";
        var worker = Process.Start(start)!;
        worker.OutputDataReceived += (_, line) => { if (line.Data is not null) lock (stdout) stdout.AppendLine(line.Data); };
        worker.ErrorDataReceived += (_, line) => { if (line.Data is not null) lock (stdout) stdout.AppendLine(line.Data); };
        worker.BeginOutputReadLine();
        worker.BeginErrorReadLine();
        return worker;
    }
}
