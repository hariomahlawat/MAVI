using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Faces;

public enum FaceQueryStatus
{
    Pending,
    Running,
    Completed,
    Failed,
}

/// <summary>
/// A transient query image (ADR-022 §4–§5): uploaded by an operator, read once by the <c>faces</c> role through a
/// short lease, then erased. The image bytes are erased when the query completes or fails, and at most
/// <see cref="ImageLifetime"/> after upload; the whole query (its faces and their vectors) is purged
/// <see cref="QueryLifetime"/> after upload, the snapshot validity.
/// </summary>
public sealed class FaceQuery
{
    public const int MaximumAttempts = 3;
    public const int MaximumImageBytes = 2 * 1024 * 1024;
    public const string NotFoundCode = "face_query_not_found";
    public const string ImageExpiredCode = "face_query_image_expired";
    public static readonly TimeSpan ImageLifetime = TimeSpan.FromMinutes(15);
    public static readonly TimeSpan QueryLifetime = TimeSpan.FromHours(1);
    public static readonly IReadOnlySet<string> MimeTypes = new HashSet<string>(StringComparer.Ordinal) { "image/jpeg", "image/png" };

    private FaceQuery() { }

    public static FaceQuery Create(string identityFingerprint, byte[] image, string mimeType, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(image);
        if (!CanonicalSha256.IsCanonical(identityFingerprint) || image.Length is < 1 or > MaximumImageBytes || !MimeTypes.Contains(mimeType))
            throw Invalid();
        var now = nowUtc.ToUniversalTime();
        return new FaceQuery
        {
            Id = Guid.CreateVersion7(),
            IdentityFingerprint = identityFingerprint,
            Image = [.. image],
            ImageSha256 = CanonicalSha256.ToHex(System.Security.Cryptography.SHA256.HashData(image)),
            MimeType = mimeType,
            SizeBytes = image.Length,
            Status = FaceQueryStatus.Pending,
            CreatedAtUtc = now,
            PurgeAfterUtc = now.Add(QueryLifetime),
        };
    }

    public bool CanClaim(DateTimeOffset nowUtc) =>
        Image is not null && AttemptCount < MaximumAttempts &&
        (Status == FaceQueryStatus.Pending ||
         (Status == FaceQueryStatus.Running && LeaseExpiresAtUtc is { } expiry && expiry <= nowUtc.ToUniversalTime()));

    public void Claim(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, TimeSpan leaseDuration)
    {
        if (!CanClaim(nowUtc) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: FaceAnalysis.LeaseTokenHashLength } || leaseDuration <= TimeSpan.Zero)
            throw Invalid();
        Status = FaceQueryStatus.Running;
        AttemptCount++;
        LeaseOwner = workerId;
        LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(leaseDuration);
    }

    public bool HoldsActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc) =>
        Status == FaceQueryStatus.Running && tokenMatches && LeaseTokenHash is not null &&
        attemptCount == AttemptCount && string.Equals(LeaseOwner, workerId, StringComparison.Ordinal) &&
        LeaseExpiresAtUtc is { } expiry && expiry > nowUtc.ToUniversalTime();

    /// <summary>Whether a completion replays the one that filled this query (same owner, capability and attempt).</summary>
    public bool IsCompletionReplay(string workerId, bool tokenMatches, int attemptCount) =>
        Status == FaceQueryStatus.Completed && tokenMatches && LeaseTokenHash is not null &&
        attemptCount == AttemptCount && string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    /// <summary>The faces are written by the caller; the image is erased now (ADR-022 §5).</summary>
    public void Complete(string workerId, bool tokenMatches, int attemptCount, string facesJson, string completionDigest, DateTimeOffset nowUtc)
    {
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(FaceAnalysis.LeaseInvalidCode, "The lease is not held by this attempt.");
        if (string.IsNullOrWhiteSpace(facesJson) || !CanonicalSha256.IsCanonical(completionDigest)) throw Invalid();
        FacesJson = facesJson;
        CompletionDigest = completionDigest;
        Status = FaceQueryStatus.Completed;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        LeaseExpiresAtUtc = null;
        Image = null;
    }

    public void Fail(string workerId, bool tokenMatches, int attemptCount, string failureCode, bool retryable, DateTimeOffset nowUtc)
    {
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(FaceAnalysis.LeaseInvalidCode, "The lease is not held by this attempt.");
        if (!FaceAnalysis.IsFailureCode(failureCode)) throw Invalid();
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        FailureCode = failureCode;
        if (retryable && AttemptCount < MaximumAttempts)
        {
            Status = FaceQueryStatus.Pending;
            return;
        }

        Terminate(failureCode, nowUtc);
    }

    /// <summary>A query whose attempts are spent and whose last lease lapsed is failed by the platform.</summary>
    public bool IsExhausted(DateTimeOffset nowUtc) =>
        Status == FaceQueryStatus.Running && AttemptCount >= MaximumAttempts &&
        LeaseExpiresAtUtc is { } expiry && expiry <= nowUtc.ToUniversalTime();

    public void FailExhausted(DateTimeOffset nowUtc)
    {
        if (!IsExhausted(nowUtc)) throw Invalid();
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        Terminate(FaceAnalysis.AttemptsExhaustedCode, nowUtc);
    }

    /// <summary>Whether the image must be erased now: a finished query, or an upload older than <see cref="ImageLifetime"/>.</summary>
    public bool IsImageExpired(DateTimeOffset nowUtc) =>
        Image is not null &&
        (Status is FaceQueryStatus.Completed or FaceQueryStatus.Failed || nowUtc.ToUniversalTime() - CreatedAtUtc >= ImageLifetime);

    /// <summary>
    /// Erases the image. A query that has not completed by then can no longer be analysed and fails with
    /// <see cref="ImageExpiredCode"/>.
    /// </summary>
    public void EraseImage(DateTimeOffset nowUtc)
    {
        Image = null;
        if (Status is FaceQueryStatus.Pending or FaceQueryStatus.Running)
        {
            LeaseOwner = null;
            LeaseTokenHash = null;
            LeaseExpiresAtUtc = null;
            Terminate(ImageExpiredCode, nowUtc);
        }
    }

    private void Terminate(string code, DateTimeOffset nowUtc)
    {
        FailureCode = code;
        Status = FaceQueryStatus.Failed;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        Image = null;
    }

    public Guid Id { get; private set; }
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public byte[]? Image { get; private set; }
    public string ImageSha256 { get; private set; } = string.Empty;
    public string MimeType { get; private set; } = string.Empty;
    public long SizeBytes { get; private set; }
    public FaceQueryStatus Status { get; private set; }
    public int AttemptCount { get; private set; }
    public string? LeaseOwner { get; private set; }
    public byte[]? LeaseTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public DateTimeOffset PurgeAfterUtc { get; private set; }
    public string? FailureCode { get; private set; }
    public string? FacesJson { get; private set; }
    public string? CompletionDigest { get; private set; }

    private static DomainValidationException Invalid() =>
        new(FaceAnalysis.TransitionInvalidCode, "The face query operation is invalid.");
}

