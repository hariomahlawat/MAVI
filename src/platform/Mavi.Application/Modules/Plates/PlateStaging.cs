using System.Globalization;

namespace Mavi.Application.Modules.Plates;

public enum PlateUploadStatus
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

public sealed record PlateUploadResult(PlateUploadStatus Status, long SizeBytes, string? Sha256);

public sealed record StagedPlatePredictions(string StagingKey, long SizeBytes);

/// <summary>
/// The platform-owned staging of uploaded <c>PlatePredictions</c>:
/// <c>staging-plates/{analysisId}/attempt-NNNN/predictions.json</c> under the managed media root,
/// outside the VisionJob <c>staging/</c> tree and the attribute staging tree. The worker never names a
/// path; the platform derives it from the authorised analysis and attempt.
/// </summary>
public interface IPlateStagingStore
{
    Task<PlateUploadResult> WriteAsync(Guid analysisId, int attemptCount, Stream body, long declaredSizeBytes,
        string declaredSha256, CancellationToken cancellationToken);

    /// <summary>The staged artefact of one attempt, or <see langword="null"/> when none is published.</summary>
    StagedPlatePredictions? Describe(Guid analysisId, int attemptCount);

    Task<Stream> OpenReadAsync(Guid analysisId, int attemptCount, CancellationToken cancellationToken);
}

/// <summary>
/// Reclaims <c>staging-plates/{analysisId}/attempt-NNNN</c> directories that the plate analysis row
/// proves dead. Its authority is that row alone.
/// </summary>
public interface IPlateStagingJanitor
{
    /// <summary>One cycle; returns the number of attempt directories removed.</summary>
    Task<int> RunCycleAsync(CancellationToken cancellationToken);
}

public static class PlateStagingLayout
{
    public const string RootDirectoryName = "staging-plates";
    public const string PredictionsFileName = "predictions.json";

    public static string AttemptDirectoryName(int attemptCount) =>
        $"attempt-{attemptCount.ToString("D4", CultureInfo.InvariantCulture)}";

    /// <summary>The logical key the accepted-evidence store reads the staged bytes by.</summary>
    public static string StagingKey(Guid analysisId, int attemptCount) =>
        $"{RootDirectoryName}/{analysisId:D}/{AttemptDirectoryName(attemptCount)}/{PredictionsFileName}";

    /// <summary>The content-addressed accepted key: not attempt-scoped, so identical bytes adopt one object.</summary>
    public static string AcceptedKey(Guid analysisId, string sha256) =>
        $"evidence/plates/{analysisId:D}/predictions-{sha256}.json";
}
