using System.Diagnostics;
using System.Globalization;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Mavi.Infrastructure.Finalization;

/// <summary>How one execution of a claim ended.</summary>
public enum VisionFinalizationExecutionKind
{
    /// <summary>The graph and completion committed.</summary>
    Published,
    /// <summary>A deterministic failure ended the job.</summary>
    Failed,
    /// <summary>A transient error was noted and the claim released; the next cycle may reclaim.</summary>
    Transient,
    /// <summary>Ownership was lost (expired, rotated away or the job left Finalizing); nothing was written.</summary>
    Lost,
    /// <summary>The absolute deadline passed with sealing incomplete; nothing was written and the claim expires naturally.</summary>
    DeadlineReached,
    /// <summary>The host is stopping; nothing was written and the claim expires naturally.</summary>
    Cancelled,
}

/// <summary>What happened to accepted evidence during one execution; never a path or a key.</summary>
public sealed record VisionFinalizationSealingSummary(int Created, long CreatedBytes, int Adopted, long AdoptedBytes, int Total)
{
    public bool SealingComplete => Created + Adopted == Total;
}

public sealed record VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind Kind, string? Code, VisionFinalizationSealingSummary Sealing);

/// <summary>
/// The non-transactional half of asynchronous finalization (F3 plan §6.3–§6.7, §9): payload
/// revalidation, bounded sealing with claim extension between batches, graph construction and
/// the hand-over to the lifecycle's publication transaction, deciding the failure class of
/// everything that goes wrong.
/// </summary>
/// <remarks>
/// <para>
/// It owns no <c>DbContext</c>: every database interaction is one lifecycle call in a scope of
/// its own, so no transaction is ever open while a payload is hashed, staging is read or an
/// object is sealed. Sealed objects are create-once and content-addressed, so a claimant that
/// loses ownership mid-way leaves objects the next claimant adopts; nothing here ever deletes
/// accepted evidence (ADR-006 §7).
/// </para>
/// <para>
/// Logs carry job ids, counts, codes and exception type names. Never a claim token, a lease
/// token, a storage path or an exception message from the filesystem.
/// </para>
/// </remarks>
public sealed partial class VisionFinalizationExecutor(
    IServiceScopeFactory scopeFactory,
    IAcceptedEvidenceStore acceptedEvidence,
    VisionResultValidator validator,
    TimeProvider timeProvider,
    ILogger<VisionFinalizationExecutor> logger)
{
    public async Task<VisionFinalizationExecutionOutcome> ExecuteAsync(
        VisionFinalizationClaim claim,
        VisionFinalizationPolicy policy,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        ArgumentNullException.ThrowIfNull(policy);

        var total = Stopwatch.StartNew();
        // The sealing accounting lives here, outside the core, so that a lifecycle call that
        // throws after sealing began (an extension, the publication's lock) still reports what
        // was created or adopted: orphan and retention accounting stays meaningful on every
        // transient path, not only on the ones the core converts itself (F3 plan §10.9).
        var execution = new ExecutionState(new VisionFinalizationSealingSummary(0, 0, 0, 0, 0));
        try
        {
            return await ExecuteCoreAsync(claim, policy, execution, total, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Host shutdown: write nothing, let the claim expire, reclaim after restart.
            LogCancelled(logger, claim.JobId, claim.FinalizationAttemptCount);
            return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Cancelled, null, execution.Sealing);
        }
        catch (Exception exception) when (IsDatabaseTransient(exception))
        {
            // A lifecycle call itself failed. Note it if the claim can still be proven; if not,
            // the claim expires on its own and reconciliation or a reclaim takes over.
            return await NoteTransientAsync(claim, VisionFinalizationFailureCodes.DbTransient, exception, execution.Sealing, cancellationToken);
        }
    }

    /// <summary>The mutable accounting of one execution, owned by <see cref="ExecuteAsync"/> and updated by the core.</summary>
    private sealed class ExecutionState(VisionFinalizationSealingSummary sealing)
    {
        public VisionFinalizationSealingSummary Sealing { get; set; } = sealing;
    }

    private async Task<VisionFinalizationExecutionOutcome> ExecuteCoreAsync(
        VisionFinalizationClaim claim,
        VisionFinalizationPolicy policy,
        ExecutionState execution,
        Stopwatch total,
        CancellationToken cancellationToken)
    {
        var empty = execution.Sealing;

        // --- Payload integrity (F3 plan §6.4): every check is deterministic. ---
        var inputs = await WithLifecycleAsync(lifecycle => lifecycle.LoadInputsAsync(claim, cancellationToken));
        if (inputs is null || claim.VideoAssetId == Guid.Empty)
            return await FailAsync(claim, VisionFinalizationFailureCodes.ContextInvalid, "run or video missing", empty, cancellationToken);
        var (payloadFailure, result) = Revalidate(claim, inputs);
        if (payloadFailure is not null)
            return await FailAsync(claim, payloadFailure.Value.Code, payloadFailure.Value.Details, empty, cancellationToken);
        if (EvidenceSealingPlan.ExceedsAdmittedCropQuota(result!))
            return await FailAsync(claim, VisionFinalizationFailureCodes.PayloadInvalid, "admitted crop quota exceeded", empty, cancellationToken);

        // --- Sealing in bounded batches (F3 plan §6.5–§6.6). ---
        var units = EvidenceSealingPlan.Build(claim.JobId, result!);
        var accepted = new Dictionary<string, string>(StringComparer.Ordinal);
        var summary = new VisionFinalizationSealingSummary(0, 0, 0, 0, units.Count);
        execution.Sealing = summary;
        var deadlineReached = false;
        var sealWatch = Stopwatch.StartNew();

        // A claim that waited in the host's queue is refreshed, or found lost, before IO begins.
        var initial = await WithLifecycleAsync(lifecycle => lifecycle.ExtendClaimAsync(claim, policy, cancellationToken));
        if (initial.Status == VisionFinalizationClaimStatus.Lost)
            return Lost(claim, "before sealing", summary);
        deadlineReached = initial.Status == VisionFinalizationClaimStatus.DeadlineReached;

        for (var offset = 0; offset < units.Count && !deadlineReached; offset += policy.SealingBatchSize)
        {
            var batch = units.Skip(offset).Take(policy.SealingBatchSize);
            foreach (var unit in batch)
            {
                cancellationToken.ThrowIfCancellationRequested();
                AcceptedEvidenceSealResult sealedResult;
                try
                {
                    sealedResult = await acceptedEvidence.SealAsync(
                        unit.SourceStorageKey, unit.AcceptedStorageKey, unit.ExpectedSizeBytes, unit.ExpectedSha256, cancellationToken);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    return await NoteTransientAsync(claim, VisionFinalizationFailureCodes.IoTransient, exception, summary, cancellationToken);
                }

                var code = sealedResult.Status switch
                {
                    AcceptedEvidenceSealStatus.Sealed => null,
                    AcceptedEvidenceSealStatus.Missing => VisionFinalizationFailureCodes.StagingMissing,
                    AcceptedEvidenceSealStatus.IntegrityMismatch => VisionFinalizationFailureCodes.StagingIntegrityFailed,
                    AcceptedEvidenceSealStatus.DestinationConflict => VisionFinalizationFailureCodes.EvidenceConflict,
                    _ => VisionFinalizationFailureCodes.StagingIntegrityFailed,
                };
                if (code is not null)
                    return await FailAsync(claim, code, $"{unit.Category} unit {unit.TrackIndex}", summary, cancellationToken);

                accepted[unit.SourceStorageKey] = sealedResult.StorageKey ?? unit.AcceptedStorageKey;
                summary = sealedResult.CreatedNew
                    ? summary with { Created = summary.Created + 1, CreatedBytes = summary.CreatedBytes + (sealedResult.SizeBytes ?? unit.ExpectedSizeBytes) }
                    : summary with { Adopted = summary.Adopted + 1, AdoptedBytes = summary.AdoptedBytes + (sealedResult.SizeBytes ?? unit.ExpectedSizeBytes) };
                execution.Sealing = summary;
            }

            // Ownership is revalidated at most one batch apart (F3 plan §6.6).
            var extension = await WithLifecycleAsync(lifecycle => lifecycle.ExtendClaimAsync(claim, policy, cancellationToken));
            switch (extension.Status)
            {
                case VisionFinalizationClaimStatus.Lost:
                    return Lost(claim, "between batches", summary);
                case VisionFinalizationClaimStatus.DeadlineReached:
                    deadlineReached = true;
                    break;
                default:
                    LogExtended(logger, claim.JobId, offset / policy.SealingBatchSize + 1, extension.ClaimExpiresAtUtc);
                    break;
            }
        }

        sealWatch.Stop();
        if (deadlineReached && !summary.SealingComplete)
        {
            // Still live until the granted expiry, but no further batch and no further
            // extension: the claim expires, reconciliation exhausts (F3 plan §6.6, §5.4).
            LogDeadlineReached(logger, claim.JobId, claim.FinalizationAttemptCount, summary.Created + summary.Adopted, summary.Total);
            return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.DeadlineReached, null, summary);
        }

        // --- Graph and publication (F3 plan §6.7, §7.4). ---
        var graph = FinalizationGraphBuilder.Build(
            result!, accepted, claim.ProcessingRunId, claim.VideoAssetId, inputs.RecordingStartUtc, timeProvider.GetUtcNow());
        var publishWatch = Stopwatch.StartNew();
        var transition = await WithLifecycleAsync(lifecycle => lifecycle.PublishAsync(claim, result!, graph, cancellationToken));
        publishWatch.Stop();
        total.Stop();

        switch (transition.Kind)
        {
            case VisionFinalizationTransitionKind.Published:
                if (logger.IsEnabled(LogLevel.Information))
                {
                    var evidence = Evidence(summary);
                    var timings = string.Create(CultureInfo.InvariantCulture,
                        $"seal {sealWatch.Elapsed.TotalMilliseconds:F1} ms, publish {publishWatch.Elapsed.TotalMilliseconds:F1} ms, total {total.Elapsed.TotalMilliseconds:F1} ms, hand-off to publish {(timeProvider.GetUtcNow() - claim.AcceptedAtUtc).TotalSeconds:F1} s");
                    LogPublished(logger, claim.JobId, claim.ProcessingRunId, result!.Tracks.Count, evidence, timings);
                }

                return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Published, null, summary);
            case VisionFinalizationTransitionKind.Stale:
                return Lost(claim, "at publication", summary);
            case VisionFinalizationTransitionKind.Failed:
                return await FailAsync(claim, transition.Code!, "publication context", summary, cancellationToken);
            case VisionFinalizationTransitionKind.Retry:
                return await NoteTransientAsync(claim, transition.Code!, null, summary, cancellationToken);
            default:
                // Ambiguous: PostgreSQL knows. The note is fenced, so on a job that committed it
                // writes nothing; on one that did not, the next claimant adopts and republishes.
                return await NoteTransientAsync(claim, VisionFinalizationFailureCodes.PublicationAmbiguous, null, summary, cancellationToken);
        }
    }

    /// <summary>The eight deterministic payload checks of F3 plan §6.4, in order.</summary>
    private ((string Code, string? Details)? Failure, ValidatedVisionResult? Result) Revalidate(VisionFinalizationClaim claim, VisionFinalizationInputs inputs)
    {
        if (inputs.Payload is not { } payload)
            return ((VisionFinalizationFailureCodes.PayloadMissing, null), null);
        if (payload.PayloadLength != payload.Payload.LongLength ||
            payload.PayloadLength > WorkerContractRules.MaximumCompletionRequestBodyBytes ||
            !payload.Matches(payload.Payload))
            return ((VisionFinalizationFailureCodes.PayloadIntegrityFailed, "length or sha256"), null);

        VisionJobCompleteRequest request;
        try
        {
            request = VisionFinalizationPayloadCodec.Decode(payload.Payload);
        }
        catch (VisionResultValidationException exception)
        {
            return ((VisionFinalizationFailureCodes.PayloadInvalid, exception.ReasonCode), null);
        }

        if (request.JobId != claim.JobId || request.AttemptCount != claim.AttemptCount)
            return ((VisionFinalizationFailureCodes.PayloadInvalid, "job or attempt binding"), null);

        ValidatedVisionResult result;
        try
        {
            result = validator.Validate(claim.JobId, request, inputs.VideoDurationMs);
        }
        catch (VisionResultValidationException exception)
        {
            return ((VisionFinalizationFailureCodes.PayloadInvalid, exception.ReasonCode), null);
        }

        if (!string.Equals(result.CompletionDigest, payload.CompletionDigest, StringComparison.Ordinal) ||
            !string.Equals(result.CompletionDigest, claim.CompletionDigest, StringComparison.Ordinal))
            return ((VisionFinalizationFailureCodes.PayloadIntegrityFailed, "completion digest"), null);
        if (result.Schema != CompletionSchema.V3)
            return ((VisionFinalizationFailureCodes.PayloadInvalid, "schema"), null);
        return (null, result);
    }

    private async Task<VisionFinalizationExecutionOutcome> FailAsync(
        VisionFinalizationClaim claim,
        string code,
        string? details,
        VisionFinalizationSealingSummary sealing,
        CancellationToken cancellationToken)
    {
        var transition = await WithLifecycleAsync(lifecycle => lifecycle.FailAsync(claim, code, details, cancellationToken));
        if (transition.Kind != VisionFinalizationTransitionKind.Failed)
            return Lost(claim, "at failure", sealing);

        LogFailed(logger, claim.JobId, claim.FinalizationAttemptCount, code, details ?? string.Empty);
        if (sealing.Created + sealing.Adopted > 0)
            LogOrphans(logger, claim.JobId, sealing.Created, sealing.CreatedBytes, sealing.Adopted);
        return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Failed, code, sealing);
    }

    private async Task<VisionFinalizationExecutionOutcome> NoteTransientAsync(
        VisionFinalizationClaim claim,
        string code,
        Exception? exception,
        VisionFinalizationSealingSummary sealing,
        CancellationToken cancellationToken)
    {
        VisionFinalizationTransition transition;
        try
        {
            transition = await WithLifecycleAsync(lifecycle => lifecycle.NoteTransientAsync(claim, code, releaseClaim: true, cancellationToken));
        }
        catch (Exception noteException) when (IsDatabaseTransient(noteException))
        {
            // The database is unreachable twice over: the claim expires on its own.
            LogTransient(logger, claim.JobId, claim.FinalizationAttemptCount, code, noteException.GetType().Name + " (not recorded)", Evidence(sealing));
            return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Transient, code, sealing);
        }

        if (transition.Kind == VisionFinalizationTransitionKind.Stale)
            return Lost(claim, "at transient note", sealing);
        LogTransient(logger, claim.JobId, claim.FinalizationAttemptCount, code, exception?.GetType().Name ?? "-", Evidence(sealing));
        return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Transient, code, sealing);
    }

    private static string Evidence(VisionFinalizationSealingSummary sealing) =>
        string.Create(CultureInfo.InvariantCulture,
            $"{sealing.Created} created ({sealing.CreatedBytes} bytes), {sealing.Adopted} adopted ({sealing.AdoptedBytes} bytes) of {sealing.Total}");

    private VisionFinalizationExecutionOutcome Lost(VisionFinalizationClaim claim, string step, VisionFinalizationSealingSummary sealing)
    {
        LogLost(logger, claim.JobId, claim.FinalizationAttemptCount, step);
        return new VisionFinalizationExecutionOutcome(VisionFinalizationExecutionKind.Lost, null, sealing);
    }

    /// <summary>One lifecycle call in a scope of its own: no DbContext outlives a single transaction.</summary>
    private async Task<T> WithLifecycleAsync<T>(Func<IVisionFinalizationLifecycle, Task<T>> action)
    {
        await using var scope = scopeFactory.CreateAsyncScope();
        return await action(scope.ServiceProvider.GetRequiredService<IVisionFinalizationLifecycle>());
    }

    private static bool IsDatabaseTransient(Exception exception) =>
        exception is DbUpdateException or PostgresException or NpgsqlException or TimeoutException;

    // Events 1503–1509, 1512–1513 (F3 plan §14).
    [LoggerMessage(EventId = 1503, EventName = "vision_finalization_claim_extended", Level = LogLevel.Debug,
        Message = "Finalization of job {JobId} extended its claim after batch {Batch}; expires {ExpiresAtUtc}.")]
    private static partial void LogExtended(ILogger logger, Guid jobId, int batch, DateTimeOffset? expiresAtUtc);

    [LoggerMessage(EventId = 1504, EventName = "vision_finalization_published", Level = LogLevel.Information,
        Message = "Finalization of job {JobId} published run {RunId}: {Tracks} tracks; accepted evidence {Evidence}; {Timings}.")]
    private static partial void LogPublished(ILogger logger, Guid jobId, Guid runId, int tracks, string evidence, string timings);

    [LoggerMessage(EventId = 1505, EventName = "vision_finalization_failed", Level = LogLevel.Warning,
        Message = "Finalization of job {JobId} (claim {FinalizationAttempt}) failed deterministically: {Code} {Details}.")]
    private static partial void LogFailed(ILogger logger, Guid jobId, int finalizationAttempt, string code, string details);

    [LoggerMessage(EventId = 1506, EventName = "vision_finalization_transient", Level = LogLevel.Warning,
        Message = "Finalization of job {JobId} (claim {FinalizationAttempt}) hit a transient error {Code} ({ExceptionType}); the claim is released for the next cycle. Accepted evidence so far: {Evidence}.")]
    private static partial void LogTransient(ILogger logger, Guid jobId, int finalizationAttempt, string code, string exceptionType, string evidence);

    [LoggerMessage(EventId = 1507, EventName = "vision_finalization_claim_lost", Level = LogLevel.Warning,
        Message = "Finalization of job {JobId} (claim {FinalizationAttempt}) lost its claim {Step}; nothing was written.")]
    private static partial void LogLost(ILogger logger, Guid jobId, int finalizationAttempt, string step);

    [LoggerMessage(EventId = 1509, EventName = "vision_finalization_orphans", Level = LogLevel.Warning,
        Message = "Finalization of job {JobId} failed after sealing began: {Created} accepted objects created ({CreatedBytes} bytes) and {Adopted} adopted are not referenced by any publication.")]
    private static partial void LogOrphans(ILogger logger, Guid jobId, int created, long createdBytes, int adopted);

    [LoggerMessage(EventId = 1513, EventName = "vision_finalization_deadline_reached", Level = LogLevel.Warning,
        Message = "Finalization of job {JobId} (claim {FinalizationAttempt}) reached the absolute deadline with {SealedObjects} of {Total} objects sealed; no further extension, the claim expires and reconciliation decides.")]
    private static partial void LogDeadlineReached(ILogger logger, Guid jobId, int finalizationAttempt, int sealedObjects, int total);

    [LoggerMessage(EventId = 1514, EventName = "vision_finalization_cancelled", Level = LogLevel.Information,
        Message = "Finalization of job {JobId} (claim {FinalizationAttempt}) stopped for host shutdown; nothing was written.")]
    private static partial void LogCancelled(ILogger logger, Guid jobId, int finalizationAttempt);
}
