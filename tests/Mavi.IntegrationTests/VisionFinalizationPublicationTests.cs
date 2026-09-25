using System.Data.Common;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The single publication transaction (F3 plan §7.4, §10.2; slice 5): its ordering, that
/// nothing is visible before its commit, that a stale claimant cannot publish, and both
/// resolutions of an ambiguous commit.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationPublicationTests
{
    [Fact]
    public async Task PublicationCommitsTheGraphCompletionSequenceAndVideoTogether()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);
        world.Clock.Advance(TimeSpan.FromSeconds(7));
        world.Sql.Clear();

        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Published, outcome.Kind);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(world.Clock.GetUtcNow(), job.CompletedAtUtc);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Equal(handOff.Ack.AcceptedAtUtc, job.FinalizationAcceptedAtUtc);
        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal(1, run.TracksCreated);
        Assert.Equal(4, run.FramesProcessed);
        Assert.Equal(1250, run.ProcessingDurationMs);
        Assert.Equal(1L, run.VisibilitySequence);
        Assert.Equal(world.Clock.GetUtcNow(), run.CompletedAtUtc);
        Assert.NotNull(run.DetectorName);
        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);
        Assert.Equal(1L, await world.VisibilityAllocationsAsync());

        using var scope = world.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var track = await db.Tracks.SingleAsync(x => x.ProcessingRunId == run.Id);
        Assert.NotNull(track.RepresentativeObservationId);
        Assert.NotNull(track.TrajectoryArtifactId);
        Assert.Equal(4, await db.Observations.CountAsync(x => x.TrackId == track.Id));
        var artifacts = await db.Artifacts.Where(x => x.ArtifactType != ArtifactType.SourceVideo).ToListAsync();
        Assert.Equal(5, artifacts.Count);
        Assert.All(artifacts, x => Assert.StartsWith($"evidence/{claim.JobId:D}/attempt-{claim.AttemptCount:0000}/", x.StorageKey, StringComparison.Ordinal));
        Assert.Equal(5, world.EvidenceFiles().Length);

        // Ordering: the job lock precedes the graph INSERTs, which precede the advisory lock,
        // which precedes the completion UPDATEs and the COMMIT (F3 plan §7.4). The sequence
        // allocation runs as a raw command on the connection, invisible to EF interceptors; it
        // is proven by the assigned VisibilitySequence above, which only exists after the barrier.
        var commands = world.Sql.Commands.ToList();
        int First(string needle) => commands.FindIndex(x => x.Contains(needle, StringComparison.Ordinal));
        int Last(string needle) => commands.FindLastIndex(x => x.Contains(needle, StringComparison.Ordinal));
        var barrier = First("pg_advisory_xact_lock(1296127561, 1412505908)");
        Assert.True(barrier >= 0, "the completion barrier was taken");
        Assert.True(First("FOR UPDATE") >= 0 && First("FOR UPDATE") < First("INSERT INTO tracks"), "the job is locked first");
        Assert.True(Last("INSERT INTO ") < barrier, "graph persisted before the barrier");
        Assert.True(barrier < Last("UPDATE vision_jobs"), "barrier before the completion update");
        Assert.True(barrier < Last("UPDATE processing_runs"));
        Assert.True(barrier < Last("UPDATE video_assets"));
        Assert.True(barrier < Last("UPDATE tracks SET representative_observation_id"), "the representative attachment lands in the final save");
        Assert.Equal(1, commands.Count(x => x.Contains("pg_advisory_xact_lock(", StringComparison.Ordinal)));

        // Idempotence: a second publication of the same claim is stale, writes nothing.
        var again = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Stale, again.Kind);
        Assert.Equal(1L, await world.VisibilityAllocationsAsync());
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
    }

    [Fact]
    public async Task NothingIsVisibleBeforeThePublicationCommit()
    {
        var faults = new CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);
        var filesBefore = world.EvidenceFiles();

        faults.Arm(failBeforeCommit: true);
        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Ambiguous, outcome.Kind);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.True(job.FinalizationOwnedBy(claim.ClaimToken.Span, world.Clock.GetUtcNow()), "the claim is untouched");
        Assert.Equal(ProcessingRunStatus.Running, run.Status);
        Assert.Null(run.VisibilitySequence);
        Assert.Equal(0, run.TracksCreated);
        Assert.Equal(VideoProcessingStatus.Processing, video.ProcessingStatus);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        Assert.Equal(filesBefore, world.EvidenceFiles()); // no compensation deletion, no new objects
        Assert.Equal(1, await world.PayloadCountAsync());

        // The note on an uncommitted job records the ambiguity and releases the claim; the
        // retry adopts every sealed object and publishes once (F3 plan §10.2).
        var note = await world.WithLifecycleAsync(l => l.NoteTransientAsync(claim, VisionFinalizationFailureCodes.PublicationAmbiguous, true, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Noted, note.Kind);
        var retry = (await world.ClaimAsync())!;
        Assert.Equal(2, retry.FinalizationAttemptCount);
        var (retryResult, retryGraph) = await world.PrepareAsync(retry);
        Assert.Equal(filesBefore, world.EvidenceFiles());
        Assert.Equal(VisionFinalizationTransitionKind.Published, (await world.WithLifecycleAsync(l => l.PublishAsync(retry, retryResult, retryGraph, CancellationToken.None))).Kind);
        // nextval is non-transactional: the rolled-back publication consumed a value that no
        // run carries. The published run carries the latest one, and it is the only one assigned.
        var (_, published, _) = await world.StateAsync(claim.JobId);
        Assert.Equal(await world.VisibilityAllocationsAsync(), published.VisibilitySequence);
        Assert.Equal(1, await world.TrackCountAsync(published.Id));
        Assert.Equal("vision_finalization_publication_ambiguous", (await world.JobAsync(claim.JobId)).FinalizationLastErrorCode);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(claim.JobId)).Status);
    }

    [Fact]
    public async Task AmbiguousCommitThatSucceededIsNotRepublishedAndTheNoteWritesNothing()
    {
        var faults = new CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);

        faults.Arm(failAfterCommit: true);
        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Ambiguous, outcome.Kind);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal(1L, run.VisibilitySequence);
        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);

        // The transient note finds Completed, fails ownership, writes nothing (with or without a release).
        var note = await world.WithLifecycleAsync(l => l.NoteTransientAsync(claim, VisionFinalizationFailureCodes.PublicationAmbiguous, true, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Stale, note.Kind);
        var plainNote = await world.WithLifecycleAsync(l => l.NoteTransientAsync(claim, VisionFinalizationFailureCodes.PublicationAmbiguous, false, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Stale, plainNote.Kind);
        var after = await world.JobAsync(claim.JobId);
        Assert.Null(after.FinalizationLastErrorCode);
        Assert.Equal(VisionJobStatus.Completed, after.Status);
        // Nothing claimable, nothing to reconcile, one sequence ever.
        Assert.Null(await world.ClaimAsync());
        Assert.Equal(0, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(world.Policy, 10, CancellationToken.None))).Exhausted);
        Assert.Equal(1L, await world.VisibilityAllocationsAsync());
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
    }

    [Fact]
    public async Task StaleClaimantCannotPublish()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var stale = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(stale);
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        var live = (await world.ClaimAsync())!;
        world.Sql.Clear();

        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(stale, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Stale, outcome.Kind);
        // Refused at the early ownership check: no bulk write and no barrier for a stale claimant.
        Assert.DoesNotContain(world.Sql.Commands, x => x.Contains("INSERT INTO", StringComparison.Ordinal));
        Assert.DoesNotContain(world.Sql.Commands, x => x.Contains("pg_advisory_xact_lock", StringComparison.Ordinal));
        var (job, run, video) = await world.StateAsync(stale.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.True(job.FinalizationOwnedBy(live.ClaimToken.Span, world.Clock.GetUtcNow()));
        Assert.Equal(ProcessingRunStatus.Running, run.Status);
        Assert.Equal(VideoProcessingStatus.Processing, video.ProcessingStatus);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        Assert.Equal(0L, await world.VisibilityAllocationsAsync());

        // The live claimant adopts what the stale one sealed and publishes.
        var (liveResult, liveGraph) = await world.PrepareAsync(live);
        Assert.Equal(VisionFinalizationTransitionKind.Published, (await world.WithLifecycleAsync(l => l.PublishAsync(live, liveResult, liveGraph, CancellationToken.None))).Kind);
    }

    [Fact]
    public async Task AnExpiredClaimCannotPublishEvenWithoutAReclaim()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);
        world.Clock.Advance(TimeSpan.FromMinutes(5));
        world.Sql.Clear();

        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Stale, outcome.Kind);
        // Same identity, expired ownership: refused before any bulk write or barrier.
        Assert.DoesNotContain(world.Sql.Commands, x => x.Contains("INSERT INTO", StringComparison.Ordinal));
        Assert.DoesNotContain(world.Sql.Commands, x => x.Contains("pg_advisory_xact_lock", StringComparison.Ordinal));
        Assert.Equal(0, await world.TrackCountAsync(claim.ProcessingRunId));
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(claim.JobId)).Status);
    }

    [Fact]
    public async Task ALiveClaimPastTheDeadlineMayStillPublish()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);
        world.Clock.Advance(deadline.AddMinutes(-1) - world.Clock.GetUtcNow());
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);
        world.Clock.Advance(TimeSpan.FromMinutes(2));

        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Published, outcome.Kind);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(claim.JobId)).Status);
    }

    [Fact]
    public async Task PublicationRefusesAWrongAttemptOrDigestAsStale()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);

        var wrongAttempt = claim with { AttemptCount = claim.AttemptCount + 1 };
        var wrongDigest = claim with { CompletionDigest = new string('b', 64) };
        var wrongFinalizationAttempt = claim with { FinalizationAttemptCount = 2 };

        Assert.Equal(VisionFinalizationTransitionKind.Stale, (await world.WithLifecycleAsync(l => l.PublishAsync(wrongAttempt, result, graph, CancellationToken.None))).Kind);
        Assert.Equal(VisionFinalizationTransitionKind.Stale, (await world.WithLifecycleAsync(l => l.PublishAsync(wrongDigest, result, graph, CancellationToken.None))).Kind);
        Assert.Equal(VisionFinalizationTransitionKind.Stale, (await world.WithLifecycleAsync(l => l.PublishAsync(wrongFinalizationAttempt, result, graph, CancellationToken.None))).Kind);
        Assert.Equal(0, await world.TrackCountAsync(claim.ProcessingRunId));
        Assert.Equal(VisionFinalizationTransitionKind.Published, (await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None))).Kind);
    }

    [Fact]
    public async Task PublicationFailsClosedWhenTheRunIsNotRunningOrAGraphAlreadyExists()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);

        // A graph row for the run that no hand-off could have produced.
        using (var scope = world.Factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var video = await db.VideoAssets.SingleAsync();
            db.Tracks.Add(Mavi.Domain.Intelligence.Track.Create(claim.ProcessingRunId, video.Id, 99, Mavi.Domain.Intelligence.ObjectClass.Person, 0, 10, video.RecordingStartUtc, 1, .5, .5, world.Clock.GetUtcNow()));
            await db.SaveChangesAsync();
        }

        var existing = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Failed, existing.Kind);
        Assert.Equal("vision_finalization_context_invalid", existing.Code);
        // Nothing was written by the publication itself; the executor decides the terminal write.
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(claim.JobId)).Status);
        Assert.Equal(1, await world.TrackCountAsync(claim.ProcessingRunId));
        Assert.Equal(0L, await world.VisibilityAllocationsAsync());

        await world.ExecuteSqlAsync("DELETE FROM tracks WHERE processing_run_id = $1", claim.ProcessingRunId);
        await world.ExecuteSqlAsync("UPDATE processing_runs SET status = 'Queued' WHERE id = $1", claim.ProcessingRunId);
        var notRunning = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));
        Assert.Equal(VisionFinalizationTransitionKind.Failed, notRunning.Kind);
        Assert.Equal("vision_finalization_context_invalid", notRunning.Code);
    }

    [Fact]
    public async Task ADatabaseFaultDuringGraphPersistenceIsARetryWithNothingWritten()
    {
        var faults = new CommitFaults();
        using var world = await FinalizationWorld.CreateAsync(configureDbContext: b => b.AddInterceptors(faults, faults.InsertInterceptor));
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        var (result, graph) = await world.PrepareAsync(claim);

        faults.Arm(failOnInsert: true);
        var outcome = await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Retry, outcome.Kind);
        Assert.Equal("vision_finalization_db_transient", outcome.Code);
        Assert.Equal(0, await world.TrackCountAsync(claim.ProcessingRunId));
        Assert.Equal(0L, await world.VisibilityAllocationsAsync());
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(claim.JobId)).Status);

        // The same claim retries the publication (no new claim needed while it is live).
        Assert.Equal(VisionFinalizationTransitionKind.Published, (await world.WithLifecycleAsync(l => l.PublishAsync(claim, result, graph, CancellationToken.None))).Kind);
    }

    /// <summary>
    /// Fails the <b>publication</b> transaction (the one that wrote the graph) before or after
    /// its real commit, or the graph INSERT itself. Other transactions (claims, extensions,
    /// notes) are never touched, so the fault lands exactly where the plan's ambiguity lives.
    /// </summary>
    internal sealed class CommitFaults : DbTransactionInterceptor
    {
        private readonly InsertFault _insert = new();
        private volatile bool _failBeforeCommit;
        private volatile bool _failAfterCommit;

        public void Arm(bool failBeforeCommit = false, bool failAfterCommit = false, bool failOnInsert = false)
        {
            _failBeforeCommit = failBeforeCommit;
            _failAfterCommit = failAfterCommit;
            _insert.Armed = failOnInsert;
        }

        public DbCommandInterceptor InsertInterceptor => _insert;

        public override ValueTask<InterceptionResult> TransactionCommittingAsync(DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            if (_failBeforeCommit && _insert.SawGraphInsert)
            {
                _failBeforeCommit = false;
                throw new InvalidOperationException("Injected failure before the database commit.");
            }

            return base.TransactionCommittingAsync(transaction, eventData, result, cancellationToken);
        }

        public override Task TransactionCommittedAsync(DbTransaction transaction, TransactionEndEventData eventData, CancellationToken cancellationToken = default)
        {
            if (_failAfterCommit && _insert.SawGraphInsert)
            {
                _failAfterCommit = false;
                throw new InvalidOperationException("Injected failure after the database commit.");
            }

            return base.TransactionCommittedAsync(transaction, eventData, cancellationToken);
        }

        public override ValueTask<DbTransaction> TransactionStartedAsync(DbConnection connection, TransactionEndEventData eventData, DbTransaction result, CancellationToken cancellationToken = default)
        {
            _insert.SawGraphInsert = false;
            return base.TransactionStartedAsync(connection, eventData, result, cancellationToken);
        }

        private sealed class InsertFault : DbCommandInterceptor
        {
            public volatile bool Armed;
            public volatile bool SawGraphInsert;

            public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
            {
                if (command.CommandText.Contains("INSERT INTO tracks", StringComparison.Ordinal))
                {
                    if (Armed)
                    {
                        Armed = false;
                        throw new Npgsql.NpgsqlException("Injected database fault during graph persistence.");
                    }

                    SawGraphInsert = true;
                }

                return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
            }
        }
    }
}
