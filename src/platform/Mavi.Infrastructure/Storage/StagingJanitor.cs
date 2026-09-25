using System.Globalization;
using Mavi.Application.Abstractions.Storage;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Reclaims <c>{MediaStorage:RootPath}/staging/{jobId}/attempt-NNNN</c> directories that the
/// VisionJob row proves dead (ADR-006 §6; S1.2 plan §6.5).
/// </summary>
/// <remarks>
/// <para>
/// Authority, per job directory, from one row read:
/// <list type="bullet">
/// <item><b>Completed / Failed</b>: every canonical attempt once <c>now ≥ CompletedAtUtc + Grace</c>,
/// then the job directory itself if it is left empty.</item>
/// <item><b>Cancelled</b>: nothing produces it today; treated like the terminal states because the
/// enum defines it as terminal, and logged once (1405).</item>
/// <item><b>Leased</b>: attempts <c>k &lt; AttemptCount</c> immediately (fenced by the lease authority);
/// never the current or a later attempt, never the job directory.</item>
/// <item><b>Finalizing</b>: the same as Leased. The current attempt is the finalizer's input and
/// survives until the job is terminal (ADR-006 §7); a later attempt is reported (1401) and kept.</item>
/// <item><b>Queued, AttemptCount 0</b>: no attempt has run; attempt directories are unexpected,
/// logged once (1401) and preserved.</item>
/// <item><b>Queued, AttemptCount &gt; 0</b>: unreachable in the aggregate; an invariant violation
/// (1406, Error), nothing deleted, nothing inferred.</item>
/// <item><b>No row</b>: only once the job directory is older than <c>UnknownJobGrace</c> (1409, Warning).</item>
/// </list>
/// </para>
/// <para>
/// Only canonical names are ever acted on: a job directory named by a lower-case "D" GUID
/// and attempts named <c>attempt-NNNN</c> exactly as the worker writes them. Anything else is
/// logged once (1401) and left alone. Deletion goes through <see cref="StagingDirectory"/>,
/// which never follows a link and never leaves <c>staging/</c>; the evidence root is never
/// opened.
/// </para>
/// </remarks>
public sealed partial class StagingJanitor(
    MaviDbContext db,
    IOptions<MediaStorageOptions> mediaOptions,
    IOptions<StagingJanitorOptions> janitorOptions,
    StagingJanitorState state,
    TimeProvider clock,
    ILogger<StagingJanitor> logger) : IStagingJanitor
{
    private const string StagingDirectoryName = "staging";
    private const int RowLookupBatchSize = 1000;
    private const int FailureEscalationCycles = 3;

    /// <summary>Whether this platform has a verified handle-relative reclamation implementation.</summary>
    public static bool IsPlatformSupported => StagingDirectory.IsSupported;

    /// <summary>Opens the media root; replaceable only by tests, to inject filesystem faults.</summary>
    internal Func<string, StagingDirectory> OpenRoot { get; init; } = StagingDirectory.OpenRoot;

    public async Task<StagingJanitorCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        await state.Gate.WaitAsync(cancellationToken);
        try
        {
            return await RunCycleCoreAsync(cancellationToken);
        }
        finally
        {
            state.Gate.Release();
        }
    }

    private async Task<StagingJanitorCycleResult> RunCycleCoreAsync(CancellationToken cancellationToken)
    {
        var options = janitorOptions.Value;
        var nowUtc = clock.GetUtcNow();
        var presentKeys = new HashSet<string>(StringComparer.Ordinal);

        using var root = OpenRoot(mediaOptions.Value.RootPath);
        StagingDirectory? staging;
        switch (root.TryOpenChildDirectory(StagingDirectoryName, out staging))
        {
            case StagingChildOpen.Missing:
                return Finish(Empty(), nowUtc, presentKeys);
            case StagingChildOpen.NotARealDirectory:
                LogPathEscape(logger, "(the staging directory itself)");
                return Finish(Empty(), nowUtc, presentKeys);
        }

        using (staging!)
        {
            var jobs = Scan(staging!, presentKeys, out var scanFailed);
            var rows = await LoadRowsAsync(jobs.Select(job => job.JobId).ToList(), cancellationToken);

            var eligible = new List<EligibleJob>();
            foreach (var job in jobs)
            {
                if (Evaluate(job, rows.GetValueOrDefault(job.JobId), options, nowUtc, presentKeys) is { } unit)
                    eligible.Add(unit);
            }

            // Oldest eligible first; the cap bounds one cycle's work, the remainder is deferred.
            eligible.Sort((left, right) =>
            {
                var byAge = left.ReferenceTimeUtc.CompareTo(right.ReferenceTimeUtc);
                return byAge != 0 ? byAge : StringComparer.Ordinal.Compare(left.Job.Name, right.Job.Name);
            });
            var batch = eligible.Take(options.MaxDirectoriesPerCycle).ToList();
            var remaining = eligible.Skip(batch.Count).ToList();

            int removed = 0, failed = 0;
            long freedBytes = 0;
            foreach (var unit in batch)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (Reclaim(staging!, unit) is { } freed)
                {
                    removed++;
                    freedBytes += freed;
                    state.RecordSuccess(unit.Job.Name);
                }
                else
                {
                    failed++;
                    remaining.Add(unit);
                }
            }

            // Outstanding after this cycle = deferred by the cap + attempted and failed (both
            // are in `remaining`). The drain estimate assumes later attempts succeed.
            var deferred = eligible.Count - batch.Count;
            var backlog = remaining.Count;
            double? oldestAge = remaining.Count == 0
                ? null
                : Math.Max(0, (nowUtc - remaining.Min(unit => unit.ReferenceTimeUtc)).TotalMinutes);
            var backlogState = oldestAge switch
            {
                { } age when age > options.ErrorOldestEligibleMinutes => "critical",
                { } age when age > options.WarnOldestEligibleMinutes => "warning",
                _ => "normal",
            };
            if (backlogState == "critical")
                LogBacklogCritical(logger, oldestAge!.Value, options.ErrorOldestEligibleMinutes);
            else if (backlogState == "warning")
                LogBacklogWarning(logger, oldestAge!.Value, options.WarnOldestEligibleMinutes);

            var result = new StagingJanitorCycleResult(
                jobs.Count,
                eligible.Count,
                batch.Count,
                removed,
                freedBytes,
                failed,
                deferred,
                oldestAge,
                backlog,
                (backlog + options.MaxDirectoriesPerCycle - 1) / options.MaxDirectoriesPerCycle,
                backlogState,
                scanFailed);
            return Finish(result, nowUtc, presentKeys);
        }
    }

    private StagingJanitorCycleResult Finish(StagingJanitorCycleResult result, DateTimeOffset nowUtc, HashSet<string> presentKeys)
    {
        LogCycle(logger, result.Scanned, result.Eligible, result.Processed, result.Removed, result.FreedBytes,
            result.Failed, result.DeferredByCap, result.OldestEligibleAgeMinutes, result.BacklogDepth,
            result.EstimatedCyclesToDrain, result.ScanFailed);
        state.CompleteCycle(result, nowUtc, presentKeys);
        return result;
    }

    private static StagingJanitorCycleResult Empty() => new(0, 0, 0, 0, 0, 0, 0, null, 0, 0, "normal");

    // Scanning
    private sealed record Attempt(string Name, int Number, DateTimeOffset LastWriteTimeUtc);

    private sealed record JobDirectory(string Name, Guid JobId, DateTimeOffset LastWriteTimeUtc, IReadOnlyList<Attempt> Attempts, bool HasOtherEntries);

    private List<JobDirectory> Scan(StagingDirectory staging, HashSet<string> presentKeys, out int scanFailed)
    {
        var jobs = new List<JobDirectory>();
        scanFailed = 0;
        foreach (var entry in staging.ListChildren())
        {
            if (entry.Name is not { } name || !TryParseJobId(name, out var jobId))
            {
                ReportUnrecognised(entry.Name ?? "<non-utf8>", presentKeys);
                continue;
            }

            presentKeys.Add(name);
            presentKeys.Add($"queued:{name}");
            presentKeys.Add($"cancelled:{name}");
            if (!entry.IsRealDirectory)
            {
                ReportPathEscape(name, presentKeys);
                continue;
            }

            try
            {
                if (ScanJob(staging, name, jobId, presentKeys) is { } scanned)
                    jobs.Add(scanned);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // One unreadable job directory must not stop the others being reclaimed. Its
                // eligibility is unknown, so it is reported, escalated and never deleted.
                scanFailed++;
                LogScanFailed(logger, name, exception);
                RecordFailureStreak(name);
            }
        }

        return jobs;
    }

    private JobDirectory? ScanJob(StagingDirectory staging, string name, Guid jobId, HashSet<string> presentKeys)
    {
        switch (staging.TryOpenChildDirectory(name, out var job))
        {
            case StagingChildOpen.Missing:
                return null;
            case StagingChildOpen.NotARealDirectory:
                ReportPathEscape(name, presentKeys);
                return null;
        }

        using (job!)
        {
            var attempts = new List<Attempt>();
            var other = false;
            foreach (var child in job!.ListChildren())
            {
                if (child.Name is { } childName && TryParseAttempt(childName, out var number) && child.IsRealDirectory)
                {
                    attempts.Add(new Attempt(childName, number, child.LastWriteTimeUtc));
                    continue;
                }

                other = true;
                if (child.Name is { } linkName && TryParseAttempt(linkName, out _))
                    ReportPathEscape($"{name}/{linkName}", presentKeys);
                else
                    ReportUnrecognised($"{name}/{child.Name ?? "<non-utf8>"}", presentKeys);
            }

            return new JobDirectory(name, jobId, job.LastWriteTimeUtc, attempts, other);
        }
    }

    /// <summary>1402 once while the link stays present; it is logged again if it reappears.</summary>
    private void ReportPathEscape(string relativeName, HashSet<string> presentKeys)
    {
        var key = $"escape:{relativeName}";
        presentKeys.Add(key);
        if (state.FirstReport(key))
            LogPathEscape(logger, relativeName);
    }

    private void ReportUnrecognised(string relativeName, HashSet<string> presentKeys)
    {
        var key = $"unrecognised:{relativeName}";
        presentKeys.Add(key);
        if (state.FirstReport(key))
            LogUnrecognised(logger, relativeName);
    }

    /// <summary>The job directory name the worker writes: <c>str(uuid)</c>, lower-case "D".</summary>
    internal static bool TryParseJobId(string name, out Guid jobId) =>
        Guid.TryParseExact(name, "D", out jobId) &&
        string.Equals(name, jobId.ToString("D", CultureInfo.InvariantCulture), StringComparison.Ordinal);

    /// <summary>Mirror of the worker's <c>superseded_attempt_number</c> canonical-name rule.</summary>
    internal static bool TryParseAttempt(string name, out int number)
    {
        number = 0;
        const string prefix = "attempt-";
        if (!name.StartsWith(prefix, StringComparison.Ordinal))
            return false;
        var digits = name.AsSpan(prefix.Length);
        if (digits.Length is < 4 or > 10)
            return false;
        foreach (var digit in digits)
        {
            if (digit is < '0' or > '9')
                return false;
        }

        if (!long.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out var value) ||
            value is < 1 or > int.MaxValue ||
            !string.Equals(value.ToString("D4", CultureInfo.InvariantCulture), digits.ToString(), StringComparison.Ordinal))
            return false;
        number = (int)value;
        return true;
    }

    // Authority
    private sealed record JobRow(VisionJobStatus Status, int AttemptCount, DateTimeOffset? CompletedAtUtc);

    private async Task<Dictionary<Guid, JobRow>> LoadRowsAsync(List<Guid> jobIds, CancellationToken cancellationToken)
    {
        var rows = new Dictionary<Guid, JobRow>();
        foreach (var chunk in jobIds.Chunk(RowLookupBatchSize))
        {
            var found = await db.VisionJobs.AsNoTracking()
                .Where(job => chunk.Contains(job.Id))
                .Select(job => new { job.Id, job.Status, job.AttemptCount, job.CompletedAtUtc })
                .ToListAsync(cancellationToken);
            foreach (var row in found)
                rows[row.Id] = new JobRow(row.Status, row.AttemptCount, row.CompletedAtUtc);
        }

        return rows;
    }

    private sealed record EligibleJob(JobDirectory Job, IReadOnlyList<Attempt> Attempts, bool RemoveJobDirectory, DateTimeOffset ReferenceTimeUtc);

    private EligibleJob? Evaluate(JobDirectory job, JobRow? row, StagingJanitorOptions options, DateTimeOffset nowUtc, HashSet<string> presentKeys)
    {
        if (row is null)
        {
            // A job row removed by another lifecycle: reclaim only a directory nobody has touched for a long time.
            if (job.LastWriteTimeUtc > nowUtc - options.UnknownJobGrace)
                return null;
            if (!HasReclaimableContent(job))
                return null;
            LogOrphanReclaimed(logger, job.Name);
            return new EligibleJob(job, job.Attempts, RemoveJobDirectory: true, job.LastWriteTimeUtc);
        }

        switch (row.Status)
        {
            case VisionJobStatus.Completed:
            case VisionJobStatus.Failed:
            case VisionJobStatus.Cancelled:
                if (row.Status == VisionJobStatus.Cancelled && state.FirstReport($"cancelled:{job.Name}"))
                    LogUnexpectedStatus(logger, job.Name, nameof(VisionJobStatus.Cancelled));
                if (row.CompletedAtUtc is not { } terminalUtc)
                {
                    LogInvariantViolation(logger, job.Name, row.Status.ToString(), row.AttemptCount, "terminal without a completion time");
                    return null;
                }

                return nowUtc >= terminalUtc + options.Grace && HasReclaimableContent(job)
                    ? new EligibleJob(job, job.Attempts, RemoveJobDirectory: true, terminalUtc)
                    : null;

            case VisionJobStatus.Leased:
                var superseded = job.Attempts.Where(attempt => attempt.Number < row.AttemptCount).ToList();
                return superseded.Count == 0
                    ? null
                    : new EligibleJob(job, superseded, RemoveJobDirectory: false, superseded.Min(attempt => attempt.LastWriteTimeUtc));

            case VisionJobStatus.Finalizing:
                // The current attempt is the finalizer's input (ADR-006 §7; F3 plan §12): never
                // reclaimable while the job is Finalizing, however long it stays there. Earlier
                // attempts are fenced by the lease authority that superseded them, exactly as
                // for a Leased job. A later attempt directory is unexpected and is preserved
                // and reported like any unrecognised entry. A Finalizing row without an attempt
                // is unreachable in the aggregate: fail closed, delete nothing.
                if (row.AttemptCount < 1)
                {
                    LogInvariantViolation(logger, job.Name, row.Status.ToString(), row.AttemptCount, "finalizing without a worker attempt");
                    return null;
                }

                foreach (var later in job.Attempts.Where(attempt => attempt.Number > row.AttemptCount))
                    ReportUnrecognised($"{job.Name}/{later.Name}", presentKeys);

                var finalized = job.Attempts.Where(attempt => attempt.Number < row.AttemptCount).ToList();
                return finalized.Count == 0
                    ? null
                    : new EligibleJob(job, finalized, RemoveJobDirectory: false, finalized.Min(attempt => attempt.LastWriteTimeUtc));

            case VisionJobStatus.Queued when row.AttemptCount == 0:
                if ((job.Attempts.Count > 0 || job.HasOtherEntries) && state.FirstReport($"queued:{job.Name}"))
                    LogQueuedWithStaging(logger, job.Name);
                return null;

            default:
                LogInvariantViolation(logger, job.Name, row.Status.ToString(), row.AttemptCount, "no reachable transition explains this state");
                return null;
        }
    }

    /// <summary>
    /// Canonical attempts to remove, or an empty job directory. A directory holding only
    /// unrecognised entries is never eligible: those entries are left alone (1401), so it
    /// could never be reclaimed and would otherwise age into a false backlog.
    /// </summary>
    private static bool HasReclaimableContent(JobDirectory job) => job.Attempts.Count > 0 || !job.HasOtherEntries;

    // Reclamation
    /// <summary>Returns the bytes freed, or <see langword="null"/> when the job directory stays because of a failure.</summary>
    private long? Reclaim(StagingDirectory staging, EligibleJob unit)
    {
        var name = unit.Job.Name;
        try
        {
            switch (staging.TryOpenChildDirectory(name, out var job))
            {
                case StagingChildOpen.Missing:
                    // Removed concurrently (the worker's own cleanup): nothing left to reclaim.
                    return 0;
                case StagingChildOpen.NotARealDirectory:
                    LogPathEscape(logger, name);
                    return Failure(name, null);
            }

            long freed = 0;
            using (job!)
            {
                foreach (var attempt in unit.Attempts)
                    freed += job!.RemoveChildTree(attempt.Name) ?? 0;
            }

            if (unit.RemoveJobDirectory)
                _ = staging.TryRemoveEmptyChildDirectory(name);
            return freed;
        }
        catch (StagingPathEscapeException exception)
        {
            LogPathEscape(logger, name, exception);
            return Failure(name, null);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return Failure(name, exception);
        }
    }

    private long? Failure(string name, Exception? exception)
    {
        if (exception is not null)
            LogDeletionFailed(logger, $"{StagingDirectoryName}/{name}", exception);
        RecordFailureStreak(name);
        return null;
    }

    private void RecordFailureStreak(string name)
    {
        var streak = state.RecordFailure(name);
        if (streak >= FailureEscalationCycles)
            LogRepeatedFailure(logger, $"{StagingDirectoryName}/{name}", streak);
    }

    // Observability (EventIds 1400–1409)
    [LoggerMessage(EventId = 1400, EventName = "staging_janitor_cycle", Level = LogLevel.Information,
        Message = "Staging janitor cycle: scanned={Scanned} eligible={Eligible} processed={Processed} removed={Removed} " +
                  "freedBytes={FreedBytes} failed={Failed} deferredByCap={DeferredByCap} " +
                  "oldestEligibleAgeMinutes={OldestEligibleAgeMinutes} backlogDepth={BacklogDepth} " +
                  "estimatedCyclesToDrain={EstimatedCyclesToDrain} scanFailed={ScanFailed}.")]
    private static partial void LogCycle(ILogger logger, int scanned, int eligible, int processed, int removed, long freedBytes,
        int failed, int deferredByCap, double? oldestEligibleAgeMinutes, int backlogDepth, int estimatedCyclesToDrain, int scanFailed);

    [LoggerMessage(EventId = 1401, EventName = "staging_janitor_unrecognised_entry", Level = LogLevel.Information,
        Message = "Staging janitor left an unrecognised entry untouched: staging/{RelativePath}.")]
    private static partial void LogUnrecognised(ILogger logger, string relativePath);

    [LoggerMessage(EventId = 1401, EventName = "staging_janitor_unrecognised_queued_job", Level = LogLevel.Information,
        Message = "Staging janitor preserved staging/{JobId}: the job is queued and has never been leased, so no attempt can own it.")]
    private static partial void LogQueuedWithStaging(ILogger logger, string jobId);

    [LoggerMessage(EventId = 1402, EventName = "staging_janitor_path_escape", Level = LogLevel.Error,
        Message = "Staging janitor refused a path that is not a real directory (link, junction or file) and left it in place: staging/{RelativePath}.")]
    private static partial void LogPathEscape(ILogger logger, string relativePath, Exception? exception = null);

    [LoggerMessage(EventId = 1403, EventName = "staging_janitor_deletion_failed", Level = LogLevel.Warning,
        Message = "Staging janitor could not reclaim {Path}; it stays and is retried next cycle.")]
    private static partial void LogDeletionFailed(ILogger logger, string path, Exception exception);

    [LoggerMessage(EventId = 1403, EventName = "staging_janitor_scan_failed", Level = LogLevel.Warning,
        Message = "Staging janitor could not inspect staging/{JobId}; without its authority nothing in it is deleted. Retried next cycle.")]
    private static partial void LogScanFailed(ILogger logger, string jobId, Exception exception);

    [LoggerMessage(EventId = 1404, EventName = "staging_janitor_repeated_failure", Level = LogLevel.Error,
        Message = "Staging janitor has failed to reclaim {Path} for {Cycles} consecutive cycles.")]
    private static partial void LogRepeatedFailure(ILogger logger, string path, int cycles);

    [LoggerMessage(EventId = 1405, EventName = "staging_janitor_unexpected_status", Level = LogLevel.Warning,
        Message = "Staging janitor found job {JobId} in status {Status}, which no current code path produces; treated as terminal.")]
    private static partial void LogUnexpectedStatus(ILogger logger, string jobId, string status);

    [LoggerMessage(EventId = 1406, EventName = "staging_janitor_invariant_violation", Level = LogLevel.Error,
        Message = "Staging janitor found job {JobId} in status {Status} with AttemptCount {AttemptCount} ({Reason}); nothing was deleted.")]
    private static partial void LogInvariantViolation(ILogger logger, string jobId, string status, int attemptCount, string reason);

    [LoggerMessage(EventId = 1407, EventName = "staging_janitor_backlog_warning", Level = LogLevel.Warning,
        Message = "Staging janitor backlog: the oldest eligible directory is {AgeMinutes} minutes old (warning above {ThresholdMinutes}).")]
    private static partial void LogBacklogWarning(ILogger logger, double ageMinutes, int thresholdMinutes);

    [LoggerMessage(EventId = 1408, EventName = "staging_janitor_backlog_critical", Level = LogLevel.Error,
        Message = "Staging janitor backlog is critical: the oldest eligible directory is {AgeMinutes} minutes old (critical above {ThresholdMinutes}).")]
    private static partial void LogBacklogCritical(ILogger logger, double ageMinutes, int thresholdMinutes);

    [LoggerMessage(EventId = 1409, EventName = "staging_janitor_orphan_job", Level = LogLevel.Warning,
        Message = "Staging janitor is reclaiming job directory {JobId}, which has no VisionJob row and is older than the unknown-job grace.")]
    private static partial void LogOrphanReclaimed(ILogger logger, string jobId);
}
