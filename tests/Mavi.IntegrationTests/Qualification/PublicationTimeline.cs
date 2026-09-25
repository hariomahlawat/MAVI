using System.Collections.Concurrent;
using System.Data.Common;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.CompilerServices;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.EntityFrameworkCore.Storage;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Test-only instrumentation of the publication transaction (F4 plan §9.2.1, §9.2.2). Three EF
/// interceptors, registered only by the harness, record every command, transaction and
/// SaveChanges event on one monotonic clock (<see cref="Stopwatch.GetTimestamp"/>) with the
/// <see cref="DbTransaction"/> it belongs to; <see cref="Analyze"/> then reconstructs each
/// publication timeline from those raw events. Production code is unchanged.
/// </summary>
/// <remarks>
/// <para>
/// The F3 publication (<c>VisionFinalizationLifecycle.PublishAsync</c>) runs, in one
/// transaction: the job <c>FOR UPDATE</c>; the no-graph check; <c>FinalizationGraphPersistence.AddAsync</c>
/// (graph tracking plus one <c>SaveChanges</c>); the exclusive advisory barrier; the sequence
/// (a raw command, invisible here); the terminal transitions; the final <c>SaveChanges</c>; the
/// commit. The job row lock is <b>not</b> the visibility barrier.
/// </para>
/// <para>
/// Barrier hold = <i>commit completed</i> − <i>barrier acquired</i>: the <c>executed</c> timestamp
/// of the one <c>pg_advisory_xact_lock</c> command whose text is the product's
/// <c>PublicationExclusiveSql</c> (read by reflection, never retyped), because that call returns
/// only once the lock is granted; to <c>TransactionCommitted</c>, which fires after
/// <c>CommitAsync</c> returned from PostgreSQL. Graph persistence = the no-graph check's
/// <c>executed</c> timestamp to the end of AddAsync's own SaveChanges (<c>SavedChanges</c>), the
/// last observable event of AddAsync; the barrier command is strictly after it, and the bracket
/// proof shows nothing else happened in between.
/// </para>
/// </remarks>
internal sealed class PublicationTimelineRecorder
{
    private readonly ConcurrentQueue<TimelineEvent> _events = new();
    private readonly ConditionalWeakTable<DbTransaction, StrongBox<long>> _transactionIds = new();
    private long _nextTransaction;

    public PublicationTimelineRecorder()
    {
        BarrierSql = ReadBarrierSql();
        SharedBarrierSql = ReadConstant("SearchSharedSql");
        Command = new CommandInterceptor(this);
        Transaction = new TransactionInterceptor(this);
        SaveChanges = new SaveChangesInterceptor(this);
    }

    /// <summary>The exclusive completion barrier, as the product defines it.</summary>
    public string BarrierSql { get; }

    /// <summary>The shared search barrier: never a publication.</summary>
    public string SharedBarrierSql { get; }

    public IInterceptor Command { get; }
    public IInterceptor Transaction { get; }
    public IInterceptor SaveChanges { get; }
    public IInterceptor[] All => [Command, Transaction, SaveChanges];

    public IReadOnlyList<TimelineEvent> Events => [.. _events];

    public void Clear() => _events.Clear();

    public static string ReadBarrierSql() => ReadConstant("PublicationExclusiveSql");

