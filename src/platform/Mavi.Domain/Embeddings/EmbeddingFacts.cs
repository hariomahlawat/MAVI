using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Embeddings;

/// <summary>
/// When an embedding identity became the preferred one. Automatic queueing covers runs completed after the
/// latest activation; history is queued only by an explicit, bounded request (ADR-021 §3; ADR-013 §9).
/// </summary>
public sealed class EmbeddingIdentityActivation
{
    private EmbeddingIdentityActivation() { }

    public static EmbeddingIdentityActivation Create(string fingerprint, string canonicalIdentity, DateTimeOffset activatedAtUtc)
    {
        if (!CanonicalSha256.IsCanonical(fingerprint) || string.IsNullOrWhiteSpace(canonicalIdentity))
            throw new DomainValidationException(EmbeddingAnalysis.TransitionInvalidCode, "The embedding activation is invalid.");
        return new EmbeddingIdentityActivation
        {
            Id = Guid.CreateVersion7(),
            Fingerprint = fingerprint,
            CanonicalIdentity = canonicalIdentity,
            ActivatedAtUtc = activatedAtUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public string Fingerprint { get; private set; } = string.Empty;
    public string CanonicalIdentity { get; private set; } = string.Empty;
    public DateTimeOffset ActivatedAtUtc { get; private set; }
}

public enum AppearanceQueryStatus
{
    Pending,
    Running,
    Completed,
    Failed,
}

/// <summary>
/// One appearance text's vector under one embedding identity (ADR-021 §4): requested by the API, filled by the
/// <c>embeddings</c> role through a short lease, then immutable and reused by every later query of the same text.
/// </summary>
public sealed class AppearanceQueryEmbedding
{
    public const int MaximumAttempts = 3;
    public const string NotFoundCode = "embedding_text_query_not_found";

    private AppearanceQueryEmbedding() { }

    public static AppearanceQueryEmbedding Request(string identityFingerprint, string normalisedText, string textSha256, DateTimeOffset nowUtc)
    {
        if (!CanonicalSha256.IsCanonical(identityFingerprint) || !CanonicalSha256.IsCanonical(textSha256) ||
            normalisedText is not { Length: >= 1 and <= 200 })
            throw Invalid();
        return new AppearanceQueryEmbedding
        {
            Id = Guid.CreateVersion7(),
            IdentityFingerprint = identityFingerprint,
            Text = normalisedText,
            TextSha256 = textSha256,
            Status = AppearanceQueryStatus.Pending,
            RequestedAtUtc = nowUtc.ToUniversalTime(),
        };
    }

    public bool CanClaim(DateTimeOffset nowUtc) =>
        AttemptCount < MaximumAttempts &&
        (Status == AppearanceQueryStatus.Pending ||
         (Status == AppearanceQueryStatus.Running && LeaseExpiresAtUtc is { } expiry && expiry <= nowUtc.ToUniversalTime()));

    public void Claim(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, TimeSpan leaseDuration)
    {
        if (!CanClaim(nowUtc) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: EmbeddingAnalysis.LeaseTokenHashLength } || leaseDuration <= TimeSpan.Zero)
            throw Invalid();
        Status = AppearanceQueryStatus.Running;
        AttemptCount++;
        LeaseOwner = workerId;
        LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(leaseDuration);
    }

    public bool HoldsActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc) =>
        Status == AppearanceQueryStatus.Running && tokenMatches && LeaseTokenHash is not null &&
        attemptCount == AttemptCount && string.Equals(LeaseOwner, workerId, StringComparison.Ordinal) &&
        LeaseExpiresAtUtc is { } expiry && expiry > nowUtc.ToUniversalTime();

    /// <summary>Whether a completion replays the one that filled this query (same owner, capability and attempt).</summary>
    public bool IsCompletionReplay(string workerId, bool tokenMatches, int attemptCount) =>
        Status == AppearanceQueryStatus.Completed && tokenMatches && LeaseTokenHash is not null &&
        attemptCount == AttemptCount && string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    public void Complete(string workerId, bool tokenMatches, int attemptCount, float[] embedding, int dimension, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(embedding);
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(EmbeddingAnalysis.LeaseInvalidCode, "The lease is not held by this attempt.");
        if (embedding.Length != dimension) throw Invalid();
        Embedding = [.. embedding];
        Status = AppearanceQueryStatus.Completed;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        LeaseExpiresAtUtc = null;
    }

    public void Fail(string workerId, bool tokenMatches, int attemptCount, string failureCode, bool retryable, DateTimeOffset nowUtc)
    {
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(EmbeddingAnalysis.LeaseInvalidCode, "The lease is not held by this attempt.");
        if (!EmbeddingAnalysis.IsFailureCode(failureCode)) throw Invalid();
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        FailureCode = failureCode;
        if (retryable && AttemptCount < MaximumAttempts)
        {
            Status = AppearanceQueryStatus.Pending;
            return;
        }

        Status = AppearanceQueryStatus.Failed;
        CompletedAtUtc = nowUtc.ToUniversalTime();
    }

    /// <summary>A query whose attempts are spent and whose last lease lapsed is failed by the platform.</summary>
    public bool IsExhausted(DateTimeOffset nowUtc) =>
        Status == AppearanceQueryStatus.Running && AttemptCount >= MaximumAttempts &&
        LeaseExpiresAtUtc is { } expiry && expiry <= nowUtc.ToUniversalTime();

    public void FailExhausted(DateTimeOffset nowUtc)
    {
        if (!IsExhausted(nowUtc)) throw Invalid();
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        FailureCode = EmbeddingAnalysis.AttemptsExhaustedCode;
        Status = AppearanceQueryStatus.Failed;
        CompletedAtUtc = nowUtc.ToUniversalTime();
    }

    public Guid Id { get; private set; }
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public string Text { get; private set; } = string.Empty;
    public string TextSha256 { get; private set; } = string.Empty;
    public AppearanceQueryStatus Status { get; private set; }
    public int AttemptCount { get; private set; }
    public string? LeaseOwner { get; private set; }
    public byte[]? LeaseTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public DateTimeOffset RequestedAtUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public string? FailureCode { get; private set; }
    public float[]? Embedding { get; private set; }

    private static DomainValidationException Invalid() =>
        new(EmbeddingAnalysis.TransitionInvalidCode, "The appearance query operation is invalid.");
}