/// <summary>
/// One gallery entry (ADR-022 §4): an operator-entered label and note. Its templates are
/// <see cref="EnrolledPersonFace"/> rows. A match against it is computed when asked and never stored (ADR-022 §1).
/// </summary>
public sealed class EnrolledPerson
{
    public const int MaximumLabelLength = 100;
    public const int MaximumNoteLength = 500;
    public const string InvalidCode = "face_gallery_entry_invalid";
    public const string NotFoundCode = "face_gallery_entry_not_found";

    private EnrolledPerson() { }

    public static EnrolledPerson Create(string? label, string? note, DateTimeOffset nowUtc)
    {
        var now = nowUtc.ToUniversalTime();
        return new EnrolledPerson
        {
            Id = Guid.CreateVersion7(),
            Label = ValidLabel(label),
            Note = ValidNote(note),
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
    }

    public void Update(string? label, string? note, bool noteGiven, DateTimeOffset nowUtc)
    {
        if (label is not null) Label = ValidLabel(label);
        if (noteGiven) Note = ValidNote(note);
        UpdatedAtUtc = nowUtc.ToUniversalTime();
    }

    public Guid Id { get; private set; }
    public string Label { get; private set; } = string.Empty;
    public string? Note { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }

    private static string ValidLabel(string? value)
    {
        var trimmed = value?.Trim();
        if (trimmed is not { Length: >= 1 and <= MaximumLabelLength } || trimmed.Any(char.IsControl))
            throw new DomainValidationException(InvalidCode, $"A label of 1 to {MaximumLabelLength} characters is required.");
        return trimmed;
    }

    private static string? ValidNote(string? value)
    {
        var trimmed = value?.Trim();
        if (string.IsNullOrEmpty(trimmed)) return null;
        if (trimmed.Length > MaximumNoteLength || trimmed.Any(character => char.IsControl(character) && character is not '\n' and not '\r'))
            throw new DomainValidationException(InvalidCode, $"A note is at most {MaximumNoteLength} characters.");
        return trimmed;
    }
}

public enum EnrolledFaceSource
{
    Evidence,
    Query,
}

/// <summary>
/// One gallery template (ADR-022 §4): a face vector under one identity. A template enrolled from an uploaded image
/// keeps the worker's 112×112 aligned thumbnail; one enrolled from evidence keeps the face observation's id (no
/// foreign key, so the run can still be deleted) and no image.
/// </summary>
public sealed class EnrolledPersonFace
{
    private EnrolledPersonFace() { }

    public static EnrolledPersonFace Create(Guid enrolledPersonId, string identityFingerprint, float[] embedding, EnrolledFaceSource source,
        Guid? sourceFaceObservationId, byte[]? thumbnail, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(embedding);
        if (enrolledPersonId == Guid.Empty || !CanonicalSha256.IsCanonical(identityFingerprint) || embedding.Length is < 1 or > 4096 ||
            (source == EnrolledFaceSource.Evidence) != (sourceFaceObservationId is not null) ||
            (source == EnrolledFaceSource.Evidence && thumbnail is not null))
            throw new DomainValidationException(EnrolledPerson.InvalidCode, "The gallery template is invalid.");
        return new EnrolledPersonFace
        {
            Id = Guid.CreateVersion7(),
            EnrolledPersonId = enrolledPersonId,
            IdentityFingerprint = identityFingerprint,
            Embedding = [.. embedding],
            SourceKind = source,
            SourceFaceObservationId = sourceFaceObservationId,
            Thumbnail = thumbnail is null ? null : [.. thumbnail],
            CreatedAtUtc = nowUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public Guid EnrolledPersonId { get; private set; }
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public float[] Embedding { get; private set; } = [];
    public EnrolledFaceSource SourceKind { get; private set; }
    public Guid? SourceFaceObservationId { get; private set; }
    public byte[]? Thumbnail { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
}
