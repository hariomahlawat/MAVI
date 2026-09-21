using System.Security.Cryptography;
using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// One analysis unit: a processing run evaluated against one scene revision by one
/// algorithm version (ADR-011 decision 3). It is the unit of scheduling, retry,
/// ownership, visibility and re-analysis.
/// </summary>
/// <remarks>
/// <para>
/// The identity triple (<see cref="ProcessingRunId"/>, <see cref="RevisionId"/>,
/// <see cref="AlgorithmVersion"/>) is unique in the database. Nothing here creates a
/// second unit for the same triple: re-analysis of an existing identity is idempotent
/// and an explicit retry reuses this row.
/// </para>
/// <para>
/// <b>Fencing.</b> Analytics run outside any transaction, so an attempt can outlive
/// its claim. Ownership is the pair (<see cref="AttemptCount"/>, claim token) recorded
/// on the row, and <see cref="RequireOwnership"/> is the single guard — completion and
/// failure both call it, inside the final transaction, after the row lock and before
/// the first write.
/// </para>
/// <para>
/// <b>Lease expiry is not ownership loss</b> (ADR-011 decision 4). This is the one
/// place this aggregate deliberately diverges from <c>VisionJob</c>, whose
/// <c>RequireValidLease</c> does treat an expired lease as invalid. Here an expired
/// lease means only <i>reclaimable</i>: ownership is lost when the row changes hands,
/// in <see cref="Reclaim"/> or <see cref="Exhaust"/>, and never merely because a clock
/// passed a boundary. An attempt that overruns and then finishes still completes, which
/// is the point — correct work is not discarded for a margin.
/// </para>
/// </remarks>
public sealed class SceneAnalysis
{
    /// <summary>Claim tokens are 32 random bytes; only the SHA-256 of one is ever stored.</summary>
    public const int ClaimTokenByteLength = 32;

    private const int Sha256ByteLength = 32;

    private SceneAnalysis() { }

    /// <summary>Creates a queued unit for one identity triple.</summary>
    public static SceneAnalysis Queue(
        Guid processingRunId,
        Guid revisionId,
        string algorithmVersion,
        string parametersSha256,
        string? sourceCommit,
        DateTimeOffset nowUtc)
    {
        if (processingRunId == Guid.Empty || revisionId == Guid.Empty) throw Invalid();
        if (string.IsNullOrWhiteSpace(algorithmVersion) || algorithmVersion.Trim().Length > 64) throw Invalid();
        if (!IsCanonicalSha256(parametersSha256)) throw Invalid();
        if (sourceCommit is { Length: > 64 }) throw Invalid();

        return new SceneAnalysis
        {
            Id = Guid.CreateVersion7(),
            ProcessingRunId = processingRunId,
            RevisionId = revisionId,
            AlgorithmVersion = algorithmVersion.Trim(),
            ParametersSha256 = parametersSha256,
            SourceCommit = sourceCommit,
            Status = SceneAnalysisStatus.Queued,
            AttemptCount = 0,
            QueuedAtUtc = nowUtc.ToUniversalTime()
        };
    }

    // --- Claiming ----------------------------------------------------------

    /// <summary>
    /// Whether this unit may be claimed now: queued, or running with a lease that has
    /// expired past the reclaim grace, and with automatic attempts remaining.
    /// </summary>
    /// <remarks>
    /// The grace is what stops the last permitted attempt being killed the instant it
    /// overruns. It applies to reclaim and to exhaustion alike, so both give a slow
    /// attempt the same chance to finish first.
    /// </remarks>
    public bool CanClaim(DateTimeOffset nowUtc, int maximumAttempts, TimeSpan reclaimGrace)
    {
        if (maximumAttempts < 1 || AttemptCount >= maximumAttempts) return false;
        var now = nowUtc.ToUniversalTime();
        return Status switch
        {
            SceneAnalysisStatus.Queued => true,
            SceneAnalysisStatus.Running => IsReclaimable(now, reclaimGrace),
            _ => false
        };
    }

    /// <summary>
    /// Takes ownership: a new attempt number, a fresh token hash and a new lease.
    /// Used for a first claim and for a reclaim alike — they are one transition, because
    /// making them two implementations is how the two drift apart.
    /// </summary>
    public void Claim(
        byte[] claimTokenHash,
        DateTimeOffset nowUtc,
        TimeSpan leaseDuration,
        int maximumAttempts,
        TimeSpan reclaimGrace)
    {
        if (!CanClaim(nowUtc, maximumAttempts, reclaimGrace)) throw Invalid();
        if (claimTokenHash is not { Length: Sha256ByteLength }) throw Invalid();
        if (leaseDuration <= TimeSpan.Zero) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        Status = SceneAnalysisStatus.Running;
        AttemptCount++;
        ClaimTokenHash = [.. claimTokenHash];
        LeaseExpiresAtUtc = now.Add(leaseDuration);
        StartedAtUtc ??= now;
        FailureCode = null;
        FailureDetails = null;
    }

