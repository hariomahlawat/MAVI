using System.Globalization;

namespace Mavi.Application.Modules.VisualAttributes;

public enum AttributeUploadStatus
{
    /// <summary>Written and published create-once under the attempt.</summary>
    Stored,
    /// <summary>The attempt already holds exactly these bytes: an idempotent replay.</summary>
    AlreadyStored,
    /// <summary>The attempt already holds different bytes: nothing is overwritten.</summary>
    Conflict,
    /// <summary>More bytes arrived than were declared.</summary>
    TooLarge,
    /// <summary>The body ended before the declared length: a transport failure.</summary>
    Truncated,
    /// <summary>The declared length arrived but not the declared SHA-256.</summary>
    IntegrityMismatch,
}

public sealed record AttributeUploadResult(AttributeUploadStatus Status, long SizeBytes, string? Sha256);

public sealed record StagedPredictions(string StagingKey, long SizeBytes);

/// <summary>
/// The platform-owned staging of uploaded <c>AttributePredictions</c> (S2b plan §12):
/// <c>staging-attributes/{analysisId}/attempt-NNNN/predictions.json</c> under the managed
/// media root, outside the <c>staging/</c> tree the VisionJob janitor governs. The worker
/// never names a path; the platform derives it from the authorised analysis and attempt.
/// </summary>
public interface IAttributeStagingStore
{
    Task<AttributeUploadResult> WriteAsync(Guid analysisId, int attemptCount, Stream body, long declaredSizeBytes,
        string declaredSha256, CancellationToken cancellationToken);

    /// <summary>The staged artefact of one attempt, or <see langword="null"/> when none is published.</summary>
    StagedPredictions? Describe(Guid analysisId, int attemptCount);

    Task<Stream> OpenReadAsync(Guid analysisId, int attemptCount, CancellationToken cancellationToken);
}

public static class AttributeStagingLayout
{
    public const string RootDirectoryName = "staging-attributes";
    public const string PredictionsFileName = "predictions.json";

    public static string AttemptDirectoryName(int attemptCount) =>
        $"attempt-{attemptCount.ToString("D4", CultureInfo.InvariantCulture)}";

    /// <summary>The logical key the accepted-evidence store reads the staged bytes by.</summary>
    public static string StagingKey(Guid analysisId, int attemptCount) =>
        $"{RootDirectoryName}/{analysisId:D}/{AttemptDirectoryName(attemptCount)}/{PredictionsFileName}";

    /// <summary>The content-addressed accepted key: not attempt-scoped, so identical bytes adopt one object.</summary>
    public static string AcceptedKey(Guid analysisId, string sha256) =>
        $"evidence/attributes/{analysisId:D}/predictions-{sha256}.json";
}
