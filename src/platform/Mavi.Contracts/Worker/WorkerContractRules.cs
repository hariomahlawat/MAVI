using System.Buffers.Text;

namespace Mavi.Contracts.Worker;

public static class WorkerContractRules
{
    /// <summary>
    /// Version of the lease, heartbeat and fail messages and of legacy completion.
    /// Only the completion message has a newer version (see <see cref="CompletionSchemaVersionV3"/>).
    /// </summary>
    public const string SchemaVersion = "2.0";
    public const string CompletionSchemaVersionV2 = "2.0";
    public const string CompletionSchemaVersionV3 = "3.0";
    /// <summary>
    /// Completion exchange 3.1 (S1.4 B3 asynchronous finalization plan §5): the same
    /// Evidence Set body as 3.0, answered with a durable hand-off (<see cref="VisionJobFinalizationResponse"/>)
    /// instead of a synchronous completion. A wire version only: it normalizes to the 3.0
    /// semantic shape and digest domain.
    /// </summary>
    public const string CompletionSchemaVersionV31 = "3.1";

    /// <summary>
    /// Completion versions this platform accepts at <c>POST …/complete</c> and advertises at
    /// <c>GET /api/vision/contract</c>, in ascending order. F1 of the asynchronous-finalization
    /// repair defines 3.1 without accepting it: acceptance switches to
    /// <see cref="AsynchronousCompletionSchemaVersions"/> when F2 lands the hand-off, and 3.0
    /// retires with it (plan §15.2).
    /// </summary>
    public static IReadOnlyList<string> CompletionSchemaVersions { get; } =
        [CompletionSchemaVersionV2, CompletionSchemaVersionV3];

    /// <summary>The set F2 enables: 2.0 unchanged, 3.1 asynchronous, 3.0 retired.</summary>
    public static IReadOnlyList<string> AsynchronousCompletionSchemaVersions { get; } =
        [CompletionSchemaVersionV2, CompletionSchemaVersionV31];

    public static bool IsAcceptedCompletionSchemaVersion(string? value) =>
        value is CompletionSchemaVersionV2 or CompletionSchemaVersionV3;

    /// <summary>Every completion version the platform can read, accepted or not.</summary>
    public static bool IsKnownCompletionSchemaVersion(string? value) =>
        value is CompletionSchemaVersionV2 or CompletionSchemaVersionV3 or CompletionSchemaVersionV31;

    /// <summary>Whether a completion version is answered by a hand-off rather than a completion.</summary>
    public static bool IsAsynchronousCompletionSchemaVersion(string? value) =>
        value is CompletionSchemaVersionV31;

    /// <summary>Wire values of <see cref="VisionJobFinalizationResponse.State"/>.</summary>
    public const string FinalizationStateFinalizing = "finalizing";
    public const string FinalizationStateCompleted = "completed";

    public static bool IsFinalizationState(string? value) =>
        value is FinalizationStateFinalizing or FinalizationStateCompleted;

    public const int MaximumCompletionTracks = 10_000;
    // Re-derived for completion 3.0 (four observation descriptors per Track). The
    // worst-shape body is pinned by WorkerContractV3Tests.WorstShapeBodyFitsUnderLimit.
    public const long MaximumCompletionRequestBodyBytes = 48L * 1024 * 1024;
    public const long MaximumCompletionArtifactBytes = 64L * 1024 * 1024;
    /// <summary>
    /// Completion 2.0: thumbnails plus trajectories. Completion 3.0: trajectories
    /// (and other non-crop artefacts) only; crops count against
    /// <see cref="MaximumCompletionEvidenceCropBytes"/>.
    /// </summary>
    public const long MaximumCompletionEvidenceBytes = 512L * 1024 * 1024;
    public const long MaximumCompletionEvidenceCropBytes = 1024L * 1024 * 1024;
    public const int MaximumTrackObservations = 4;
    public const long MaximumRepresentativeCropBytes = 64L * 1024;
    public const long MaximumSupplementalCropBytes = 160L * 1024;
    public const int MaximumCompletionDependencyVersions = 128;
    public const double MinimumPositiveTrackerParameter = 1e-9;
    public const double MaximumPositiveTrackerParameter = 1e9;

    // Worker identity rules
    public static bool IsCanonicalWorkerId(string? value)
    {
        if (value is not { Length: >= 1 and <= 128 } || !IsAsciiAlphaNumeric(value[0])) return false;
        foreach (var character in value.AsSpan(1))
        {
            if (!IsWorkerIdContinuation(character)) return false;
        }
        return true;
    }

    public static bool TryNormalizeWorkerId(string? value, out string normalized)
    {
        normalized = value ?? string.Empty;
        return IsCanonicalWorkerId(value);
    }

    public static bool IsCanonicalLeaseToken(string? value)
    {
        if (value is not { Length: 43 }) return false;
        Span<byte> decoded = stackalloc byte[32];
        try
        {
            return Base64Url.TryDecodeFromChars(value, decoded, out var written) && written == 32 &&
                   string.Equals(Base64Url.EncodeToString(decoded), value, StringComparison.Ordinal);
        }
        catch (FormatException)
        {
            return false;
        }
    }

    // Failure reporting rules
    public static bool IsFailureCode(string? value)
    {
        if (value is not { Length: >= 1 and <= 64 } || !IsAsciiLower(value[0])) return false;
        foreach (var character in value.AsSpan(1))
        {
            if (!IsFailureCodeContinuation(character)) return false;
        }
        return true;
    }

    public static bool IsLogicalStorageKey(string? value)
    {
        if (value is null || value.Length is < 1 or > 512 || value[0] == '/' || value[^1] == '/' ||
            value.Contains('\\', StringComparison.Ordinal) || value.Contains(':', StringComparison.Ordinal)) return false;
        return value.Split('/').All(segment => segment.Length > 0 && segment is not "." and not "..");
    }

    private static bool IsFailureCodeContinuation(char value) =>
        IsAsciiLower(value) || value is >= '0' and <= '9' or '_';

    private static bool IsWorkerIdContinuation(char value) =>
        IsAsciiAlphaNumeric(value) || value is '.' or '_' or '-';

    private static bool IsAsciiAlphaNumeric(char value) =>
        value is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9';

    private static bool IsAsciiLower(char value) => value is >= 'a' and <= 'z';
}
