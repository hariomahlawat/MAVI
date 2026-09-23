using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>Staging janitor with database authority: J1–J14 of the S1.2 plan (§6.5, test matrix).</summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class StagingJanitorTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 23, 12, 0, 0, TimeSpan.Zero);

    // J1
    [Theory]
    [InlineData(VisionJobStatus.Completed)]
    [InlineData(VisionJobStatus.Failed)]
    [InlineData(VisionJobStatus.Cancelled)]
    public async Task TerminalJobAttemptIsRemovedAfterGraceNotBefore(VisionJobStatus status)
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(status, attemptCount: 2, completedAtUtc: Now.AddMinutes(-1));
        world.Stage(job, "attempt-0001");
        world.Stage(job, "attempt-0002");

        var early = await world.RunCycleAsync();
        Assert.Equal(0, early.Eligible);
        Assert.True(world.JobExists(job));

        world.Clock.Advance(TimeSpan.FromMinutes(4));
        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.Equal(20, cycle.FreedBytes);
        Assert.False(world.JobExists(job));
        Assert.Equal(status == VisionJobStatus.Cancelled ? 1 : 0, world.Logs.Count(1405));
    }

    // J2
    [Fact]
    public async Task SimulatedWorkerDeathAfterCompletionIsReclaimedAndAcceptedEvidenceStaysServable()
    {
        using var world = await JanitorWorld.CreateAsync();
        using var client = world.Factory.CreateClient();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(world.Factory);
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await VisionResultCompletionApiTests.BuildRequestAsync(world.Factory, lease);
        using (var completed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);

        // The worker died before its fast-path cleanup: staging is still there.
        Assert.True(world.JobExists(lease.JobId));
        Assert.Equal(0, (await world.RunCycleAsync()).Removed);

        world.Clock.Advance(TimeSpan.FromMinutes(6));
        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.JobExists(lease.JobId));
        using var scope = world.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        foreach (var artifact in await db.Artifacts.Where(x => x.ArtifactType != ArtifactType.SourceVideo).ToListAsync())
        {
            using var content = await client.GetAsync($"/api/artifacts/{artifact.Id:D}/content");
            Assert.Equal(HttpStatusCode.OK, content.StatusCode);
            Assert.Equal(artifact.SizeBytes, (await content.Content.ReadAsByteArrayAsync()).LongLength);
        }
    }

    // J3
    [Fact]
    public async Task LeasedJobCurrentAndLaterAttemptsAreNeverRemovedLowerAttemptsAreRemovedImmediately()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Leased, attemptCount: 3, completedAtUtc: null);
        foreach (var attempt in new[] { "attempt-0001", "attempt-0002", "attempt-0003", "attempt-0004" })
            world.Stage(job, attempt);

        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.AttemptExists(job, "attempt-0001"));
        Assert.False(world.AttemptExists(job, "attempt-0002"));
        Assert.True(world.AttemptExists(job, "attempt-0003"));
        Assert.True(world.AttemptExists(job, "attempt-0004"));

        // Nothing is left that the lease does not fence.
        Assert.Equal(0, (await world.RunCycleAsync()).Eligible);
    }

    // J4
    [Fact]
    public async Task QueuedZeroAttemptJobWithStagingIsPreservedAndLogged()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Queued, attemptCount: 0, completedAtUtc: null);
        world.Stage(job, "attempt-0001");

        world.Clock.Advance(TimeSpan.FromDays(3));
        var cycle = await world.RunCycleAsync();
        await world.RunCycleAsync();

        Assert.Equal(0, cycle.Eligible);
        Assert.True(world.AttemptExists(job, "attempt-0001"));
        Assert.Equal(1, world.Logs.Count(1401));
    }

    // J4
    [Fact]
    public async Task QueuedPositiveAttemptCountIsAnInvariantViolationPreservedAndLogged()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Queued, attemptCount: 2, completedAtUtc: null);
        world.Stage(job, "attempt-0001");
        world.Stage(job, "attempt-0002");

        world.Clock.Advance(TimeSpan.FromDays(3));
        var cycle = await world.RunCycleAsync();

        Assert.Equal(0, cycle.Eligible);
        Assert.True(world.AttemptExists(job, "attempt-0001"));
        Assert.True(world.AttemptExists(job, "attempt-0002"));
        var violation = Assert.Single(world.Logs.Entries(1406));
        Assert.Equal(LogLevel.Error, violation.Level);
    }

    // J5
    [Fact]
    public async Task OtherJobDirectoriesAreUntouchedWhenOneIsReclaimed()
    {
        using var world = await JanitorWorld.CreateAsync();
        var done = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
        var running = await world.SeedJobAsync(VisionJobStatus.Leased, 1, null);
        var recent = await world.SeedJobAsync(VisionJobStatus.Failed, 1, Now.AddMinutes(-2));
        foreach (var job in new[] { done, running, recent })
            world.Stage(job, "attempt-0001");

        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.JobExists(done));
        Assert.True(world.AttemptExists(running, "attempt-0001"));
        Assert.True(world.AttemptExists(recent, "attempt-0001"));
    }

    // J5
    [Fact]
    public async Task NonCanonicalNamesAreUntouchedAndLoggedOnce()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
        world.Stage(job, "attempt-0001");
        foreach (var name in new[] { "attempt-1", "attempt-00001", "attempt-0000", "Attempt-0001", "scratch" })
            world.Stage(job, name);
        var upper = world.StagingPath(job.ToString("D").ToUpperInvariant());
        Directory.CreateDirectory(Path.Combine(upper, "attempt-0001"));
        Directory.CreateDirectory(Path.Combine(world.StagingPath("not-a-guid"), "attempt-0001"));
        File.WriteAllBytes(world.StagingPath("stray.bin"), [1]);

        await world.RunCycleAsync();
        await world.RunCycleAsync();

        Assert.False(world.AttemptExists(job, "attempt-0001"));
        foreach (var name in new[] { "attempt-1", "attempt-00001", "attempt-0000", "Attempt-0001", "scratch" })
            Assert.True(world.AttemptExists(job, name));
        Assert.True(Directory.Exists(Path.Combine(upper, "attempt-0001")));
        Assert.True(Directory.Exists(world.StagingPath("not-a-guid")));
        Assert.True(File.Exists(world.StagingPath("stray.bin")));
        // Five entries in the job directory plus three at the staging root, each reported once.
        Assert.Equal(8, world.Logs.Count(1401));
    }

    // J6
    [Fact]
    public async Task CycleIsIdempotentAndToleratesConcurrentCleanupOfTheSameDirectories()
    {
        using var world = await JanitorWorld.CreateAsync();
        var jobs = new List<Guid>();
        for (var index = 0; index < 40; index++)
        {
            var job = await world.SeedJobAsync(VisionJobStatus.Completed, 2, Now.AddHours(-1));
            world.Stage(job, "attempt-0001", nested: true);
            world.Stage(job, "attempt-0002", nested: true);
            jobs.Add(job);
        }

        // Two independent janitors race over the same directories, as the worker's own
        // cleanup races the platform: neither may fail and everything must end up gone.
        var results = await Task.WhenAll(world.RunIndependentCycleAsync(), world.RunIndependentCycleAsync());

        Assert.True(results.All(result => result.Failed == 0), string.Join('\n', world.Logs.Entries(1403).Select(entry => entry.Message)));
        Assert.All(jobs, job => Assert.False(world.JobExists(job)));
        var again = await world.RunCycleAsync();
        Assert.Equal(0, again.Scanned);
        Assert.Equal(0, again.Failed);
    }

    // J7
    [Fact]
    public async Task LinkedAttemptAndJobDirectoriesAreRefusedAndTheirTargetsPreserved()
    {
        using var world = await JanitorWorld.CreateAsync();
        var outside = Path.Combine(Path.GetTempPath(), $"mavi-janitor-outside-{Guid.NewGuid():N}");
        Directory.CreateDirectory(outside);
        File.WriteAllBytes(Path.Combine(outside, "sentinel.bin"), [7]);
        var links = new List<string>();
        try
        {
            var linkedAttempt = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
            Directory.CreateDirectory(world.StagingPath(linkedAttempt.ToString("D")));
            links.Add(world.AttemptPath(linkedAttempt, "attempt-0001"));
            StagingDirectorySafetyTests.CreateDirectoryLink(links[^1], outside);
            var linkedJob = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
            links.Add(world.StagingPath(linkedJob.ToString("D")));
            StagingDirectorySafetyTests.CreateDirectoryLink(links[^1], outside);

            var cycle = await world.RunCycleAsync();

            Assert.Equal(0, cycle.Removed);
            Assert.True(File.Exists(Path.Combine(outside, "sentinel.bin")));
            Assert.True(new DirectoryInfo(world.AttemptPath(linkedAttempt, "attempt-0001")).Attributes.HasFlag(FileAttributes.ReparsePoint));
            Assert.True(new DirectoryInfo(world.StagingPath(linkedJob.ToString("D"))).Attributes.HasFlag(FileAttributes.ReparsePoint));
            Assert.All(world.Logs.Entries(1402), entry => Assert.Equal(LogLevel.Error, entry.Level));
            Assert.Equal(2, world.Logs.Count(1402));
        }
        finally
        {
            // Remove the links themselves (never their target) before anything recursive runs.
            foreach (var link in links.Where(path => Directory.Exists(path)))
                Directory.Delete(link);
            Directory.Delete(outside, recursive: true);
        }
    }

    // J9
    [Fact]
    public async Task DeletionFailureIsLoggedRetriedAndEscalatesAfterThreeCyclesWhileTheHostKeepsServing()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
        var deep = world.AttemptPath(job, "attempt-0001");
        for (var level = 0; level <= StagingDirectory.MaximumTreeDepth + 1; level++)
            deep = Path.Combine(deep, "d");
        Directory.CreateDirectory(deep);

        for (var cycle = 1; cycle <= 3; cycle++)
        {
            var result = await world.RunCycleAsync();
            Assert.Equal(1, result.Failed);
            Assert.Equal(0, result.Removed);
        }

        Assert.True(world.AttemptExists(job, "attempt-0001"));
        Assert.Equal(3, world.Logs.Count(1403));
        var escalation = Assert.Single(world.Logs.Entries(1404));
        Assert.Equal(LogLevel.Error, escalation.Level);

        using var client = world.Factory.CreateClient();
        var health = await JanitorWorld.HealthAsync(client);
        Assert.Equal(3, health.GetProperty("consecutiveFailures").GetInt32());
        Assert.Equal(1, health.GetProperty("failed").GetInt32());

        // Once the obstruction is gone the streak clears.
        Directory.Delete(world.AttemptPath(job, "attempt-0001"), recursive: true);
        world.Stage(job, "attempt-0001");
        Assert.Equal(1, (await world.RunCycleAsync()).Removed);
        Assert.Equal(0, (await JanitorWorld.HealthAsync(client)).GetProperty("consecutiveFailures").GetInt32());
    }

    // J10
    [Fact]
    public async Task UnknownJobDirectoryIsRemovedOnlyAfterUnknownGrace()
    {
        using var world = await JanitorWorld.CreateAsync(DateTimeOffset.UtcNow);
        var orphan = Guid.CreateVersion7();
        world.Stage(orphan, "attempt-0001");
        Directory.SetLastWriteTimeUtc(world.StagingPath(orphan.ToString("D")), world.Clock.GetUtcNow().AddHours(-23).UtcDateTime);

        Assert.Equal(0, (await world.RunCycleAsync()).Eligible);
        Assert.True(world.JobExists(orphan));

        Directory.SetLastWriteTimeUtc(world.StagingPath(orphan.ToString("D")), world.Clock.GetUtcNow().AddHours(-25).UtcDateTime);
        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.JobExists(orphan));
        Assert.Equal(LogLevel.Warning, Assert.Single(world.Logs.Entries(1409)).Level);
    }

    // J11
    [Fact]
    public async Task JanitorNeverTouchesAnythingOutsideTheStagingPrefix()
    {
        using var world = await JanitorWorld.CreateAsync();
        var job = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddHours(-1));
        world.Stage(job, "attempt-0001");
        var name = job.ToString("D");
        var sentinels = new[]
        {
            Path.Combine(world.Factory.MediaRoot, "source", name, "attempt-0001", "sentinel.bin"),
            Path.Combine(world.Factory.MediaRoot, name, "attempt-0001", "sentinel.bin"),
            Path.Combine(world.Factory.EvidenceRoot, name, "attempt-0001", "sentinel.bin"),
            Path.Combine(world.Factory.EvidenceRoot, "staging", name, "attempt-0001", "sentinel.bin"),
        };
        foreach (var sentinel in sentinels)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(sentinel)!);
            File.WriteAllBytes(sentinel, [3]);
        }

        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.JobExists(job));
        Assert.All(sentinels, sentinel => Assert.True(File.Exists(sentinel), sentinel));
    }

    // J12
    [Fact]
    public async Task BacklogDrainsAcrossCyclesWithThePerCycleCapAndTruthfulObservability()
    {
        const int cap = 2;
        using var world = await JanitorWorld.CreateAsync(options: new StagingJanitorOptions { MaxDirectoriesPerCycle = cap });
        var jobs = new List<Guid>();
        for (var index = 0; index < 2 * cap + 1; index++)
        {
            // Distinct ages: the first job is the oldest.
            var job = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddMinutes(-50 + index * 10));
            world.Stage(job, "attempt-0001");
            jobs.Add(job);
        }

        var first = await world.RunCycleAsync();
        Assert.Equal(5, first.Eligible);
        Assert.Equal(cap, first.Processed);
        Assert.Equal(cap, first.Removed);
        Assert.Equal(cap + 1, first.DeferredByCap);
        Assert.Equal(cap + 1, first.BacklogDepth);
        Assert.Equal(2, first.EstimatedCyclesToDrain);
        Assert.Equal(30, first.OldestEligibleAgeMinutes!.Value, 6);
        Assert.False(world.JobExists(jobs[0]));
        Assert.False(world.JobExists(jobs[1]));
        Assert.All(jobs.Skip(cap), job => Assert.True(world.JobExists(job)));

        var second = await world.RunCycleAsync();
        Assert.Equal(cap, second.Removed);
        Assert.Equal(1, second.BacklogDepth);
        Assert.Equal(1, second.EstimatedCyclesToDrain);

        var third = await world.RunCycleAsync();
        Assert.Equal(1, third.Removed);
        Assert.Equal(0, third.BacklogDepth);
        Assert.Equal(0, third.EstimatedCyclesToDrain);
        Assert.Null(third.OldestEligibleAgeMinutes);
        Assert.All(jobs, job => Assert.False(world.JobExists(job)));
    }

    // J13
    [Fact]
    public async Task BacklogAgeThresholdsEscalateAndRecover()
    {
        using var world = await JanitorWorld.CreateAsync(options: new StagingJanitorOptions { MaxDirectoriesPerCycle = 1 });
        using var client = world.Factory.CreateClient();
        var newest = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddMinutes(-90));
        var older = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddMinutes(-400));
        var oldest = await world.SeedJobAsync(VisionJobStatus.Completed, 1, Now.AddMinutes(-401));
        foreach (var job in new[] { newest, older, oldest })
            world.Stage(job, "attempt-0001");

        var critical = await world.RunCycleAsync();
        Assert.Equal("critical", critical.BacklogState);
        Assert.Equal(LogLevel.Error, Assert.Single(world.Logs.Entries(1408)).Level);
        Assert.Equal("critical", (await JanitorWorld.HealthAsync(client)).GetProperty("backlogState").GetString());

        var warning = await world.RunCycleAsync();
        Assert.Equal("warning", warning.BacklogState);
        Assert.Single(world.Logs.Entries(1407));
        Assert.Equal("warning", (await JanitorWorld.HealthAsync(client)).GetProperty("backlogState").GetString());

        var normal = await world.RunCycleAsync();
        Assert.Equal("normal", normal.BacklogState);
        Assert.Equal("normal", (await JanitorWorld.HealthAsync(client)).GetProperty("backlogState").GetString());
    }

    // J14
    [Fact]
    public async Task RetriedVideoOldFailedJobAndNewQueuedJobAreIndependent()
    {
        using var world = await JanitorWorld.CreateAsync();
        using var client = world.Factory.CreateClient();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(world.Factory);
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        using (var failed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/fail",
                   new VisionJobFailRequest("2.0", "gpu-sdd-01", lease.LeaseToken, "ffmpeg_decode_failed", null)))
            Assert.Equal(HttpStatusCode.OK, failed.StatusCode);
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();

        Guid retryJob;
        using (var scope = world.Factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var retry = await db.VisionJobs.AsNoTracking().SingleAsync(x => x.Id != lease.JobId);
            Assert.Equal(VisionJobStatus.Queued, retry.Status);
            Assert.Equal(0, retry.AttemptCount);
            retryJob = retry.Id;
        }

        world.Stage(lease.JobId, "attempt-0001");
        Directory.CreateDirectory(world.StagingPath(retryJob.ToString("D")));
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        var cycle = await world.RunCycleAsync();

        Assert.Equal(1, cycle.Removed);
        Assert.False(world.JobExists(lease.JobId));
        Assert.True(world.JobExists(retryJob));
        Assert.Equal(0, world.Logs.Count(1401)); // an empty queued job directory is silent

        world.Stage(retryJob, "attempt-0001");
        await world.RunCycleAsync();
        Assert.True(world.AttemptExists(retryJob, "attempt-0001"));
        Assert.Equal(1, world.Logs.Count(1401));
    }

    [Fact]
    public async Task HealthDetailsExposeJanitorStatus()
    {
        using var world = await JanitorWorld.CreateAsync();
        using var client = world.Factory.CreateClient();

        var before = await JanitorWorld.HealthAsync(client);
        Assert.False(before.GetProperty("enabled").GetBoolean()); // the test host keeps the scheduler off
        Assert.Equal(JsonValueKind.Null, before.GetProperty("lastRunUtc").ValueKind);

        await world.RunCycleAsync();
        var after = await JanitorWorld.HealthAsync(client);
        Assert.NotEqual(JsonValueKind.Null, after.GetProperty("lastRunUtc").ValueKind);
        foreach (var property in new[] { "lastCycleRemoved", "failed", "deferredByCap", "backlogDepth", "oldestEligibleAgeMinutes", "consecutiveFailures", "backlogState" })
            Assert.True(after.TryGetProperty(property, out _), property);
    }

    // World
    private sealed class JanitorWorld : IDisposable
    {
        private int _sequence;

        private JanitorWorld(ApiTestFactory factory, MutableTimeProvider clock, CapturingLoggerProvider logs)
        {
            Factory = factory;
            Clock = clock;
            Logs = logs;
        }

        public ApiTestFactory Factory { get; }
        public MutableTimeProvider Clock { get; }
        public CapturingLoggerProvider Logs { get; }

        public static async Task<JanitorWorld> CreateAsync(DateTimeOffset? now = null, StagingJanitorOptions? options = null)
        {
            var clock = new MutableTimeProvider(now ?? Now);
            var logs = new CapturingLoggerProvider();
            var factory = new ApiTestFactory
            {
                Clock = clock,
                OverrideServices = services =>
                {
                    services.AddSingleton<ILoggerProvider>(logs);
                    if (options is not null)
                    {
                        services.RemoveAll<IOptions<StagingJanitorOptions>>();
                        services.AddSingleton(Options.Create(options));
                    }
                },
            };
            await factory.ResetAndMigrateAsync();
            Directory.CreateDirectory(Path.Combine(factory.MediaRoot, "staging"));
            return new JanitorWorld(factory, clock, logs);
        }

        public async Task<StagingJanitorCycleResult> RunCycleAsync()
        {
            await using var scope = Factory.Services.CreateAsyncScope();
            return await scope.ServiceProvider.GetRequiredService<IStagingJanitor>().RunCycleAsync(CancellationToken.None);
        }

        /// <summary>A second janitor with its own state and gate, as an independent concurrent cleaner.</summary>
        public async Task<StagingJanitorCycleResult> RunIndependentCycleAsync()
        {
            await using var scope = Factory.Services.CreateAsyncScope();
            var provider = scope.ServiceProvider;
            var janitor = new StagingJanitor(
                provider.GetRequiredService<MaviDbContext>(),
                provider.GetRequiredService<IOptions<MediaStorageOptions>>(),
                provider.GetRequiredService<IOptions<StagingJanitorOptions>>(),
                new StagingJanitorState(provider.GetRequiredService<IOptions<StagingJanitorOptions>>()),
                Clock,
                provider.GetRequiredService<ILogger<StagingJanitor>>());
            await Task.Yield();
            return await janitor.RunCycleAsync(CancellationToken.None);
        }

        public static async Task<JsonElement> HealthAsync(HttpClient client)
        {
            using var document = JsonDocument.Parse(await client.GetStringAsync("/api/health"));
            return document.RootElement.GetProperty("details").GetProperty("stagingJanitor").Clone();
        }

        public async Task<Guid> SeedJobAsync(VisionJobStatus status, int attemptCount, DateTimeOffset? completedAtUtc)
        {
            var index = Interlocked.Increment(ref _sequence);
            using var scope = Factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var camera = Camera.Create($"CAM-J{index}", "Janitor", "UTC", Now);
            var source = Artifact.Create(ArtifactType.SourceVideo, $"source/janitor-{index}.mp4", "video/mp4", 1,
                index.ToString("x64", System.Globalization.CultureInfo.InvariantCulture), createdAtUtc: Now);
            var video = VideoAsset.Create(camera.Id, source.Id, "janitor.mp4", Now, 60_000, 25, 1, 1920, 1080, "h264",
                TimestampSource.Manual, 1, importedAtUtc: Now);
            var run = ProcessingRun.Create(video.Id, "phase1-v1", "{}", Now);
            var job = VisionJob.Create(run.Id, "phase1-detection-tracking", Now);
            db.AddRange(camera, source, video, run, job);
            await db.SaveChangesAsync();
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE vision_jobs SET status = {status.ToString()}, attempt_count = {attemptCount}, completed_at_utc = {completedAtUtc} WHERE id = {job.Id}");
            return job.Id;
        }

        public string StagingPath(string name) => Path.Combine(Factory.MediaRoot, "staging", name);

        public string AttemptPath(Guid job, string attempt) => Path.Combine(StagingPath(job.ToString("D")), attempt);

        public void Stage(Guid job, string attempt, bool nested = false)
        {
            var path = AttemptPath(job, attempt);
            Directory.CreateDirectory(Path.Combine(path, "trajectories"));
            File.WriteAllBytes(Path.Combine(path, "trajectories", "person-000001.msgpack"), new byte[10]);
            if (nested)
            {
                Directory.CreateDirectory(Path.Combine(path, "evidence", "deep"));
                File.WriteAllBytes(Path.Combine(path, "evidence", "deep", "a.jpg"), new byte[4]);
            }
        }

        public bool JobExists(Guid job) => Directory.Exists(StagingPath(job.ToString("D")));

        public bool AttemptExists(Guid job, string attempt) =>
            Directory.Exists(AttemptPath(job, attempt)) || File.Exists(AttemptPath(job, attempt));

        public void Dispose() => Factory.Dispose();
    }

    internal sealed record CapturedLog(int EventId, LogLevel Level, string Message);

    internal sealed class CapturingLoggerProvider : ILoggerProvider
    {
        private readonly ConcurrentQueue<CapturedLog> _entries = new();

        public IEnumerable<CapturedLog> Entries(int eventId) => _entries.Where(entry => entry.EventId == eventId).ToList();

        public int Count(int eventId) => Entries(eventId).Count();

        public ILogger CreateLogger(string categoryName) => new Logger(categoryName, _entries);

        public void Dispose()
        {
        }

        private sealed class Logger(string category, ConcurrentQueue<CapturedLog> entries) : ILogger
        {
            public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

            public bool IsEnabled(LogLevel logLevel) => true;

            public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
            {
                if (category.StartsWith("Mavi.Infrastructure.Storage.StagingJanitor", StringComparison.Ordinal))
                    entries.Enqueue(new CapturedLog(eventId.Id, logLevel,
                        exception is null ? formatter(state, exception) : $"{formatter(state, exception)} {exception}"));
            }
        }
    }
}