    private static string ReadConstant(string name)
    {
        var field = typeof(ProcessingVisibilityBarrier).GetField(name, BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException($"ProcessingVisibilityBarrier.{name} is not found; the barrier cannot be identified.");
        return (string?)field.GetRawConstantValue() ?? throw new InvalidOperationException($"ProcessingVisibilityBarrier.{name} has no value.");
    }

    public static string Normalize(string sql) => string.Join(' ', sql.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    public bool IsBarrier(string? sql) => sql is not null && Normalize(sql) == Normalize(BarrierSql);

    /// <summary>
    /// The transaction an event belongs to. Npgsql reuses one <see cref="DbTransaction"/> object
    /// per pooled connection, so the instance alone would merge successive transactions: every
    /// <c>TransactionStarted</c> opens a new ordinal for its instance, and later events on that
    /// instance belong to it until the next start.
    /// </summary>
    private long? TransactionOrdinal(DbTransaction? transaction, bool starting)
    {
        if (transaction is null) return null;
        var box = _transactionIds.GetValue(transaction, _ => new StrongBox<long>(0));
        if (starting) Interlocked.Exchange(ref box.Value, Interlocked.Increment(ref _nextTransaction));
        return Interlocked.Read(ref box.Value) is var ordinal and > 0 ? ordinal : null;
    }

    private void Add(TimelineEventKind kind, DbTransaction? transaction, Guid? transactionId, Guid? connectionId, Guid? contextId, Guid? commandId, string? sql, object?[]? parameters) =>
        _events.Enqueue(new TimelineEvent(
            kind, Stopwatch.GetTimestamp(), DateTimeOffset.UtcNow, TransactionOrdinal(transaction, kind == TimelineEventKind.TransactionStarted),
            transactionId, connectionId, contextId, commandId, sql, parameters ?? [], PublicationScope.Current));

    private void AddCommand(TimelineEventKind kind, DbCommand command, CommandEventData data) =>
        Add(kind, command.Transaction, null, data.ConnectionId, data.Context?.ContextId.InstanceId, data.CommandId, command.CommandText,
            [.. command.Parameters.Cast<DbParameter>().Select(p => p.Value)]);

    private void AddSave(TimelineEventKind kind, DbContextEventData data) =>
        Add(kind, data.Context?.Database.CurrentTransaction?.GetDbTransaction(), data.Context?.Database.CurrentTransaction?.TransactionId, null,
            data.Context?.ContextId.InstanceId, null, null, null);

    // -- analysis ---------------------------------------------------------------------------

    /// <summary>
    /// Every transaction that took the exclusive barrier, reconstructed. <paramref name="jobId"/>
    /// restricts to transactions whose row lock names that job; <paramref name="scopedOnly"/>
    /// to transactions started inside a <see cref="PublicationScope"/> (the finalizer's
    /// PublishAsync); the synchronous reference path has none.
    /// </summary>
    public IReadOnlyList<PublicationTimeline> Analyze(Guid? jobId = null, bool scopedOnly = true)
    {
        var events = Events;
        var byTransaction = events.Where(e => e.Transaction is not null).GroupBy(e => e.Transaction!.Value);
        var timelines = new List<PublicationTimeline>();
        foreach (var group in byTransaction)
        {
            var ordered = group.OrderBy(e => e.Ticks).ToList();
            var barriers = ordered.Where(e => e.Kind == TimelineEventKind.CommandExecuted && IsBarrier(e.Sql)).ToList();
            if (barriers.Count == 0) continue;
            if (scopedOnly && ordered.All(e => e.Scope is null)) continue;
            var timeline = Build(ordered, barriers);
            if (jobId is { } job && timeline.JobId != job) continue;
            timelines.Add(timeline);
        }

        return [.. timelines.OrderBy(t => t.Ticks.GetValueOrDefault("transactionBegun"))];
    }

    private static PublicationTimeline Build(List<TimelineEvent> ordered, List<TimelineEvent> barriers)
    {
        var problems = new List<string>();
        var ticks = new Dictionary<string, long>(StringComparer.Ordinal);
        TimelineEvent? First(Func<TimelineEvent, bool> predicate) => ordered.FirstOrDefault(predicate);
        void Put(string name, TimelineEvent? e)
        {
            if (e is null) problems.Add($"{name} was not observed");
            else ticks[name] = e.Ticks;
        }

        var started = First(e => e.Kind == TimelineEventKind.TransactionStarted);
        Put("transactionBegun", started);
        var rowLock = First(e => e.Kind == TimelineEventKind.CommandExecuted && e.Sql is { } s
            && s.Contains("vision_jobs", StringComparison.Ordinal) && s.Contains("FOR UPDATE", StringComparison.Ordinal));
        Put("rowLockAcquired", rowLock);
        var jobId = rowLock?.Parameters.OfType<Guid>().FirstOrDefault();

        var graphSaving = First(e => e.Kind == TimelineEventKind.SavingChanges);
        var graphSaved = graphSaving is null ? null : First(e => e.Kind == TimelineEventKind.SavedChanges && e.Ticks >= graphSaving.Ticks);
        Put("graphSavingChanges", graphSaving);
        Put("graphSavedChanges", graphSaved);
        // The no-graph check: the last command completed before AddAsync's SaveChanges began.
        var beforeGraph = graphSaving is null ? null : ordered.LastOrDefault(e => e.Kind == TimelineEventKind.CommandExecuted && e.Ticks < graphSaving.Ticks);
        var noGraphCheck = beforeGraph?.Sql is { } check && check.Contains("tracks", StringComparison.Ordinal) && check.Contains("EXISTS", StringComparison.OrdinalIgnoreCase);
        Put("graphPersistenceStart", noGraphCheck ? beforeGraph : graphSaving);
        Put("graphPersistenceEnd", graphSaved);

        var barrier = barriers[0];
        var barrierStarted = ordered.LastOrDefault(e => e.Kind == TimelineEventKind.CommandExecuting && e.CommandId == barrier.CommandId);
        Put("barrierCommandStarted", barrierStarted);
        Put("barrierAcquired", barrier);
        var committing = First(e => e.Kind == TimelineEventKind.TransactionCommitting);
        var committed = First(e => e.Kind == TimelineEventKind.TransactionCommitted);
        Put("commitStarted", committing);
        Put("commitCompleted", committed);
        var rolledBack = ordered.Any(e => e.Kind is TimelineEventKind.TransactionRolledBack or TimelineEventKind.TransactionFailed or TimelineEventKind.SaveChangesFailed or TimelineEventKind.CommandFailed);

        // Bracket proof: between the no-graph check and the barrier command, the only events
        // are AddAsync's single SaveChanges and the commands it issued.
        var graphBracketOnly = graphSaving is not null && graphSaved is not null && beforeGraph is not null && barrierStarted is not null
            && noGraphCheck
            && ordered.Where(e => e.Ticks > beforeGraph.Ticks && e.Ticks < barrierStarted.Ticks)
                .All(e => e.Ticks >= graphSaving.Ticks && e.Ticks <= graphSaved.Ticks)
            && ordered.Count(e => e.Kind == TimelineEventKind.SavingChanges && e.Ticks < barrierStarted.Ticks) == 1;

        var timeline = new PublicationTimeline
        {
            JobId = jobId,
            TransactionOrdinal = barrier.Transaction!.Value,
            TransactionId = started?.TransactionId?.ToString("N") ?? committed?.TransactionId?.ToString("N"),
            ConnectionId = (started?.ConnectionId ?? rowLock?.ConnectionId)?.ToString("N"),
            BarrierCommandText = barrier.Sql!,
            Committed = committed is not null && !rolledBack,
            CommitCompletedUtc = committed?.Utc,
            Scope = ordered.Select(e => e.Scope).FirstOrDefault(s => s is not null),
            Ticks = ticks,
            SingleBarrierCommand = barriers.Count == 1,
            GraphPersistenceBracketContainsOnlyAddAsync = graphBracketOnly,
            // Commands on other connections (the API prober, the health loop) never belong here.
            LongestCommandMs = ordered.Where(e => e.Kind == TimelineEventKind.CommandExecuted)
                .Select(e => S1QualificationSupport.TicksMs(ordered.LastOrDefault(s => s.Kind == TimelineEventKind.CommandExecuting && s.CommandId == e.CommandId)?.Ticks ?? e.Ticks, e.Ticks))
                .DefaultIfEmpty(0).Max(),
            Problems = problems,
        };
        if (!timeline.Committed) timeline.Problems.Add("the transaction did not commit");
        return timeline;
    }

    // -- interceptors -----------------------------------------------------------------------

    private sealed class CommandInterceptor(PublicationTimelineRecorder recorder) : DbCommandInterceptor
    {
        public override InterceptionResult<DbDataReader> ReaderExecuting(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuting, command, eventData);
            return result;
        }

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuting, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override DbDataReader ReaderExecuted(DbCommand command, CommandExecutedEventData eventData, DbDataReader result)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuted, command, eventData);
            return result;
        }

