using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// S1.4 B3-A (F4 plan §8): the durable completion 3.1 hand-off at the worst shape, measured
/// through the real HTTP endpoint, validator, payload encoding, PostgreSQL insert and
/// <c>Leased → Finalizing</c> transition, with the hosted finalizer <b>off</b> so nothing can
/// seal or publish during a sample. Replaces the retired synchronous sealing-scale harness.
/// </summary>
/// <remarks>
/// <para>Opt-in and heavy; skipped (and reported skipped) unless <c>MAVI_QUALIFICATION=1</c>:</para>
/// <code>
/// MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=... MAVI_S1_HANDOFF_ROOT=/path/on/qualified/filesystem \
/// dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~S1HandOffScaleTests"
/// </code>
/// <para>
/// Every sample stages 50,000 real, distinct objects (four crops and a trajectory per Track)
/// before the job is leased, so the lease cannot expire during staging, then times one POST.
/// The output retains every raw sample; the evidence checker recomputes the statistics and
/// applies the 15 s bound (<c>tools/qualification/s1_evidence.py</c>). The harness asserts only
/// that each hand-off did what B3-A claims: <c>finalizing</c>, one payload row, no publication.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class S1HandOffScaleTests
{
    private const string EvidenceFile = "s1-b3a-hand-off.json";
    public const string Schema = "s1-b3a-hand-off-v1";

    [Fact]
    public void TheMeasuredEnvelopeIsTheEnforcedEnvelope()
    {
        // Runs in the ordinary suite: the harness measures at the contract's own maxima.
        Assert.Equal(WorkerContractRules.MaximumCompletionTracks, S1QualificationSupport.WorstTracks);
        Assert.Equal(WorkerContractRules.MaximumTrackObservations, S1QualificationSupport.Roles.Length);
        Assert.Equal(50_000, S1QualificationSupport.WorstTracks * S1QualificationSupport.ObjectsPerTrack);
    }

    [Fact]
    public void OnlyTheFullEnvelopeWithTheFinalizerOffInAQualifiedEnvironmentIsAuthoritative()
    {
        var qualified = new Dictionary<string, string>
        {
            [QualificationGate.QualificationGradeKey] = "true",
            [QualificationGate.GitWorkingTreeCleanKey] = "true",
            [QualificationGate.GitCommitObjectPresentKey] = "true",
        };
        var full = S1QualificationSupport.WorstTracks;
        Assert.Empty(NonAuthoritativeReasons(full, 10, 3, 1, null, false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(200, 10, 3, 1, null, false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 9, 3, 1, null, false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 2, 1, null, false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 0, null, false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, "120", false, "ssd", qualified));
        // The hand-off must not be able to wait for the finalizer.
        Assert.Contains(NonAuthoritativeReasons(full, 10, 3, 1, null, true, "ssd", qualified), r => r.Contains("finalizer", StringComparison.Ordinal));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, null, false, "hosted-runner", qualified));
        foreach (var key in qualified.Keys)
        {
            var degraded = new Dictionary<string, string>(qualified) { [key] = "false" };
            Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, null, false, "ssd", degraded));
        }
    }

    [Fact]
    public void AReducedDiagnosticRunIsLabelledNonAuthoritative()
    {
        var reasons = NonAuthoritativeReasons(500, 2, 1, 1, null, false, "virtual", new Dictionary<string, string>());
        Assert.Contains(reasons, r => r.Contains("tracks 500", StringComparison.Ordinal));
        Assert.Contains(reasons, r => r.Contains("samples", StringComparison.Ordinal));
        Assert.Contains(reasons, r => r.Contains("repeats", StringComparison.Ordinal));
    }

    /// <summary>Why a run cannot be B3-A evidence; empty only for the plan's full envelope.</summary>
    internal static List<string> NonAuthoritativeReasons(
        int tracks, int samplesPerRepeat, int repeats, int warmup, string? configuredTimeout, bool finalizerHostEnabled,
        string storageClass, IReadOnlyDictionary<string, string> environment)
    {
        var reasons = new List<string>();
        if (tracks != S1QualificationSupport.WorstTracks)
            reasons.Add($"tracks {tracks} != the {S1QualificationSupport.WorstTracks} contract maximum");
        if (samplesPerRepeat * repeats < 30) reasons.Add($"samples {samplesPerRepeat * repeats} < 30");
        if (repeats < 3) reasons.Add($"repeats {repeats} < 3");
        if (warmup < 1) reasons.Add("no warm-up sample excluded");
        if (configuredTimeout is not null)
            reasons.Add("MAVI_REQUEST_TIMEOUT_SECONDS overrides the worker default; the qualified install uses the WorkerSettings default");
        if (finalizerHostEnabled) reasons.Add("the finalizer host was enabled: the hand-off could have waited for finalization");
        reasons.AddRange(S1QualificationSupport.CommonNonAuthoritativeReasons(environment, storageClass));
        return reasons;
    }

    /// <summary>The worker's <c>request_timeout_seconds</c> default (<c>mavi_vision/common/settings.py</c>).</summary>
    internal const double DefaultWorkerRequestTimeoutSeconds = 30.0;

    [S1QualificationFact]
    public async Task DurableHandOffWallTimeAtTheWorstShape()
    {
        var tracks = S1QualificationSupport.Setting("MAVI_S1_HANDOFF_TRACKS", S1QualificationSupport.WorstTracks);
        var samplesPerRepeat = S1QualificationSupport.Setting("MAVI_S1_HANDOFF_SAMPLES", 10);
        var repeats = S1QualificationSupport.Setting("MAVI_S1_HANDOFF_REPEATS", 3);
        var warmup = S1QualificationSupport.Setting("MAVI_S1_HANDOFF_WARMUP", 1);
        var configuredTimeout = Environment.GetEnvironmentVariable("MAVI_REQUEST_TIMEOUT_SECONDS");
        var timeoutSeconds = configuredTimeout is null ? DefaultWorkerRequestTimeoutSeconds : double.Parse(configuredTimeout, CultureInfo.InvariantCulture);
        var root = Environment.GetEnvironmentVariable("MAVI_S1_HANDOFF_ROOT");
        Assert.False(string.IsNullOrWhiteSpace(root), "MAVI_S1_HANDOFF_ROOT must name a directory on the filesystem being qualified.");
        const bool finalizerHostEnabled = false;

        var connection = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")!;
        var environment = await QualificationGate.CaptureEnvironmentAsync(connection);
        var runId = QualificationGate.NewRunId();
        var fileName = $"s1-b3a-hand-off.{S1QualificationSupport.RuntimeVariant()}.json";
        QualificationGate.Begin(fileName, runId, environment);

        // The harness works only in directories it creates and owns under the root.
        var workRoot = Path.Combine(root!, $"mavi-s1-b3a-{runId}");
        var mediaRoot = Path.Combine(workRoot, "media");
        var evidenceRoot = Path.Combine(workRoot, "evidence");
        Directory.CreateDirectory(mediaRoot);
        Directory.CreateDirectory(evidenceRoot);
        var host = S1QualificationSupport.Host(evidenceRoot);
        try
        {
            var samples = new List<Dictionary<string, object?>>();
            var splits = new List<object>();
            object? shape = null;
            for (var repeat = 0; repeat < repeats; repeat++)
            {
                for (var index = 0; index < warmup + samplesPerRepeat; index++)
                {
                    var sample = await MeasureOnceAsync(mediaRoot, evidenceRoot, tracks, finalizerHostEnabled);
                    shape ??= sample.Shape;
                    sample.Values["repeat"] = repeat;
                    sample.Values["index"] = index;
                    sample.Values["warmup"] = index < warmup;
                    samples.Add(sample.Values);
                }

                // Informational: the store's own validation/encoding/persistence split, once per repeat.
                splits.Add(await SubmissionSplitAsync(mediaRoot, evidenceRoot, tracks));
            }

            var measured = samples.Where(s => !(bool)s["warmup"]!).Select(s => (double)s["handOffMs"]!).ToList();
            var reasons = NonAuthoritativeReasons(tracks, samplesPerRepeat, repeats, warmup, configuredTimeout, finalizerHostEnabled, (string)host["storageClass"]!, environment);
            var path = S1QualificationSupport.WriteOutput(fileName, new
            {
                schema = Schema,
                status = "complete",
                authoritative = reasons.Count == 0,
                nonAuthoritativeReasons = reasons,
                runId,
                variant = S1QualificationSupport.RuntimeVariant(),
                environment,
                host,
                workRoot,
                shape,
                finalizerHostEnabled,
                workerRequestTimeoutMs = timeoutSeconds * 1000.0,
                workerRequestTimeoutSource = configuredTimeout is null ? "WorkerSettings default" : "MAVI_REQUEST_TIMEOUT_SECONDS",
                // Informational only; the checker recomputes every statistic from `samples`.
                summary = S1QualificationSupport.Stats(measured),
                submissionSplits = splits,
                samples,
            });
            Console.WriteLine($"S1 B3-A hand-off evidence: {path}");
        }
        finally
        {
            if (Directory.Exists(workRoot)) Directory.Delete(workRoot, recursive: true);
        }
    }

    private sealed record Sample(Dictionary<string, object?> Values, object Shape);

    private static void Empty(string root)
    {
        foreach (var entry in Directory.EnumerateFileSystemEntries(root))
        {
            if (Directory.Exists(entry)) Directory.Delete(entry, recursive: true);
            else File.Delete(entry);
        }
    }

    private static async Task<Sample> MeasureOnceAsync(string mediaRoot, string evidenceRoot, int trackCount, bool finalizerHostEnabled)
    {
        Empty(mediaRoot);
        Empty(evidenceRoot);
        await S1QualificationSupport.ResetDatabaseAsync(mediaRoot, evidenceRoot);
        using var factory = new ApiTestFactory
        {
            EnableAsynchronousFinalization = true,
            EnableVisionFinalizationHost = finalizerHostEnabled,
            MediaRootOverride = mediaRoot,
            EvidenceRootOverride = evidenceRoot,
        };
        using var client = factory.CreateClient();
        client.Timeout = Timeout.InfiniteTimeSpan;
        var (_, jobId, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var store = factory.Services.GetRequiredService<IMediaStore>();
        var (staged, shape) = await S1QualificationSupport.StageAsync(store, jobId, 1, trackCount);
        Assert.Equal(shape.StagedObjects, S1QualificationSupport.FileCount(Path.Combine(mediaRoot, "staging")));

        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        Assert.Equal(jobId, lease.JobId);
        Assert.Equal(1, lease.AttemptCount);
        var request = S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31);
        var bodyBytes = JsonSerializer.SerializeToUtf8Bytes(request, S1QualificationSupport.Web).LongLength;

        var rssBefore = Process.GetCurrentProcess().WorkingSet64;
        var stopwatch = Stopwatch.StartNew();
        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        stopwatch.Stop();
        var handOffMs = stopwatch.Elapsed.TotalMilliseconds;
        var rssAfter = Process.GetCurrentProcess().WorkingSet64;
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.OK, body);
        var ack = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(body, S1QualificationSupport.Web)!;

        // What B3-A claims, asserted on every sample.
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.AsNoTracking().SingleAsync(x => x.Id == lease.JobId);
        var payloadRows = await db.VisionFinalizationPayloads.CountAsync();
        var payloadBytes = await db.VisionFinalizationPayloads.Select(x => x.PayloadLength).SingleAsync();
        var publishedRows = await S1QualificationSupport.PublishedRowsAsync(factory);
        var acceptedFiles = S1QualificationSupport.FileCount(evidenceRoot);
        Assert.Equal("finalizing", ack.State);
        Assert.Equal(trackCount, ack.TracksSubmitted);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(1, payloadRows);
        Assert.Equal(0, publishedRows);
        Assert.Equal(0, acceptedFiles);
        Assert.NotNull(job.FinalizationAcceptedAtUtc);
        var claimNull = job.FinalizationClaimTokenHash is null && job.FinalizationClaimExpiresAtUtc is null && job.FinalizationClaimExtendedAtUtc is null;
        Assert.True(claimNull);

        stopwatch.Restart();
        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        stopwatch.Stop();
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var replayAck = (await replay.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal(1, await db.VisionFinalizationPayloads.CountAsync());

        return new Sample(new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["handOffMs"] = handOffMs,
            ["replayMs"] = stopwatch.Elapsed.TotalMilliseconds,
            ["httpStatus"] = (int)response.StatusCode,
            ["state"] = ack.State,
            ["tracksSubmitted"] = ack.TracksSubmitted,
            ["jobStatus"] = job.Status.ToString(),
            ["payloadRows"] = payloadRows,
            ["publishedRows"] = publishedRows,
            ["acceptedEvidenceFiles"] = acceptedFiles,
            ["acceptedAtPresent"] = job.FinalizationAcceptedAtUtc is not null,
            ["claimTripleNull"] = claimNull,
            ["stagedObjects"] = shape.StagedObjects,
            ["replayState"] = replayAck.State,
            ["requestBodyBytes"] = bodyBytes,
            ["payloadBytes"] = payloadBytes,
            ["stagedBytes"] = shape.StagedBytes,
            ["apiRssBeforeBytes"] = rssBefore,
            ["apiRssDeltaBytes"] = rssAfter - rssBefore,
        }, new { tracks = shape.Tracks, observations = shape.Observations, stagedObjects = shape.StagedObjects });
    }

    /// <summary>The submission store's own timing split, through the real store (informational).</summary>
    private static async Task<object> SubmissionSplitAsync(string mediaRoot, string evidenceRoot, int trackCount)
    {
        Empty(mediaRoot);
        Empty(evidenceRoot);
        await S1QualificationSupport.ResetDatabaseAsync(mediaRoot, evidenceRoot);
        using var factory = new ApiTestFactory { EnableAsynchronousFinalization = true, MediaRootOverride = mediaRoot, EvidenceRootOverride = evidenceRoot };
        using var client = factory.CreateClient();
        var (_, jobId, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var (staged, _) = await S1QualificationSupport.StageAsync(factory.Services.GetRequiredService<IMediaStore>(), jobId, 1, trackCount);
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31);
        using var scope = factory.Services.CreateScope();
        var result = await scope.ServiceProvider.GetRequiredService<IVisionFinalizationSubmissionStore>()
            .SubmitAsync(lease.JobId, lease.WorkerId, lease.LeaseToken, request, CancellationToken.None);
        Assert.True(result.IsSuccess, result.ErrorCode);
        var timings = result.Timings!;
        return new
        {
            validationMs = timings.Validation.TotalMilliseconds,
            payloadEncodingMs = timings.PayloadEncoding.TotalMilliseconds,
            persistenceMs = timings.Persistence.TotalMilliseconds,
            totalMs = timings.Total.TotalMilliseconds,
        };
    }
}
