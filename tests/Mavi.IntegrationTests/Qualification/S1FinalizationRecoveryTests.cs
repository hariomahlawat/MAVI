using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The executable (H) rows of the crash and recovery matrix (F4 plan §11): real process loss of
/// a real worker and of real API hosts, not injected clocks. Every other row of the matrix is an
/// existing discriminating integration test the evidence checker names (its B3 proving map).
/// </summary>
/// <remarks>
/// <para>Opt-in and heavy; skipped unless <c>MAVI_QUALIFICATION=1</c>:</para>
/// <code>
/// MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=... MAVI_S1_RECOVERY_ROOT=/path/on/qualified/filesystem \
/// MAVI_S1_WORKER_PYTHON=/path/to/worker/venv/python \
/// dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~S1FinalizationRecoveryTests"
/// </code>
/// <para>
/// Each row starts from a fresh schema and empty roots, kills at a declared point, restarts
/// where the scenario needs it, and records the kill point, restart latency, created/adopted
/// objects (from event 1504 of the surviving host), final state, publications (the run's Track
/// rows, with event 1504 as a cross-check), visibility sequence and its stability, live claims
/// and orphan bytes (accepted files no Artifact row references). A row passes only if
/// the job converges to exactly one publication and one sequence with every object accounted.
/// </para>
/// <para>
/// The worker row uses the real <c>mavi_vision</c> worker process
/// (<c>tools/vision/dev/fixture_worker_harness.py</c>: the real <c>WorkerRunner</c> and client,
/// completion 3.1, fixture detector and tracker), so its shape is that harness's small one,
/// recorded in the row; the envelope-size worker independence is B3-B's (it never runs a worker).
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class S1FinalizationRecoveryTests
{
    public const string Schema = "s1-b3-crash-matrix-v1";
    public static readonly string[] Scenarios = ["worker-death-after-hand-off", "host-death-before-first-claim", "host-death-mid-seal", "two-hosts-racing"];
    private static readonly Regex Created = new(@"(\d+) created", RegexOptions.CultureInvariant);
    private static readonly Regex Adopted = new(@"(\d+) adopted", RegexOptions.CultureInvariant);

    [Fact]
    public void TheHarnessCoversExactlyThePlansProcessKillRows() =>
        Assert.Equal(["worker-death-after-hand-off", "host-death-before-first-claim", "host-death-mid-seal", "two-hosts-racing"], Scenarios);

    [Fact]
    public void ARowPassesOnlyWhenItConvergesToOnePublication()
    {
        var good = new RowFacts("Completed", 1, 1, 50_000, 30_000, 20_000, 0, true, 10_000, 10_000, true, 1);
        Assert.Empty(RowProblems("host-death-mid-seal", good));
        Assert.NotEmpty(RowProblems("two-hosts-racing", good with { GraphTrackRows = 20_000 }));  // published twice, a log line lost
        Assert.NotEmpty(RowProblems("two-hosts-racing", good with { SequenceStable = false }));
        Assert.NotEmpty(RowProblems("two-hosts-racing", good with { MaxLiveClaims = 2 }));
        Assert.NotEmpty(RowProblems("host-death-mid-seal", good with { Adopted = 0, Created = 50_000 }));  // recreated, never adopted
        Assert.NotEmpty(RowProblems("two-hosts-racing", good with { Publications = 2 }));
        Assert.NotEmpty(RowProblems("two-hosts-racing", good with { Sequences = 2 }));
        Assert.NotEmpty(RowProblems("host-death-before-first-claim", good with { FinalState = "Failed" }));
        Assert.NotEmpty(RowProblems("host-death-before-first-claim", good with { Created = 10, Adopted = 0 }));
        Assert.NotEmpty(RowProblems("host-death-before-first-claim", good with { KillPointHeld = false }));
    }

    [Fact]
    public void WindowsRecoveryRequiresExplicitWorkerPython()
    {
        var exception = Assert.Throws<InvalidOperationException>(() => ResolveWorkerPython(null, isWindows: true));
        Assert.Contains("MAVI_S1_WORKER_PYTHON", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ExplicitWorkerPythonIsUsedWithoutPathFallback()
    {
        Assert.Equal(@"C:\qualified\venv\Scripts\python.exe", ResolveWorkerPython(@"C:\qualified\venv\Scripts\python.exe", isWindows: true));
        Assert.Equal("/qualified/venv/bin/python", ResolveWorkerPython("/qualified/venv/bin/python", isWindows: false));
        Assert.Equal("python3", ResolveWorkerPython(null, isWindows: false));
    }

    internal sealed record RowFacts(
        string FinalState, int Publications, long Sequences, int Expected, int Created, int Adopted, long OrphanBytes, bool KillPointHeld,
        int ExpectedTracks, long GraphTrackRows, bool SequenceStable, long MaxLiveClaims);

    internal static List<string> RowProblems(string scenario, RowFacts facts)
    {
        var problems = new List<string>();
        if (facts.FinalState != "Completed") problems.Add($"ended {facts.FinalState}");
        if (facts.Publications != 1) problems.Add($"{facts.Publications} publications");
        if (facts.Sequences != 1) problems.Add($"{facts.Sequences} visibility sequences");
        // The database, not a console line, says how many graphs were published.
        if (facts.ExpectedTracks <= 0 || facts.GraphTrackRows != facts.ExpectedTracks) problems.Add($"{facts.GraphTrackRows} Track rows for {facts.ExpectedTracks} Tracks");
        if (!facts.SequenceStable) problems.Add("the run's visibility sequence changed after publication");
        if (facts.MaxLiveClaims > 1) problems.Add($"{facts.MaxLiveClaims} live claims observed");
        if (facts.Created + facts.Adopted != facts.Expected) problems.Add($"created {facts.Created} + adopted {facts.Adopted} != {facts.Expected}");
        if (scenario == "host-death-mid-seal" && facts.Adopted == 0) problems.Add("nothing adopted after a mid-seal kill");
        if (!facts.KillPointHeld) problems.Add("the declared kill point did not hold");
        return problems;
    }

    [S1QualificationFact]
    public async Task ProcessLossConvergesToExactlyOnePublication()
    {
        var tracks = S1QualificationSupport.Setting("MAVI_S1_RECOVERY_TRACKS", S1QualificationSupport.WorstTracks);
        var root = Environment.GetEnvironmentVariable("MAVI_S1_RECOVERY_ROOT");
        Assert.False(string.IsNullOrWhiteSpace(root), "MAVI_S1_RECOVERY_ROOT must name a directory on the filesystem being qualified.");
        var connection = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")!;
        var environment = await QualificationGate.CaptureEnvironmentAsync(connection);
        var runId = QualificationGate.NewRunId();
        var fileName = $"s1-b3-crash-matrix.{S1QualificationSupport.RuntimeVariant()}.json";
        QualificationGate.Begin(fileName, runId, environment);
        var workRoot = Path.Combine(root!, $"mavi-s1-crash-{runId}");
        Directory.CreateDirectory(workRoot);
        var host = S1QualificationSupport.Host(workRoot);
        try
        {
            // MAVI_S1_RECOVERY_SCENARIOS narrows a diagnostic run; a narrowed run is never evidence.
            var only = (Environment.GetEnvironmentVariable("MAVI_S1_RECOVERY_SCENARIOS") ?? string.Join(',', Scenarios))
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToHashSet(StringComparer.Ordinal);
            var rows = new List<object>();
            if (only.Contains(Scenarios[0])) rows.Add(await WorkerDeathAsync(connection, workRoot));
            if (only.Contains(Scenarios[1])) rows.Add(await HostDeathBeforeFirstClaimAsync(connection, workRoot, tracks));
            if (only.Contains(Scenarios[2])) rows.Add(await HostDeathMidSealAsync(connection, workRoot, tracks));
            if (only.Contains(Scenarios[3])) rows.Add(await TwoHostsRacingAsync(connection, workRoot, tracks));
            var reasons = S1QualificationSupport.CommonNonAuthoritativeReasons(environment, (string)host["storageClass"]!);
            if (!Scenarios.All(only.Contains)) reasons.Add($"only {string.Join(',', only)} of the H scenarios ran");
            if (tracks != S1QualificationSupport.WorstTracks) reasons.Add($"tracks {tracks} != the {S1QualificationSupport.WorstTracks} contract maximum");
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
                rows,
            });
            Console.WriteLine($"S1 B3 crash-matrix evidence: {path}");
            // The output records a failed row for the checker; the run is red for the operator too.
            var failed = rows.Select(row => JsonSerializer.SerializeToElement(row)).Where(row => !row.GetProperty("passed").GetBoolean())
                .Select(row => row.GetProperty("scenario").GetString()).ToList();
            Assert.True(failed.Count == 0, $"crash rows failed: {string.Join(", ", failed)}");
        }
        finally
        {
            QualificationWorkRoot.Delete(workRoot);
        }
    }

    // -- scenarios ------------------------------------------------------------------------------

    private sealed record Roots(string Media, string Evidence);

    private static async Task<Roots> FreshAsync(string workRoot, string scenario)
    {
        var roots = new Roots(Path.Combine(workRoot, scenario, "media"), Path.Combine(workRoot, scenario, "evidence"));
        Directory.CreateDirectory(roots.Media);
        Directory.CreateDirectory(roots.Evidence);
        await S1QualificationSupport.ResetDatabaseAsync(roots.Media, roots.Evidence);
        return roots;
    }

    /// <summary>Queues a seeded video, stages the worst shape and hands it off through <paramref name="api"/>.</summary>
    private static async Task<(Guid JobId, int Expected, int Tracks)> HandOffAsync(Roots roots, HttpClient api, int tracks)
    {
        using var factory = new ApiTestFactory { MediaRootOverride = roots.Media, EvidenceRootOverride = roots.Evidence };
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        (await api.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var jobId = await ScalarAsync<Guid>(factory.ConnectionString,
            "SELECT j.id FROM vision_jobs j JOIN processing_runs r ON r.id = j.processing_run_id WHERE r.video_asset_id = $1", videoId);
        var (staged, shape) = await S1QualificationSupport.StageAsync(factory.Services.GetRequiredService<IMediaStore>(), jobId, 1, tracks);
        var lease = await VisionResultCompletionApiTests.LeaseAsync(api, "gpu-sdd-01");
        Assert.Equal(jobId, lease.JobId);
        using var response = await api.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return (jobId, shape.StagedObjects, shape.Tracks);
    }

    private static async Task<object> HostDeathBeforeFirstClaimAsync(string connection, string workRoot, int tracks)
    {
        const string scenario = "host-death-before-first-claim";
        var roots = await FreshAsync(workRoot, scenario);
        // Host A takes the hand-off and dies before any cycle can claim it. Its poll interval
        // is lengthened (recorded) so the kill always precedes its next cycle; host B, the
        // survivor, runs the committed configuration.
        var aOverrides = new Dictionary<string, string> { ["VisionFinalization__PollIntervalSeconds"] = "300" };
        await using var a = ChildApiHost.Start("A", connection, roots.Media, roots.Evidence, aOverrides);
        await a.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        using var api = a.Client();
        var (jobId, expected, expectedTracks) = await HandOffAsync(roots, api, tracks);
        var killedAt = a.Kill();
        var attemptsAtKill = await ScalarAsync<int>(connection, "SELECT finalization_attempt_count FROM vision_jobs WHERE id = $1", jobId);

        await using var b = ChildApiHost.Start("B", connection, roots.Media, roots.Evidence);
        var restart = await b.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        return await ConvergeAsync(scenario, connection, roots, jobId, expected, expectedTracks, [a, b], restart,
            new { phase = "after hand-off acknowledgement, before any claim", finalizationAttemptsAtKill = attemptsAtKill, killedAtUtc = killedAt, hostAOverrides = aOverrides },
            attemptsAtKill == 0);
    }

    private static async Task<object> HostDeathMidSealAsync(string connection, string workRoot, int tracks)
    {
        const string scenario = "host-death-mid-seal";
        var roots = await FreshAsync(workRoot, scenario);
        await using var a = ChildApiHost.Start("A", connection, roots.Media, roots.Evidence);
        await a.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        using var api = a.Client();
        var (jobId, expected, expectedTracks) = await HandOffAsync(roots, api, tracks);
        // Kill when about 40 % of the objects are sealed (observed from the accepted root).
        var target = expected * 2 / 5;
        var deadline = DateTime.UtcNow + TimeSpan.FromMinutes(30);
        while (S1QualificationSupport.FileCount(roots.Evidence) < target)
        {
            Assert.True(DateTime.UtcNow < deadline, "sealing did not reach the kill point");
            await Task.Delay(20);
        }

        var killedAt = a.Kill();
        var sealedAtKill = S1QualificationSupport.FileCount(roots.Evidence);
        await using var b = ChildApiHost.Start("B", connection, roots.Media, roots.Evidence);
        var restart = await b.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        return await ConvergeAsync(scenario, connection, roots, jobId, expected, expectedTracks, [a, b], restart,
            new { afterSealedObjects = sealedAtKill, targetSealedObjects = target, killedAtUtc = killedAt },
            sealedAtKill > 0 && sealedAtKill < expected);
    }

    private static async Task<object> TwoHostsRacingAsync(string connection, string workRoot, int tracks)
    {
        const string scenario = "two-hosts-racing";
        var roots = await FreshAsync(workRoot, scenario);
        await using var a = ChildApiHost.Start("A", connection, roots.Media, roots.Evidence);
        await using var b = ChildApiHost.Start("B", connection, roots.Media, roots.Evidence);
        await a.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        var restart = await b.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        using var api = a.Client();
        var (jobId, expected, expectedTracks) = await HandOffAsync(roots, api, tracks);
        return await ConvergeAsync(scenario, connection, roots, jobId, expected, expectedTracks, [a, b], restart,
            new { phase = "no kill: two live hosts poll one Finalizing job" }, killPointHeld: true);
    }

    private static async Task<object> WorkerDeathAsync(string connection, string workRoot)
    {
        const string scenario = "worker-death-after-hand-off";
        var roots = await FreshAsync(workRoot, scenario);
        await using var a = ChildApiHost.Start("A", connection, roots.Media, roots.Evidence);
        var restart = await a.WaitHealthyAsync(TimeSpan.FromMinutes(2));
        var videoId = await SeedRealVideoAsync(roots, connection);
        using var api = a.Client();
        (await api.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var jobId = await ScalarAsync<Guid>(connection,
            "SELECT j.id FROM vision_jobs j JOIN processing_runs r ON r.id = j.processing_run_id WHERE r.video_asset_id = $1", videoId);

        var python = ResolveWorkerPython(Environment.GetEnvironmentVariable("MAVI_S1_WORKER_PYTHON"), OperatingSystem.IsWindows());
        var repository = RepositoryRoot();
        var start = new ProcessStartInfo(python, [Path.Combine(repository, "tools", "vision", "dev", "fixture_worker_harness.py")])
        {
            WorkingDirectory = repository,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.Environment["MAVI_API_BASE_URL"] = a.BaseAddress.ToString().TrimEnd('/');
        start.Environment["MAVI_WORKER_ID"] = "qualification-worker-01";
        start.Environment["MAVI_MEDIA_ROOT"] = roots.Media;
        start.Environment["MAVI_COMPLETION_SCHEMA_VERSION"] = WorkerContractRules.CompletionSchemaVersionV31;
        // run_once() normally exits immediately after the hand-off acknowledgement. Hold the
        // fixture process so this H-row controls the declared kill point instead of racing exit.
        start.Environment["MAVI_FIXTURE_STAY_ALIVE_AFTER_HANDOFF_SECONDS"] = "300";
        var workerOutput = new List<string>();
        var workerError = new List<string>();
        using var worker = Process.Start(start)!;
        worker.OutputDataReceived += (_, args) => { if (args.Data is not null) lock (workerOutput) workerOutput.Add(args.Data); };
        worker.ErrorDataReceived += (_, args) => { if (args.Data is not null) lock (workerError) workerError.Add(args.Data); };
        string status;
        bool exitedBeforeKill;
        try
        {
            worker.BeginOutputReadLine();
            worker.BeginErrorReadLine();

            // Kill the worker the moment the platform holds the hand-off.
            var deadline = DateTime.UtcNow + TimeSpan.FromMinutes(10);
            while ((status = await ScalarAsync<string>(connection, "SELECT status FROM vision_jobs WHERE id = $1", jobId)) is not ("Finalizing" or "Completed" or "Failed"))
            {
                Assert.False(worker.HasExited && status is "Queued",
                    $"the worker exited ({(worker.HasExited ? worker.ExitCode : 0)}) before leasing. stdout: {string.Join(" | ", workerOutput)} stderr: {string.Join(" | ", workerError)}");
                Assert.True(DateTime.UtcNow < deadline, "the worker never handed off");
                await Task.Delay(10);
            }

            exitedBeforeKill = worker.HasExited;
        }
        finally
        {
            // Never leave the worker running, whatever the harness saw.
            if (!worker.HasExited) worker.Kill(entireProcessTree: true);
            worker.WaitForExit();
        }

        var (expected, expectedTracks) = await PayloadObjectsAsync(connection, jobId);
        // The row is a death only if this harness killed a live worker after the hand-off.
        return await ConvergeAsync(scenario, connection, roots, jobId, expected, expectedTracks, [a], restart,
            new { phase = "platform status Finalizing observed", statusAtKill = status, workerExitedBeforeKill = exitedBeforeKill, shape = "fixture_worker_harness natural shape" },
            killPointHeld: status == "Finalizing" && !exitedBeforeKill);
    }

    // -- convergence ----------------------------------------------------------------------------

    private static async Task<object> ConvergeAsync(
        string scenario, string connection, Roots roots, Guid jobId, int expected, int expectedTracks, IReadOnlyList<ChildApiHost> hosts, TimeSpan restart, object killPoint, bool killPointHeld)
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromHours(2);
        var liveClaims = new List<long>();
        string status;
        while (true)
        {
            liveClaims.Add(await ScalarAsync<long>(connection, S1FinalizationEnvelopeTests.LiveClaimsSql));
            status = await ScalarAsync<string>(connection, "SELECT status FROM vision_jobs WHERE id = $1", jobId);
            if (status is "Completed" or "Failed") break;
            Assert.True(DateTime.UtcNow < deadline, $"{scenario}: the job did not reach a terminal state");
            await Task.Delay(100);
        }

        // The run's sequence must not move once published: the live hosts keep polling through
        // this hold, so a republish would rewrite it.
        var sequenceAtPublication = await RunSequenceAsync(connection, jobId);
        await Task.Delay(TimeSpan.FromSeconds(10));
        var sequenceStable = sequenceAtPublication is not null && await RunSequenceAsync(connection, jobId) == sequenceAtPublication;
        var graphTrackRows = await ScalarAsync<long>(connection, "SELECT count(*) FROM tracks t JOIN vision_jobs j ON j.processing_run_id = t.processing_run_id WHERE j.id = $1", jobId);
        var published = hosts.SelectMany(h => h.Output).Where(line => line.Contains("[1504]", StringComparison.Ordinal) || line.Contains($"job {jobId} published", StringComparison.Ordinal)).ToList();
        var publications = hosts.SelectMany(h => h.Output).Count(line => line.Contains($"Finalization of job {jobId} published", StringComparison.Ordinal));
        var message = hosts.SelectMany(h => h.Output).LastOrDefault(line => line.Contains($"Finalization of job {jobId} published", StringComparison.Ordinal)) ?? "";
        var created = Created.Match(message) is { Success: true } c ? int.Parse(c.Groups[1].Value, CultureInfo.InvariantCulture) : 0;
        var adopted = Adopted.Match(message) is { Success: true } d ? int.Parse(d.Groups[1].Value, CultureInfo.InvariantCulture) : 0;
        // The visibility sequence assigned to this job's run (never the global counter, which
        // search and analytics snapshots advance too).
        var sequences = await ScalarAsync<long>(connection, "SELECT count(*) FROM processing_runs r JOIN vision_jobs j ON j.processing_run_id = r.id WHERE j.id = $1 AND r.visibility_sequence IS NOT NULL", jobId);
        var orphanBytes = await OrphanBytesAsync(connection, roots.Evidence);
        var facts = new RowFacts(status, publications, sequences, expected, created, adopted, orphanBytes, killPointHeld,
            expectedTracks, graphTrackRows, sequenceStable, liveClaims.Max());
        var problems = RowProblems(scenario, facts);
        return new
        {
            scenario,
            passed = problems.Count == 0,
            problems,
            finalState = status,
            publications,
            sequenceCount = sequences,
            expectedTracks,
            graphTrackRows,
            sequenceStable,
            visibilitySequence = sequenceAtPublication,
            liveClaimSamples = liveClaims,
            maxLiveClaims = liveClaims.Max(),
            expectedObjects = expected,
            createdObjects = created,
            adoptedObjects = adopted,
            killPoint,
            restartLatencyMs = restart.TotalMilliseconds,
            orphanBytes,
            // Cross-check only: publications are counted from the database above.
            event1504CrossCheck = published,
        };
    }

    /// <summary>Bytes of accepted files that no Artifact row references (ADR-006 §5 orphans).</summary>
    private static async Task<long> OrphanBytesAsync(string connection, string evidenceRoot)
    {
        var referenced = new HashSet<string>(StringComparer.Ordinal);
        await using (var db = new NpgsqlConnection(connection))
        {
            await db.OpenAsync();
            await using var command = new NpgsqlCommand("SELECT storage_key FROM artifacts", db);
            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync()) referenced.Add(reader.GetString(0).Replace('\\', '/'));
        }

        long bytes = 0;
        foreach (var file in Directory.EnumerateFiles(evidenceRoot, "*", SearchOption.AllDirectories))
        {
            var key = Path.GetRelativePath(evidenceRoot, file).Replace('\\', '/');
            if (!referenced.Contains(key) && !referenced.Contains("evidence/" + key)) bytes += new FileInfo(file).Length;
        }

        return bytes;
    }

    /// <summary>The objects the retained hand-off names: one trajectory per Track plus each crop.</summary>
    private static async Task<(int Objects, int Tracks)> PayloadObjectsAsync(string connection, Guid jobId)
    {
        await using var db = new NpgsqlConnection(connection);
        await db.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT payload FROM vision_finalization_payloads WHERE job_id = $1", db);
        command.Parameters.AddWithValue(jobId);
        var payload = (byte[])(await command.ExecuteScalarAsync())!;
        using var document = JsonDocument.Parse(payload);
        var count = 0;
        var tracks = 0;
        foreach (var track in document.RootElement.GetProperty("tracks").EnumerateArray())
        {
            tracks++;
            if (track.TryGetProperty("trajectoryArtifact", out var trajectory) && trajectory.ValueKind == JsonValueKind.Object) count++;
            if (track.TryGetProperty("observations", out var observations))
                count += observations.EnumerateArray().Count(o => o.TryGetProperty("crop", out var crop) && crop.ValueKind == JsonValueKind.Object);
        }

        return (count, tracks);
    }

    private static async Task<long?> RunSequenceAsync(string connection, Guid jobId)
    {
        await using var db = new NpgsqlConnection(connection);
        await db.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT r.visibility_sequence FROM processing_runs r JOIN vision_jobs j ON j.processing_run_id = r.id WHERE j.id = $1", db);
        command.Parameters.AddWithValue(jobId);
        return await command.ExecuteScalarAsync() is long value ? value : null;
    }

    private static async Task<Guid> SeedRealVideoAsync(Roots roots, string connection)
    {
        // A 12 s, 25 fps, 640x360 test pattern: the fixture harness's detections span frames 50-250.
        var sourceId = Guid.CreateVersion7();
        var relative = $"source/{sourceId}.mp4";
        var path = Path.Combine(roots.Media, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var ffmpegPath = QualificationMediaTools.ResolveBundledFfmpeg(RepositoryRoot());
        var ffmpegStart = new ProcessStartInfo(ffmpegPath)
        {
            UseShellExecute = false,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        foreach (var argument in new[] { "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", path })
            ffmpegStart.ArgumentList.Add(argument);
        using (var ffmpeg = Process.Start(ffmpegStart)!)
        {
            var error = ffmpeg.StandardError.ReadToEndAsync();
            await ffmpeg.WaitForExitAsync();
            var errorText = await error;
            Assert.True(ffmpeg.ExitCode == 0, $"FFmpeg seed generation failed with exit {ffmpeg.ExitCode}: {errorText}");
        }

        var bytes = await File.ReadAllBytesAsync(path);
        using var factory = new ApiTestFactory { MediaRootOverride = roots.Media, EvidenceRootOverride = roots.Evidence };
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var now = DateTimeOffset.UtcNow;
        var camera = Camera.Create("CAM-CRASH", "Crash matrix", "UTC", now);
        var source = Artifact.Create(ArtifactType.SourceVideo, relative, "video/mp4", bytes.LongLength, Convert.ToHexStringLower(SHA256.HashData(bytes)), createdAtUtc: now);
        var video = VideoAsset.Create(camera.Id, source.Id, "crash-matrix.mp4", now, 12_000, 25, 1, 640, 360, "h264", TimestampSource.Manual, 1, importedAtUtc: now);
        db.AddRange(camera, source, video);
        await db.SaveChangesAsync();
        return video.Id;
    }

    internal static string ResolveWorkerPython(string? configured, bool isWindows)
    {
        if (!string.IsNullOrWhiteSpace(configured))
            return configured;
        if (isWindows)
            throw new InvalidOperationException("MAVI_S1_WORKER_PYTHON must be set explicitly on Windows qualification hosts.");
        return "python3";
    }

    private static string RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !Directory.Exists(Path.Combine(directory.FullName, ".git"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("the repository root is not an ancestor of the test assembly");
    }

    private static async Task<T> ScalarAsync<T>(string connection, string sql, params object[] parameters)
    {
        await using var db = new NpgsqlConnection(connection);
        await db.OpenAsync();
        await using var command = new NpgsqlCommand(sql, db);
        foreach (var parameter in parameters) command.Parameters.AddWithValue(parameter);
        var value = await command.ExecuteScalarAsync();
        return value is T typed ? typed : (T)Convert.ChangeType(value!, typeof(T), CultureInfo.InvariantCulture);
    }
}