    /// <summary>Reclaim is a claim of a running unit; kept as a name for the caller's intent.</summary>
    public void Reclaim(
        byte[] claimTokenHash,
        DateTimeOffset nowUtc,
        TimeSpan leaseDuration,
        int maximumAttempts,
        TimeSpan reclaimGrace)
    {
        if (Status != SceneAnalysisStatus.Running) throw Invalid();
        Claim(claimTokenHash, nowUtc, leaseDuration, maximumAttempts, reclaimGrace);
    }

    // --- Ownership ---------------------------------------------------------

    /// <summary>
    /// Whether the caller still owns this unit: it is running, the attempt matches and
    /// the token hashes to the stored value.
    /// </summary>
    /// <remarks>
    /// <para>
    /// All three are required, and the token is the one that cannot be guessed. That
    /// matters because <see cref="Retry"/> resets <see cref="AttemptCount"/> to zero, so
    /// across a retry boundary a stale attempt's number can legitimately collide with
    /// the current one. Reducing this check to an attempt comparison would let that
    /// stale attempt through.
    /// </para>
    /// <para>
    /// The lease clock is deliberately absent — see the type's remarks.
    /// </para>
    /// </remarks>
    public bool OwnedBy(int attemptCount, ReadOnlySpan<byte> claimToken)
    {
        if (Status != SceneAnalysisStatus.Running) return false;
        if (attemptCount != AttemptCount) return false;
        if (ClaimTokenHash is not { Length: Sha256ByteLength }) return false;
        if (claimToken.Length != ClaimTokenByteLength) return false;

        Span<byte> actual = stackalloc byte[Sha256ByteLength];
        SHA256.HashData(claimToken, actual);
        return CryptographicOperations.FixedTimeEquals(actual, ClaimTokenHash);
    }

    /// <summary>Throws <see cref="SceneAnalysisStaleAttemptException"/> unless the caller still owns the unit.</summary>
    public void RequireOwnership(int attemptCount, ReadOnlySpan<byte> claimToken)
    {
        if (!OwnedBy(attemptCount, claimToken))
        {
            throw new SceneAnalysisStaleAttemptException(Id, attemptCount);
        }
    }

    // --- Terminal transitions (owner only) ---------------------------------

    /// <summary>
    /// Marks the unit successful. The caller must already have written its facts and
    /// allocated <paramref name="visibilitySequence"/> in the same transaction, so that
    /// the unit and its facts become observable together.
    /// </summary>
    public void Complete(
        int attemptCount,
        ReadOnlySpan<byte> claimToken,
        long visibilitySequence,
        int analysedTrackCount,
        int unavailableTrackCount,
        DateTimeOffset nowUtc)
    {
        RequireOwnership(attemptCount, claimToken);
        if (visibilitySequence <= 0) throw Invalid();
        if (analysedTrackCount < 0 || unavailableTrackCount < 0) throw Invalid();

        Status = SceneAnalysisStatus.Completed;
        VisibilitySequence = visibilitySequence;
        AnalysedTrackCount = analysedTrackCount;
        UnavailableTrackCount = unavailableTrackCount;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        ClaimTokenHash = null;
        LeaseExpiresAtUtc = null;
        FailureCode = null;
        FailureDetails = null;
    }

    /// <summary>
    /// Records an attempt failure. While automatic attempts remain the unit returns to
    /// <see cref="SceneAnalysisStatus.Queued"/> for re-claim; otherwise it fails.
    /// </summary>
    public void FailAttempt(
        int attemptCount,
        ReadOnlySpan<byte> claimToken,
        string failureCode,
        string? failureDetails,
        int maximumAttempts,
        DateTimeOffset nowUtc)
    {
        RequireOwnership(attemptCount, claimToken);
        if (string.IsNullOrWhiteSpace(failureCode) || failureCode.Length > 64) throw Invalid();
        if (failureDetails is { Length: > 4000 }) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        FailureCode = failureCode;
        FailureDetails = failureDetails;
        ClaimTokenHash = null;
        LeaseExpiresAtUtc = null;

        if (AttemptCount < maximumAttempts)
        {
            // Another automatic attempt is allowed: back to the queue, and the failure
            // code stays visible until that attempt supersedes it.
            Status = SceneAnalysisStatus.Queued;
            QueuedAtUtc = now;
            return;
        }

        Status = SceneAnalysisStatus.Failed;
        CompletedAtUtc = now;
    }

