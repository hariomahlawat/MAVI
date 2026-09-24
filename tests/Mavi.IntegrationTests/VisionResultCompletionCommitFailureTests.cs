using System.Data.Common;
using System.Net;
using System.Net.Http.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Mavi.IntegrationTests;

/// <summary>
/// S1.4 B4: completion 3.0 at the database commit boundary (plan §8).
/// <para>
/// The real <c>ProcessingResultStore</c> semantics, not a stronger claim. Newly
/// sealed evidence is compensated only when the store can prove the database
/// did not commit: the commit was not attempted, or the rollback was confirmed.
/// When the outcome is ambiguous, the evidence is retained and event 1301 is
/// logged. Retained evidence is unreferenced until an exact replay adopts it.
/// The replay re-seals idempotently, because an existing, hash-verified
/// destination is accepted as sealed.
/// </para>
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionResultCompletionCommitFailureTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];
    private const int RollbackConfirmationFailureEventId = 1301;

    [Fact]
    public async Task CommitFailureWithConfirmedRollbackCompensatesAndPublishesNothing()
    {
        var faults = new CommitBoundaryFaults();
        var logs = new CapturingLoggerProvider();
        using var factory = Factory(faults, logs);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failBeforeCommit: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        Assert.True(faults.RollbackReached);
        await AssertNoIntelligenceAsync(factory);
        Assert.Empty(EvidenceFiles(factory));
        Assert.DoesNotContain(logs.Entries, x => x.EventId.Id == RollbackConfirmationFailureEventId);

        // The staged inputs are untouched, so the worker's retry completes normally.
        using var retried = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, retried.StatusCode);
        await AssertPublishedOnceAsync(factory, client, lease);
    }

    [Fact]
    public async Task CommitThatSucceededButReportedFailureRetainsEvidenceAndExactReplayIsIdempotent()
    {
        // The ambiguous case: the database committed, then the commit call failed.
        // The rollback cannot be confirmed (the transaction is already complete), so
        // compensation must not run: deleting the evidence would orphan committed rows.
        var faults = new CommitBoundaryFaults();
        var logs = new CapturingLoggerProvider();
        using var factory = Factory(faults, logs);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failAfterCommit: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        Assert.Contains(logs.Entries, x => x.EventId.Id == RollbackConfirmationFailureEventId && x.Level == LogLevel.Error);
        Assert.Equal(Roles.Length + 1, EvidenceFiles(factory).Length);
        var committedRunId = await AssertPublishedOnceAsync(factory, client, lease);

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var response = await replay.Content.ReadFromJsonAsync<VisionJobCompleteResponse>();
        Assert.Equal(committedRunId, response!.ProcessingRunId);
        Assert.Equal(committedRunId, await AssertPublishedOnceAsync(factory, client, lease));
        Assert.Equal(Roles.Length + 1, EvidenceFiles(factory).Length);
    }

    [Fact]
    public async Task UnconfirmedRollbackRetainsUnreferencedEvidenceAndExactReplayAdoptsIt()
    {
        // The commit did not happen, but the rollback could not be confirmed either.
        // The store cannot tell this from the committed case, so it retains the evidence.
        var faults = new CommitBoundaryFaults();
        var logs = new CapturingLoggerProvider();
        using var factory = Factory(faults, logs);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failBeforeCommit: true, failRollback: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        Assert.Contains(logs.Entries, x => x.EventId.Id == RollbackConfirmationFailureEventId && x.Level == LogLevel.Error);
        var retained = EvidenceFiles(factory);
        Assert.Equal(Roles.Length + 1, retained.Length);
        await AssertNoIntelligenceAsync(factory);
        await AssertUnreferencedAsync(factory, retained);

        var retainedWrites = retained.ToDictionary(path => path, File.GetLastWriteTimeUtc);
        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        await AssertPublishedOnceAsync(factory, client, lease);
        // Adopted in place: the same files, not a second copy.
        Assert.Equal(retained.Order(StringComparer.Ordinal), EvidenceFiles(factory).Order(StringComparer.Ordinal));
        Assert.All(retainedWrites, x => Assert.Equal(x.Value, File.GetLastWriteTimeUtc(x.Key)));
    }

    [Fact]
    public async Task ProcessLossAfterSealingBeforeCommitLeavesEvidenceUnservedUntilExactReplay()
    {
        // Process loss between sealing and commit leaves exactly what a crashed
        // store would: sealed files, no rows. Modelled by sealing through the real
        // accepted-evidence store, then completing in a fresh request.
        using var factory = Factory(new CommitBoundaryFaults(), new CapturingLoggerProvider());
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        await using (var scope = factory.Services.CreateAsyncScope())
        {
            var accepted = scope.ServiceProvider.GetRequiredService<IAcceptedEvidenceStore>();
            var track = request.Tracks!.Single();
            foreach (var observation in track.Observations!)
                await SealAsync(accepted, observation.Crop!, AcceptedKey(lease, "crops", $"{track.TrackId}-{observation.Role}", observation.Crop!.Sha256!, "jpg"));
            await SealAsync(accepted, track.TrajectoryArtifact!, AcceptedKey(lease, "trajectories", track.TrackId!, track.TrajectoryArtifact!.Sha256!, "msgpack"));
        }

        var sealedFiles = EvidenceFiles(factory);
        Assert.Equal(Roles.Length + 1, sealedFiles.Length);
        await AssertNoIntelligenceAsync(factory);
        await AssertUnreferencedAsync(factory, sealedFiles);

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var runId = await AssertPublishedOnceAsync(factory, client, lease);
        Assert.Equal(sealedFiles.Order(StringComparer.Ordinal), EvidenceFiles(factory).Order(StringComparer.Ordinal));

        using var second = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        Assert.Equal(runId, await AssertPublishedOnceAsync(factory, client, lease));
    }

    // Helpers
    private static ApiTestFactory Factory(CommitBoundaryFaults faults, CapturingLoggerProvider logs) => new()
    {
        Clock = new MutableTimeProvider(Now),
        ConfigureDbContext = options => options.AddInterceptors(faults),
        OverrideServices = services => services.AddSingleton<ILoggerProvider>(logs),
    };

    private static async Task<(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request)> LeasedCompletionAsync(
        ApiTestFactory factory)
    {
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await VisionResultCompletionV3ApiTests.BuildRequestAsync(factory, lease, Roles);
        return (client, lease, request);
    }

    private static string AcceptedKey(VisionJobLeaseContract lease, string category, string stem, string sha256, string extension) =>
        $"evidence/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/{category}/{stem}-{sha256}.{extension}";

    private static async Task SealAsync(IAcceptedEvidenceStore store, VisionArtifactDescriptorContract descriptor, string acceptedKey)
    {
        var sealedResult = await store.SealAsync(
            descriptor.StorageKey!, acceptedKey, descriptor.SizeBytes!.Value, descriptor.Sha256!, CancellationToken.None);
        Assert.Equal(AcceptedEvidenceSealStatus.Sealed, sealedResult.Status);
        Assert.True(sealedResult.CreatedNew);
    }

    private static string[] EvidenceFiles(ApiTestFactory factory) =>
        Directory.Exists(factory.EvidenceRoot)
            ? Directory.GetFiles(factory.EvidenceRoot, "*", SearchOption.AllDirectories)
            : [];

    private static async Task AssertNoIntelligenceAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Empty(await db.Tracks.ToListAsync());
        Assert.Empty(await db.Observations.ToListAsync());
        Assert.Equal(1, await db.Artifacts.CountAsync());
        Assert.Equal(VisionJobStatus.Leased, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(ProcessingRunStatus.Running, (await db.ProcessingRuns.SingleAsync()).Status);
    }

    /// <summary>Evidence with no Artifact row has no id, so no read path can serve it.</summary>
    private static async Task AssertUnreferencedAsync(ApiTestFactory factory, IEnumerable<string> files)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var referenced = await db.Artifacts.Select(x => x.StorageKey).ToListAsync();
        foreach (var file in files)
        {
            var key = "evidence/" + Path.GetRelativePath(factory.EvidenceRoot, file).Replace(Path.DirectorySeparatorChar, '/');
            Assert.DoesNotContain(key, referenced);
        }
    }

    /// <summary>Exactly one published Evidence Set, every crop served from its row.</summary>
    private static async Task<Guid> AssertPublishedOnceAsync(ApiTestFactory factory, HttpClient client, VisionJobLeaseContract lease)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Single(await db.Tracks.ToListAsync());
        Assert.Equal(Roles.Length, await db.Observations.CountAsync());
        var crops = await db.Artifacts.Where(x => x.ArtifactType == ArtifactType.EvidenceCrop).ToListAsync();
        Assert.Equal(Roles.Length, crops.Count);
        Assert.Equal(1, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.TrackTrajectory));
        Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
        var run = await db.ProcessingRuns.SingleAsync();
        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        foreach (var crop in crops)
        {
            Assert.StartsWith($"evidence/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/crops/", crop.StorageKey, StringComparison.Ordinal);
            using var content = await client.GetAsync($"/api/artifacts/{crop.Id:D}/content");
            Assert.Equal(HttpStatusCode.OK, content.StatusCode);
            Assert.Equal(crop.SizeBytes, (await content.Content.ReadAsByteArrayAsync()).LongLength);
        }

        return run.Id;
    }

    private sealed class InjectedCommitBoundaryException(string message) : Exception(message);

    /// <summary>
    /// Fails the next transaction commit on either side of the real database commit,
    /// and optionally the rollback that follows. It is armed only for the completion
    /// under test, so setup and lease transactions are unaffected.
    /// </summary>
    private sealed class CommitBoundaryFaults : DbTransactionInterceptor
    {
        private volatile bool _failBeforeCommit;
        private volatile bool _failAfterCommit;
        private volatile bool _failRollback;

        public bool RollbackReached { get; private set; }

        public void Arm(bool failBeforeCommit = false, bool failAfterCommit = false, bool failRollback = false)
        {
            _failBeforeCommit = failBeforeCommit;
            _failAfterCommit = failAfterCommit;
            _failRollback = failRollback;
            RollbackReached = false;
        }

        public override ValueTask<InterceptionResult> TransactionCommittingAsync(
            DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            if (_failBeforeCommit)
            {
                _failBeforeCommit = false;
                throw new InjectedCommitBoundaryException("Injected failure before the database commit.");
            }

            return base.TransactionCommittingAsync(transaction, eventData, result, cancellationToken);
        }

        public override Task TransactionCommittedAsync(
            DbTransaction transaction, TransactionEndEventData eventData, CancellationToken cancellationToken = default)
        {
            if (_failAfterCommit)
            {
                _failAfterCommit = false;
                throw new InjectedCommitBoundaryException("Injected failure after the database commit.");
            }

            return base.TransactionCommittedAsync(transaction, eventData, cancellationToken);
        }

        public override ValueTask<InterceptionResult> TransactionRollingBackAsync(
            DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            RollbackReached = true;
            if (_failRollback)
            {
                _failRollback = false;
                throw new InjectedCommitBoundaryException("Injected failure confirming the rollback.");
            }

            return base.TransactionRollingBackAsync(transaction, eventData, result, cancellationToken);
        }
    }

    private sealed record LoggedEntry(LogLevel Level, EventId EventId, string Message);

    private sealed class CapturingLoggerProvider : ILoggerProvider
    {
        private readonly System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> _entries = new();

        public IReadOnlyCollection<LoggedEntry> Entries => _entries.ToArray();

        public ILogger CreateLogger(string categoryName) => new Capturing(_entries);

        public void Dispose()
        {
        }

        private sealed class Capturing(System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> entries) : ILogger
        {
            public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

            public bool IsEnabled(LogLevel logLevel) => true;

            public void Log<TState>(
                LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
                entries.Enqueue(new LoggedEntry(logLevel, eventId, formatter(state, exception)));
        }
    }
}
