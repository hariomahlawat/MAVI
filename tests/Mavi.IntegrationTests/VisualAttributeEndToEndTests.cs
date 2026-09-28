using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Domain.Media;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>A fact that needs the Python worker environment; reported skipped, never passed, without it.</summary>
public sealed class AttributeWorkerFactAttribute : FactAttribute
{
    public const string PythonVariable = "MAVI_S2B_WORKER_PYTHON";

    public AttributeWorkerFactAttribute()
    {
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(PythonVariable)))
            Skip = $"needs the mavi_vision worker environment; set {PythonVariable} to its python";
    }
}

/// <summary>
/// The fixture end to end (S2b plan §14): the real <c>mavi_vision.attributes.main</c> process,
/// composed from a derived Development overlay through the real resolver, against the real
/// platform on a real socket — lease, concurrent heartbeat, authorised evidence reads with
/// byte verification, canonical artefact upload, three-phase completion and publication. No
/// fixture-only endpoint, no database or filesystem access by the worker.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeEndToEndTests(PostgresFixture fixture, ITestOutputHelper output)
{
    private static readonly string VisionRoot = Path.Combine(VisualAttributeReleaseFixture.Root, "src", "vision");

    [AttributeWorkerFact]
    public async Task TheFixtureWorkerPublishesARunThroughTheRealLeasePlane()
    {
        var python = Environment.GetEnvironmentVariable(AttributeWorkerFactAttribute.PythonVariable)!;
        var overlayDirectory = Path.Combine(Path.GetTempPath(), $"mavi-va-e2e-{Guid.NewGuid():N}");
        var overlay = await ComposeOverlayAsync(python, overlayDirectory);

        using var world = await VisualAttributeWorld.CreateAsync(fixture, DateTimeOffset.UtcNow);
        var logs = new VisionFinalizationSubmissionApiTests.CapturingLoggerProvider();
        await using var factory = new ApiTestFactory
        {
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
            VisualAttributeComponentBindingPath = overlay.GetProperty("componentBindingPath").GetString(),
            VisualAttributePipelineProfilePath = overlay.GetProperty("pipelineProfilePath").GetString(),
            OverrideServices = services => services.AddSingleton<Microsoft.Extensions.Logging.ILoggerProvider>(logs),
        };
        factory.UseKestrel(0);
        factory.StartServer();
        using var client = factory.CreateClient();
        var cycle = factory.Services.GetRequiredService<Mavi.Api.VisualAttributes.VisualAttributeHostedService>();
        await cycle.RunCycleAsync(CancellationToken.None);

        // Two person Tracks and one vehicle Track, two accepted crops each; one person Track's
        // crops are both gone from the evidence root (an authoritative evidence_missing).
        await Task.Delay(20);
        var run = await world.SeedRunAsync(2, 1, 2, completedAtUtc: DateTimeOffset.UtcNow);
        foreach (var observation in run.Track(1).Observations)
        {
            File.SetAttributes(world.EvidencePath(observation.StorageKey), FileAttributes.Normal);
            File.Delete(world.EvidencePath(observation.StorageKey));
        }

        Assert.Equal(1, (await cycle.RunCycleAsync(CancellationToken.None)).Queued);

        var worker = StartWorker(python, client.BaseAddress!, overlay);
        var stdout = new StringBuilder();
        worker.OutputDataReceived += (_, line) => { if (line.Data is not null) lock (stdout) stdout.AppendLine(line.Data); };
        worker.ErrorDataReceived += (_, line) => { if (line.Data is not null) lock (stdout) stdout.AppendLine(line.Data); };
        worker.BeginOutputReadLine();
        worker.BeginErrorReadLine();
        VisualAttributeAnalysis? unit = null;
        try
        {
            var deadline = Stopwatch.StartNew();
            while (deadline.Elapsed < TimeSpan.FromSeconds(90))
            {
                await using var db = world.Read();
                unit = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync();
                if (unit.Status is VisualAttributeAnalysisStatus.Completed or VisualAttributeAnalysisStatus.Failed) break;
                if (worker.HasExited) break;
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
        Assert.Equal(VisualAttributeAnalysisStatus.Completed, unit.Status);
        Assert.Equal(1, unit.AttemptCount);
        Assert.Equal(2, unit.TracksAnalysed);
        Assert.Equal(1, unit.TracksUnavailable);

        await using (var db = world.Read())
        {
            var outcomes = await db.VisualAttributeTrackOutcomes.AsNoTracking().Where(x => x.AnalysisId == unit.Id).ToListAsync();
            Assert.Equal("evidence_missing", outcomes.Single(x => x.TrackId == run.Track(1).TrackId).Reason);
            var attributes = await db.VisualAttributes.AsNoTracking().Where(x => x.AnalysisId == unit.Id).ToListAsync();
            // Person: 2 types; vehicle: 1; the Unavailable person: none.
            Assert.Equal(3, attributes.Count);
            var cropIds = run.Tracks.SelectMany(track => track.Observations).Select(item => item.ObservationId).ToHashSet();
            Assert.All(attributes.Where(x => x.Outcome == VisualAttributeOutcome.Observed), x => Assert.Contains(x.SupportingObservationId!.Value, cropIds));
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == unit.PredictionArtifactId);
            Assert.Equal(ArtifactType.AttributePredictions, artifact.ArtifactType);
            var bytes = await File.ReadAllBytesAsync(world.EvidencePath(artifact.StorageKey));
            Assert.Equal(artifact.Sha256, Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes)));
            Assert.Equal((byte)'\n', bytes[^1]);
            using var provenance = JsonDocument.Parse(unit.ProvenanceJson!);
            Assert.Equal("unpacked-environment", provenance.RootElement.GetProperty("runtimePackSource").GetString());
            Assert.Equal(overlay.GetProperty("modelPackId").GetString(),
                provenance.RootElement.GetProperty("capabilities")[0].GetProperty("modelPackId").GetString());
        }

        var readiness = await client.GetFromJsonAsync<JsonElement>($"/api/processing/runs/{run.RunId}/visual-attributes");
        Assert.Equal(nameof(VisualAttributeReadinessState.Ready), readiness.GetProperty("state").GetString());

        // Every read was audited, and the capability reached no log line of either process.
        Assert.Equal(4, logs.Entries.Count(entry => entry.EventId.Id == 2000));
        Assert.Equal(2, logs.Entries.Count(entry => entry.EventId.Id == 2002));
        // A capability is a standalone 43-character Base64Url token; none appears anywhere.
        var tokenPattern = new System.Text.RegularExpressions.Regex("(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])");
        Assert.DoesNotMatch(tokenPattern, stdout.ToString());
        Assert.DoesNotMatch(tokenPattern, string.Join('\n', logs.Entries.Select(entry => entry.Message)));
    }

    private static async Task<JsonElement> ComposeOverlayAsync(string python, string directory)
    {
        var start = new ProcessStartInfo(python, ["-m", "tests.attribute_overlay", directory])
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

    private static Process StartWorker(string python, Uri baseAddress, JsonElement overlay)
    {
        var start = new ProcessStartInfo(python, ["-m", "mavi_vision.attributes.main"])
        {
            WorkingDirectory = VisionRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.Environment["MAVI_API_BASE_URL"] = baseAddress.ToString().TrimEnd('/');
        start.Environment["MAVI_WORKER_ID"] = "attributes-e2e-01";
        start.Environment["MAVI_COMPONENT_BINDING_PATH"] = overlay.GetProperty("componentBindingPath").GetString();
        start.Environment["MAVI_PIPELINE_PROFILE_PATH"] = overlay.GetProperty("pipelineProfilePath").GetString();
        start.Environment["MAVI_OVERLAY_ROOT"] = overlay.GetProperty("overlayRoot").GetString();
        start.Environment["MAVI_MODEL_ROOT"] = overlay.GetProperty("modelRoot").GetString();
        start.Environment["MAVI_POLL_INTERVAL_SECONDS"] = "0.25";
        start.Environment["MAVI_HEARTBEAT_INTERVAL_SECONDS"] = "2";
        return Process.Start(start)!;
    }
}