    /// <summary>
    /// Terminal exhaustion, taken by the reconciler on a unit it holds under a row lock
    /// once the lease and its grace have passed. Clearing the token hash is what makes
    /// the overrunning attempt stale, exactly as a reclaim would.
    /// </summary>
    public void Exhaust(DateTimeOffset nowUtc, TimeSpan reclaimGrace)
    {
        var now = nowUtc.ToUniversalTime();
        if (Status != SceneAnalysisStatus.Running || !IsReclaimable(now, reclaimGrace)) throw Invalid();

        Status = SceneAnalysisStatus.Failed;
        FailureCode = SceneAnalyticsErrorCodes.AttemptsExhausted;
        FailureDetails = null;
        ClaimTokenHash = null;
        LeaseExpiresAtUtc = null;
        CompletedAtUtc = now;
    }

    // --- Operator transitions ----------------------------------------------

    /// <summary>
    /// Explicit operator retry: a <b>new retry cycle</b> on this same unit.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <see cref="AttemptCount"/> bounds the automatic attempts within one cycle; it is
    /// not a lifetime counter. Resetting it is what makes a unit that exhausted its
    /// attempts retryable without inventing a second unit for an identity that is unique
    /// by construction.
    /// </para>
    /// <para>
    /// <see cref="QueuedAtUtc"/>, <see cref="StartedAtUtc"/> and
    /// <see cref="CompletedAtUtc"/> describe the current cycle and are reset with it.
    /// Nothing is lost: retry is legal only from <see cref="SceneAnalysisStatus.Failed"/>,
    /// where the unit never completed, and the per-attempt record lives in the logs.
    /// </para>
    /// <para>
    /// <b>No facts are deleted here.</b> A unit's own facts are replaced only inside a
    /// later successful commit, after ownership has been revalidated.
    /// </para>
    /// </remarks>
    public void Retry(DateTimeOffset nowUtc)
    {
        if (Status != SceneAnalysisStatus.Failed) throw Invalid();

        Status = SceneAnalysisStatus.Queued;
        AttemptCount = 0;
        ClaimTokenHash = null;
        LeaseExpiresAtUtc = null;
        FailureCode = null;
        FailureDetails = null;
        QueuedAtUtc = nowUtc.ToUniversalTime();
        StartedAtUtc = null;
        CompletedAtUtc = null;
    }

    /// <summary>
    /// Marks this successful unit historical after a later analysis of the same run
    /// succeeded for a different identity.
    /// </summary>
    /// <remarks>
    /// Only the facts' currency changes. The facts themselves, the counts, the timestamps
    /// and <see cref="VisibilitySequence"/> are untouched, because a query that pinned
    /// this identity must keep reading exactly what it read before.
    /// </remarks>
    public void Supersede()
    {
        if (Status != SceneAnalysisStatus.Completed) throw Invalid();
        Status = SceneAnalysisStatus.Superseded;
    }

    // --- State -------------------------------------------------------------

    public Guid Id { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public Guid RevisionId { get; private set; }
    public string AlgorithmVersion { get; private set; } = string.Empty;
    public string ParametersSha256 { get; private set; } = string.Empty;
    public string? SourceCommit { get; private set; }
    public SceneAnalysisStatus Status { get; private set; }
    public int AttemptCount { get; private set; }
    public byte[]? ClaimTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public DateTimeOffset QueuedAtUtc { get; private set; }
    public DateTimeOffset? StartedAtUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public long? VisibilitySequence { get; private set; }
    public int AnalysedTrackCount { get; private set; }
    public int UnavailableTrackCount { get; private set; }
    public string? FailureCode { get; private set; }
    public string? FailureDetails { get; private set; }

    /// <summary>
    /// True for the states that carry committed facts. Both successful states qualify:
    /// currency is not validity.
    /// </summary>
    public bool IsFactBearing =>
        Status is SceneAnalysisStatus.Completed or SceneAnalysisStatus.Superseded;

    private bool IsReclaimable(DateTimeOffset nowUtc, TimeSpan reclaimGrace) =>
        LeaseExpiresAtUtc is { } expiry && nowUtc > expiry.Add(reclaimGrace);

    private static bool IsCanonicalSha256(string value) =>
        value is { Length: 64 } && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The scene analysis operation is invalid.");
}
