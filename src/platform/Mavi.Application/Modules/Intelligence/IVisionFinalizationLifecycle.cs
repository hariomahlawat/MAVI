namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// One finalizer's ownership of one Finalizing job, as handed out by <see cref="IVisionFinalizationLifecycle.ClaimNextAsync"/>.
/// The raw claim token lives here and nowhere else: only its hash is persisted, it is never
/// logged, and <see cref="ToString"/> omits it.
/// </summary>
/// <param name="AttemptCount">The worker attempt whose hand-off is being finalized.</param>
/// <param name="FinalizationAttemptCount">This claim's ordinal (first claim = 1).</param>
/// <param name="FinalizationDeadlineUtc">
/// Informational copy of the absolute deadline (F3 plan §5.4) for logging and the executor's
/// scheduling; the aggregate under the row lock is the authority for every write.
/// </param>
public sealed record VisionFinalizationClaim(
    Guid JobId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    int AttemptCount,
    int FinalizationAttemptCount,
    ReadOnlyMemory<byte> ClaimToken,
    DateTimeOffset ClaimExpiresAtUtc,
    DateTimeOffset FinalizationDeadlineUtc,
    string CompletionDigest,
    DateTimeOffset AcceptedAtUtc)
{
    public override string ToString() =>
        $"VisionFinalizationClaim {{ JobId = {JobId}, AttemptCount = {AttemptCount}, FinalizationAttemptCount = {FinalizationAttemptCount}, ClaimExpiresAtUtc = {ClaimExpiresAtUtc:O} }}";
}

/// <summary>The answer to a claim extension (F3 plan §7.2).</summary>
public enum VisionFinalizationClaimStatus
{
    /// <summary>Extended; the claim is live until the new expiry.</summary>
    Live,
    /// <summary>Ownership is intact but the absolute deadline has passed: no further extension is possible.</summary>
    DeadlineReached,
    /// <summary>The claim expired, was rotated away, or the job is no longer Finalizing.</summary>
    Lost,
}

public sealed record VisionFinalizationExtension(VisionFinalizationClaimStatus Status, DateTimeOffset? ClaimExpiresAtUtc);

/// <summary>What the executor needs to revalidate a hand-off, read without any lock (F3 plan §7.3).</summary>
/// <param name="Payload">The retained payload row, or <see langword="null"/> when it is missing.</param>
public sealed record VisionFinalizationInputs(
    Mavi.Domain.Processing.VisionFinalizationPayload? Payload,
    long VideoDurationMs,
    DateTimeOffset RecordingStartUtc);

public enum VisionFinalizationTransitionKind
{
    /// <summary>The graph and completion committed.</summary>
    Published,
    /// <summary>The caller no longer owns the job; nothing was written.</summary>
    Stale,
    /// <summary>The job moved to its terminal failure.</summary>
    Failed,
    /// <summary>A transient error was recorded on the job.</summary>
    Noted,
    /// <summary>The database refused the write before commit; nothing was written. Retry under the claim rules.</summary>
    Retry,
    /// <summary>The commit call failed and whether the database committed is its knowledge alone (F3 plan §10.2).</summary>
    Ambiguous,
}

public sealed record VisionFinalizationTransition(VisionFinalizationTransitionKind Kind, string? Code = null)
{
    public static readonly VisionFinalizationTransition Published = new(VisionFinalizationTransitionKind.Published);
    public static readonly VisionFinalizationTransition Stale = new(VisionFinalizationTransitionKind.Stale);
    public static readonly VisionFinalizationTransition Noted = new(VisionFinalizationTransitionKind.Noted);
    public static readonly VisionFinalizationTransition Ambiguous = new(VisionFinalizationTransitionKind.Ambiguous, VisionFinalizationFailureCodes.PublicationAmbiguous);

    public static VisionFinalizationTransition Failed(string code) => new(VisionFinalizationTransitionKind.Failed, code);

    public static VisionFinalizationTransition Retry(string code) => new(VisionFinalizationTransitionKind.Retry, code);
}

/// <summary>One reconciliation pass (F3 plan §7.5).</summary>
/// <param name="Exhausted">Jobs moved to <c>vision_finalization_exhausted</c>.</param>
/// <param name="MalformedJobIds">Finalizing jobs whose claim metadata is non-canonical; untouched, for the operator.</param>
/// <param name="InvariantJobIds">Jobs whose run or video refused the failed transition; untouched, for the operator.</param>
public sealed record VisionFinalizationReconciliation(int Exhausted, IReadOnlyList<Guid> MalformedJobIds, IReadOnlyList<Guid> InvariantJobIds);

/// <summary>PostgreSQL's answer about Finalizing rows, for health (F3 plan §6.9).</summary>
public sealed record VisionFinalizationCounts(
    int FinalizingJobs,
    int LiveClaims,
    int MalformedClaims,
    DateTimeOffset? OldestFinalizingAcceptedAtUtc);

/// <summary>
/// The transactional half of asynchronous finalization (F3 plan §6.2, §7). Every method opens
/// its own short transaction on freshly read state, takes its row lock explicitly and commits
/// before returning. Nothing here hashes a payload, reads staging or seals; nothing outside
/// here writes a Finalizing job.
/// </summary>
public interface IVisionFinalizationLifecycle
{
    /// <summary>Claims the oldest claimable Finalizing job, or <see langword="null"/>. Commits before returning.</summary>
    Task<VisionFinalizationClaim?> ClaimNextAsync(VisionFinalizationPolicy policy, CancellationToken cancellationToken);

    /// <summary>Renews the claim, or reports that it cannot be renewed.</summary>
    Task<VisionFinalizationExtension> ExtendClaimAsync(VisionFinalizationClaim claim, VisionFinalizationPolicy policy, CancellationToken cancellationToken);

    /// <summary>Reads the retained payload and the video facts without a lock or transaction; <see langword="null"/> when the run or video is missing.</summary>
    Task<VisionFinalizationInputs?> LoadInputsAsync(VisionFinalizationClaim claim, CancellationToken cancellationToken);

    /// <summary>The single publication transaction (F3 plan §7.4).</summary>
    Task<VisionFinalizationTransition> PublishAsync(
        VisionFinalizationClaim claim,
        ValidatedVisionResult result,
        FinalizationGraphPlan graph,
        CancellationToken cancellationToken);

    /// <summary>Claim-fenced deterministic failure of the job, run and video (F3 plan §7.6).</summary>
    Task<VisionFinalizationTransition> FailAsync(VisionFinalizationClaim claim, string code, string? details, CancellationToken cancellationToken);

    /// <summary>Records a transient error under the live claim and optionally releases the claim for the next cycle (F3 plan §7.7).</summary>
    Task<VisionFinalizationTransition> NoteTransientAsync(VisionFinalizationClaim claim, string code, bool releaseClaim, CancellationToken cancellationToken);

    /// <summary>Tokenless, failure-only reconciliation of abandoned jobs; reports malformed rows without touching them (F3 plan §7.5).</summary>
    Task<VisionFinalizationReconciliation> ExhaustAbandonedAsync(VisionFinalizationPolicy policy, int batchSize, CancellationToken cancellationToken);

    /// <summary>Deletes retained payload rows of terminal jobs past the grace, idempotently (F3 plan §7.8).</summary>
    Task<int> CleanUpPayloadsAsync(int batchSize, TimeSpan grace, CancellationToken cancellationToken);

    /// <summary>Counts Finalizing rows from PostgreSQL, without a lock.</summary>
    Task<VisionFinalizationCounts> CountAsync(CancellationToken cancellationToken);
}