        public override ValueTask<DbDataReader> ReaderExecutedAsync(DbCommand command, CommandExecutedEventData eventData, DbDataReader result, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuted, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override ValueTask<InterceptionResult<int>> NonQueryExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuting, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override InterceptionResult<int> NonQueryExecuting(DbCommand command, CommandEventData eventData, InterceptionResult<int> result)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuting, command, eventData);
            return result;
        }

        public override ValueTask<int> NonQueryExecutedAsync(DbCommand command, CommandExecutedEventData eventData, int result, CancellationToken cancellationToken = default)
        {
            // pg_advisory_xact_lock returns only once the lock is granted: this is "acquired".
            recorder.AddCommand(TimelineEventKind.CommandExecuted, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override int NonQueryExecuted(DbCommand command, CommandExecutedEventData eventData, int result)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuted, command, eventData);
            return result;
        }

        public override ValueTask<InterceptionResult<object>> ScalarExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<object> result, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuting, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override ValueTask<object?> ScalarExecutedAsync(DbCommand command, CommandExecutedEventData eventData, object? result, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandExecuted, command, eventData);
            return ValueTask.FromResult(result);
        }

        public override Task CommandFailedAsync(DbCommand command, CommandErrorEventData eventData, CancellationToken cancellationToken = default)
        {
            recorder.AddCommand(TimelineEventKind.CommandFailed, command, eventData);
            return Task.CompletedTask;
        }

        public override void CommandFailed(DbCommand command, CommandErrorEventData eventData) =>
            recorder.AddCommand(TimelineEventKind.CommandFailed, command, eventData);
    }

    private sealed class TransactionInterceptor(PublicationTimelineRecorder recorder) : DbTransactionInterceptor
    {
        public override ValueTask<DbTransaction> TransactionStartedAsync(DbConnection connection, TransactionEndEventData eventData, DbTransaction result, CancellationToken cancellationToken = default)
        {
            recorder.Add(TimelineEventKind.TransactionStarted, result, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return ValueTask.FromResult(result);
        }

        public override DbTransaction TransactionStarted(DbConnection connection, TransactionEndEventData eventData, DbTransaction result)
        {
            recorder.Add(TimelineEventKind.TransactionStarted, result, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return result;
        }

        public override ValueTask<InterceptionResult> TransactionCommittingAsync(DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            recorder.Add(TimelineEventKind.TransactionCommitting, transaction, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return ValueTask.FromResult(result);
        }

        public override Task TransactionCommittedAsync(DbTransaction transaction, TransactionEndEventData eventData, CancellationToken cancellationToken = default)
        {
            // Fires only after DbTransaction.CommitAsync returned: PostgreSQL acknowledged COMMIT.
            recorder.Add(TimelineEventKind.TransactionCommitted, transaction, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return Task.CompletedTask;
        }

        public override Task TransactionRolledBackAsync(DbTransaction transaction, TransactionEndEventData eventData, CancellationToken cancellationToken = default)
        {
            recorder.Add(TimelineEventKind.TransactionRolledBack, transaction, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return Task.CompletedTask;
        }

        public override Task TransactionFailedAsync(DbTransaction transaction, TransactionErrorEventData eventData, CancellationToken cancellationToken = default)
        {
            recorder.Add(TimelineEventKind.TransactionFailed, transaction, eventData.TransactionId, eventData.ConnectionId, eventData.Context?.ContextId.InstanceId, null, null, null);
            return Task.CompletedTask;
        }
    }

    private sealed class SaveChangesInterceptor(PublicationTimelineRecorder recorder) : Microsoft.EntityFrameworkCore.Diagnostics.SaveChangesInterceptor
    {
        public override ValueTask<InterceptionResult<int>> SavingChangesAsync(DbContextEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            recorder.AddSave(TimelineEventKind.SavingChanges, eventData);
            return ValueTask.FromResult(result);
        }

        public override ValueTask<int> SavedChangesAsync(SaveChangesCompletedEventData eventData, int result, CancellationToken cancellationToken = default)
        {
            recorder.AddSave(TimelineEventKind.SavedChanges, eventData);
            return ValueTask.FromResult(result);
        }

        public override Task SaveChangesFailedAsync(DbContextErrorEventData eventData, CancellationToken cancellationToken = default)
        {
            recorder.AddSave(TimelineEventKind.SaveChangesFailed, eventData);
            return Task.CompletedTask;
        }
    }
}

internal enum TimelineEventKind
{
    CommandExecuting,
    CommandExecuted,
    CommandFailed,
    TransactionStarted,
    TransactionCommitting,
    TransactionCommitted,
    TransactionRolledBack,
    TransactionFailed,
    SavingChanges,
    SavedChanges,
    SaveChangesFailed,
}

internal sealed record TimelineEvent(
    TimelineEventKind Kind,
    long Ticks,
    DateTimeOffset Utc,
    long? Transaction,
    Guid? TransactionId,
    Guid? ConnectionId,
    Guid? ContextId,
    Guid? CommandId,
    string? Sql,
    object?[] Parameters,
    long? Scope);

/// <summary>One reconstructed publication transaction, with its raw timestamps.</summary>
internal sealed class PublicationTimeline
{
    public Guid? JobId { get; init; }
    public long TransactionOrdinal { get; init; }
    public string? TransactionId { get; init; }
    public string? ConnectionId { get; init; }
    public required string BarrierCommandText { get; init; }
    public bool Committed { get; init; }
    public DateTimeOffset? CommitCompletedUtc { get; init; }
    public long? Scope { get; init; }
    public required Dictionary<string, long> Ticks { get; init; }
    public bool SingleBarrierCommand { get; init; }
    public bool GraphPersistenceBracketContainsOnlyAddAsync { get; init; }
    public double LongestCommandMs { get; init; }
    public required List<string> Problems { get; init; }

    /// <summary>The invariant of F4 plan §9.2.1, as the checker recomputes it.</summary>
    public IReadOnlyList<string> OrderingProblems()
    {
        var problems = new List<string>(Problems);
        string[] order = ["rowLockAcquired", "graphPersistenceStart", "graphPersistenceEnd", "barrierCommandStarted", "barrierAcquired", "commitCompleted"];
        bool[] strict = [true, false, true, false, true];
        for (var i = 0; i < strict.Length; i++)
        {
            if (!Ticks.TryGetValue(order[i], out var a) || !Ticks.TryGetValue(order[i + 1], out var b)) continue;
            if (strict[i] ? a >= b : a > b)
                problems.Add($"ordering violated: {order[i]} {(strict[i] ? "<" : "<=")} {order[i + 1]}");
        }

        if (Ticks.TryGetValue("commitStarted", out var cs) && Ticks.TryGetValue("commitCompleted", out var cc) && cs >= cc)
            problems.Add("ordering violated: commitStarted < commitCompleted");
        return problems;
    }

    public double Ms(string from, string to) => S1QualificationSupport.TicksMs(Ticks[from], Ticks[to]);

    public double BarrierHoldMs => Ms("barrierAcquired", "commitCompleted");
    public double BarrierWaitMs => Ms("barrierCommandStarted", "barrierAcquired");
    public double PublishTransactionMs => Ms("transactionBegun", "commitCompleted");
    public double GraphPersistenceMs => Ms("graphPersistenceStart", "graphPersistenceEnd");
    public double GraphSaveChangesMs => Ms("graphSavingChanges", "graphSavedChanges");
    public double RowLockToCommitMs => Ms("rowLockAcquired", "commitCompleted");

    /// <summary>The retained form: raw ticks and the frequency, never only derived values.</summary>
    public object ToOutput(string transition) => new
    {
        stopwatchFrequency = Stopwatch.Frequency,
        ticks = Ticks,
        transactionId = TransactionId,
        connectionId = ConnectionId,
        barrierCommandText = BarrierCommandText,
        transition,
        committed = Committed,
        commitCompletedUtc = CommitCompletedUtc?.ToString("O", System.Globalization.CultureInfo.InvariantCulture),
    };
}

/// <summary>
/// Marks the async flow of one <c>PublishAsync</c> call, so its transaction's events can be told
/// from every other transaction in the process (the API prober, the health loop, other jobs).
/// </summary>
internal static class PublicationScope
{
    private static readonly AsyncLocal<long?> CurrentScope = new();
    private static long _next;

    public static long? Current => CurrentScope.Value;

    public static long Enter()
    {
        var id = Interlocked.Increment(ref _next);
        CurrentScope.Value = id;
        return id;
    }

    public static void Exit() => CurrentScope.Value = null;
}
