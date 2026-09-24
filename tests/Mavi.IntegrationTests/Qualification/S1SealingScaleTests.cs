using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// S1.4 B3 (plan §7.4): the end-to-end completion wall time at the worst-case
/// sealed object count, measured through the <b>real</b> accepted-evidence
/// store on the filesystem that holds <c>MAVI_S1_SEALING_EVIDENCE_ROOT</c>.
/// </summary>
/// <remarks>
/// <para>
/// This is a heavy, opt-in harness. It is skipped, and reported as skipped,
/// unless <c>MAVI_QUALIFICATION=1</c>:
/// </para>
/// <code>
/// MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=... \
/// MAVI_S1_SEALING_EVIDENCE_ROOT=/path/on/qualified/filesystem \
/// dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~S1SealingScaleTests"
/// </code>
/// <para>
/// The worst case is 10,000 trajectories plus four crops per Track. That is
/// 50,000 sealed objects when quota admission admits every crop, which it does
/// at these small object sizes. Count and publication cost dominate sealing, so
/// the objects are small and distinct (plan §7.4). Each sample is one complete
/// POST: validation, sealing and commit, while the job row is held
/// <c>FOR UPDATE</c>. The exact replay a timed-out worker would send is timed
/// separately. The output carries the environment identity, per-sample times,
/// min/p50/p95/max, the p50 spread across repeats, and the row and object counts.
/// The evidence checker (<c>tools/qualification/s1_evidence.py</c>) applies the
/// 2× headroom bound against the worker request timeout. This harness asserts
/// only that each completion succeeded and persisted exactly what it sent.
/// </para>
/// <para>
/// A fake or sparse store cannot stand in for this: it skips the durable
/// publication (<c>DurableFilePublication</c> flush and directory fsync on
/// POSIX, write-through move on Windows), and that is the cost measured here.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class S1SealingScaleTests
{
    private const string EvidenceFile = "s1-b3-sealing-scale.json";
    private static readonly DateTimeOffset Now = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];

    private static int Setting(string name, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(name), NumberStyles.None, CultureInfo.InvariantCulture, out var value) && value > 0
            ? value
            : fallback;

    [Fact]
    public void TheMeasuredEnvelopeIsTheEnforcedEnvelope()
    {
        // Runs in the ordinary suite: the harness measures at the contract's own maxima.
        Assert.Equal(WorkerContractRules.MaximumCompletionTracks, DefaultTracks);
        Assert.Equal(WorkerContractRules.MaximumTrackObservations, Roles.Length);
    }

    private static int DefaultTracks => WorkerContractRules.MaximumCompletionTracks;

    [S1QualificationFact]
    public async Task RealStoreCompletionWallTimeAtTheWorstCaseObjectCount()
    {
        var tracks = Setting("MAVI_S1_SEALING_TRACKS", DefaultTracks);
        var samples = Setting("MAVI_S1_SEALING_SAMPLES", 30);
        var repeats = Setting("MAVI_S1_SEALING_REPEATS", 3);
        var warmup = Setting("MAVI_S1_SEALING_WARMUP", 1);
        // The worker's own setting (WorkerSettings, env prefix MAVI_), not a
        // harness knob: the value the qualified install's worker would use.
        var configuredTimeout = Environment.GetEnvironmentVariable("MAVI_REQUEST_TIMEOUT_SECONDS");
        var timeoutSeconds = string.IsNullOrWhiteSpace(configuredTimeout)
            ? DefaultWorkerRequestTimeoutSeconds
            : double.Parse(configuredTimeout, NumberStyles.Float, CultureInfo.InvariantCulture);
        var evidenceRoot = Environment.GetEnvironmentVariable("MAVI_S1_SEALING_EVIDENCE_ROOT");
        Assert.False(string.IsNullOrWhiteSpace(evidenceRoot), "MAVI_S1_SEALING_EVIDENCE_ROOT must name a directory on the filesystem being qualified.");
        Directory.CreateDirectory(evidenceRoot!);

        var connection = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION") ?? new ApiTestFactory().ConnectionString;
        var environment = await QualificationGate.CaptureEnvironmentAsync(connection);
        var runId = QualificationGate.NewRunId();
        QualificationGate.Begin(EvidenceFile, runId, environment);

        var runs = new List<object>();
        var p50s = new List<double>();
        var all = new List<double>();
        object? shape = null;
        for (var repeat = 0; repeat < repeats; repeat++)
        {
            var completion = new List<double>();
            var replay = new List<double>();
            for (var index = 0; index < warmup + samples; index++)
            {
                var sample = await MeasureOnceAsync(evidenceRoot!, tracks);
                shape ??= sample.Shape;
                if (index < warmup) continue;
                completion.Add(sample.CompletionMs);
                replay.Add(sample.ReplayMs);
            }

            p50s.Add(Percentile(completion, 0.50));
            all.AddRange(completion);
            runs.Add(new { repeat, completionMs = completion, replayMs = replay, completion = Stats(completion), replay = Stats(replay) });
        }

        // Any reduced envelope or unqualified environment still produces output,
        // but never authoritative output; the evidence checker requires it.
        var nonAuthoritative = NonAuthoritativeReasons(tracks, samples, repeats, warmup, configuredTimeout, environment);
        var path = QualificationGate.Write(EvidenceFile, new
        {
            schema = "s1-b3-sealing-scale-v1",
            status = "complete",
            authoritative = nonAuthoritative.Count == 0,
            nonAuthoritativeReasons = nonAuthoritative,
            workerRequestTimeoutSource = configuredTimeout is null ? "WorkerSettings default" : "MAVI_REQUEST_TIMEOUT_SECONDS",
            runId,
            environment,
            evidenceRoot,
            evidenceFilesystem = FilesystemOf(evidenceRoot!),
            shape,
            workerRequestTimeoutMs = timeoutSeconds * 1000.0,
            samples,
            repeats,
            warmupExcluded = warmup,
            completion = Stats(all),
            p50RunSpreadMs = p50s.Max() - p50s.Min(),
            runs,
        });
        Console.WriteLine($"S1 B3 sealing scale evidence: {path}");
    }

    /// <summary>The worker's <c>request_timeout_seconds</c> default (<c>mavi_vision/common/settings.py</c>).</summary>
    internal const double DefaultWorkerRequestTimeoutSeconds = 30.0;

    /// <summary>Why a run cannot be B3 evidence; empty only for the plan's full envelope.</summary>
    internal static List<string> NonAuthoritativeReasons(
        int tracks, int samples, int repeats, int warmup, string? configuredTimeout, IReadOnlyDictionary<string, string> environment)
    {
        var reasons = new List<string>();
        if (tracks != WorkerContractRules.MaximumCompletionTracks)
            reasons.Add($"tracks {tracks} != the {WorkerContractRules.MaximumCompletionTracks} contract maximum");
        if (samples < 30) reasons.Add($"samples {samples} < 30");
        if (repeats < 3) reasons.Add($"repeats {repeats} < 3");
        if (warmup < 1) reasons.Add("no warm-up sample excluded");
        if (configuredTimeout is not null)
            reasons.Add("MAVI_REQUEST_TIMEOUT_SECONDS overrides the worker default; bind the install configuration in the record instead");
        if (!QualificationGate.IsQualificationGrade(environment)) reasons.Add("not a qualification-grade PostgreSQL");
        foreach (var key in new[] { QualificationGate.GitWorkingTreeCleanKey, QualificationGate.GitCommitObjectPresentKey })
        {
            if (!environment.TryGetValue(key, out var value) || value != "true")
                reasons.Add($"{key} is not true");
        }

        return reasons;
    }

    private sealed record Sample(double CompletionMs, double ReplayMs, object Shape);

    private static async Task<Sample> MeasureOnceAsync(string evidenceRoot, int trackCount)
    {
        foreach (var entry in Directory.EnumerateFileSystemEntries(evidenceRoot))
        {
            if (Directory.Exists(entry)) Directory.Delete(entry, recursive: true);
            else File.Delete(entry);
        }

        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now), EvidenceRootOverride = evidenceRoot };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        client.Timeout = Timeout.InfiniteTimeSpan;
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await WorstCountRequestAsync(factory, lease, trackCount);

        var stopwatch = Stopwatch.StartNew();
        using (var completed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request))
        {
            stopwatch.Stop();
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        }

        var completionMs = stopwatch.Elapsed.TotalMilliseconds;
        stopwatch.Restart();
        using (var replayed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request))
        {
            stopwatch.Stop();
            Assert.Equal(HttpStatusCode.OK, replayed.StatusCode);
        }

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var trackRows = await db.Tracks.CountAsync();
        var observationRows = await db.Observations.CountAsync();
        var cropRows = await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.EvidenceCrop);
        var trajectoryRows = await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.TrackTrajectory);
        var acceptedFiles = Directory.GetFiles(evidenceRoot, "*", SearchOption.AllDirectories);
        Assert.Equal(trackCount, trackRows);
        Assert.Equal(trackCount * Roles.Length, observationRows);
        Assert.Equal(trackCount * Roles.Length, cropRows);
        Assert.Equal(trackCount, trajectoryRows);
        Assert.Equal(cropRows + trajectoryRows, acceptedFiles.Length);
        Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);

        return new Sample(completionMs, stopwatch.Elapsed.TotalMilliseconds, new
        {
            tracks = trackRows,
            observations = observationRows,
            sealedObjects = acceptedFiles.Length,
            acceptedEvidenceBytes = acceptedFiles.Sum(x => new FileInfo(x).Length),
            artifactRows = await db.Artifacts.CountAsync(),
        });
    }

    private static async Task<VisionJobCompleteRequest> WorstCountRequestAsync(
        ApiTestFactory factory, VisionJobLeaseContract lease, int trackCount)
    {
        using var scope = factory.Services.CreateScope();
        var store = scope.ServiceProvider.GetRequiredService<IMediaStore>();
        var prefix = $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}";
        var tracks = new List<VisionTrackResultContract>(trackCount);
        long cropBytes = 0;
        for (var index = 1; index <= trackCount; index++)
        {
            var trackId = $"person-{index:D6}";
            var observations = new List<VisionTrackObservationContract>(Roles.Length);
            for (var rank = 0; rank < Roles.Length; rank++)
            {
                var key = $"{prefix}/evidence/{trackId}-{Roles[rank]}.jpg";
                var stored = await store.WriteAsync(key, new MemoryStream(Encoding.UTF8.GetBytes($"jpeg-{trackId}-{Roles[rank]}")), CancellationToken.None);
                cropBytes += stored.SizeBytes;
                observations.Add(new VisionTrackObservationContract(
                    Roles[rank], rank, 250 + rank * 250, rank, .88, .8 - rank * .1, .8 - rank * .1,
                    new VisionBoundingBoxContract(.1, .2, .3, .4),
                    new VisionArtifactDescriptorContract(key, "image/jpeg", stored.SizeBytes, stored.Sha256)));
            }

            var trajectoryKey = $"{prefix}/trajectories/{trackId}.msgpack";
            var trajectory = await store.WriteAsync(
                trajectoryKey, new MemoryStream(Encoding.UTF8.GetBytes($"trajectory-{trackId}")), CancellationToken.None);
            tracks.Add(new VisionTrackResultContract(
                trackId, "person", 0, 1000, 4, .85, .9, null,
                new VisionArtifactDescriptorContract(trajectoryKey, "application/msgpack", trajectory.SizeBytes, trajectory.Sha256),
                observations));
        }

        // Each role's accounting is the sum over its admitted crops; every candidate is admitted.
        var perRole = Roles.ToDictionary(role => role, role => tracks.Sum(t => t.Observations!.Single(o => o.Role == role).Crop!.SizeBytes!.Value));
        VisionEvidenceRoleAccountingContract Accounting(string role) =>
            new(trackCount, trackCount, 0, perRole[role], perRole[role]);
        Assert.Equal(cropBytes, perRole.Values.Sum());

        return new VisionJobCompleteRequest(
            "3.0", lease.JobId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
            4, 1250, VisionResultCompletionApiTests.Provenance(), tracks,
            new VisionEvidenceAccountingContract(
                Accounting("representative"), Accounting("near-view"), Accounting("early-diverse"), Accounting("late-diverse")));
    }

    private static object Stats(List<double> values) => new
    {
        n = values.Count,
        min = values.Min(),
        p50 = Percentile(values, 0.50),
        p95 = Percentile(values, 0.95),
        max = values.Max(),
    };

    /// <summary>Nearest-rank percentile.</summary>
    internal static double Percentile(IEnumerable<double> values, double fraction)
    {
        var ordered = values.Order().ToArray();
        if (ordered.Length == 0) throw new InvalidOperationException("percentile_of_empty_series");
        var rank = (int)Math.Ceiling(fraction * ordered.Length);
        return ordered[Math.Clamp(rank, 1, ordered.Length) - 1];
    }

    private static string FilesystemOf(string path)
    {
        var full = Path.GetFullPath(path);
        var drive = DriveInfo.GetDrives()
            .Where(x => full.StartsWith(x.RootDirectory.FullName, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
            .MaxBy(x => x.RootDirectory.FullName.Length);
        return drive is null ? "unknown" : $"{drive.DriveFormat} at {drive.RootDirectory.FullName}";
    }

    [Fact]
    public void OnlyTheFullEnvelopeInAQualifiedEnvironmentIsAuthoritative()
    {
        var qualified = new Dictionary<string, string>
        {
            [QualificationGate.QualificationGradeKey] = "true",
            [QualificationGate.GitWorkingTreeCleanKey] = "true",
            [QualificationGate.GitCommitObjectPresentKey] = "true",
        };
        Assert.Empty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 30, 3, 1, null, qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(200, 30, 3, 1, null, qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 29, 3, 1, null, qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 30, 2, 1, null, qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 30, 3, 0, null, qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 30, 3, 1, "120", qualified));
        foreach (var key in qualified.Keys)
        {
            var degraded = new Dictionary<string, string>(qualified) { [key] = "false" };
            Assert.NotEmpty(NonAuthoritativeReasons(WorkerContractRules.MaximumCompletionTracks, 30, 3, 1, null, degraded));
        }
    }

    [Theory]
    [InlineData(new[] { 5.0, 1.0, 3.0, 2.0, 4.0 }, 0.50, 3.0)]
    [InlineData(new[] { 5.0, 1.0, 3.0, 2.0, 4.0 }, 0.95, 5.0)]
    [InlineData(new[] { 7.0 }, 0.95, 7.0)]
    public void PercentileIsNearestRank(double[] values, double fraction, double expected) =>
        Assert.Equal(expected, Percentile(values, fraction));
}

/// <summary>
/// A fact that runs only when the heavy qualification pass is asked for.
/// Otherwise it is reported as <b>skipped</b>, never as a pass. A malformed
/// <c>MAVI_QUALIFICATION</c> value throws, exactly as <see cref="QualificationGate.Enabled"/> does.
/// </summary>
public sealed class S1QualificationFactAttribute : FactAttribute
{
    public S1QualificationFactAttribute()
    {
        if (!QualificationGate.Enabled)
            Skip = $"heavy S1.4 qualification harness; set {QualificationGate.EnabledVariable}=1 to run it";
    }
}
