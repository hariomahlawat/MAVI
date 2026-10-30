using Mavi.Contracts.Worker.Embeddings;

namespace Mavi.Contracts.Worker.Faces;

/// <summary>The face control plane's closed vocabulary and bounds (PoC S6; ADR-022 §3–§4).</summary>
public static class FaceContractRules
{
    public const string SchemaVersion = "mavi-face-control-v1";
    public const string IdentitySchemaVersion = "mavi-face-identity-v1";
    public const string PipelineSchemaVersion = "mavi-face-pipeline-v1";
    public const string RoleId = "faces";

    public const string CapabilityHeader = EmbeddingContractRules.CapabilityHeader;
    public const string AttemptHeader = EmbeddingContractRules.AttemptHeader;
    public const string WorkerHeader = EmbeddingContractRules.WorkerHeader;

    public const string AnalysisRoutePrefix = "/api/faces/analyses";
    public const string QueryWorkerRoutePrefix = "/api/faces/queries";

    public const string OutcomeObserved = "observed";
    public const string OutcomeUnknown = "unknown";

    public const string ReasonNoEvidence = "no_evidence";
    public const string ReasonEvidenceUnavailable = "evidence_unavailable";
    public const string ReasonNoFaceDetected = "no_face_detected";
    public const string ReasonFaceTooSmall = "face_too_small";

    public static readonly IReadOnlySet<string> UnknownReasons = new HashSet<string>(StringComparer.Ordinal)
    {
        ReasonNoEvidence, ReasonEvidenceUnavailable, ReasonNoFaceDetected, ReasonFaceTooSmall,
    };

    /// <summary>The analysis failure vocabulary and whether each code may be retried.</summary>
    public static readonly IReadOnlyDictionary<string, bool> FailureCodeRetryable = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        ["face_runtime_failed"] = true,
        ["face_evidence_transport_failed"] = true,
        ["face_model_unavailable"] = true,
        ["face_cancelled"] = true,
        ["face_output_invalid"] = false,
    };

    /// <summary>The query failure vocabulary.</summary>
    public static readonly IReadOnlyDictionary<string, bool> QueryFailureCodeRetryable = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        ["face_query_runtime_failed"] = true,
        ["face_query_transport_failed"] = true,
        ["face_query_image_invalid"] = false,
    };

    public const int MaximumAnalysisTracks = WorkerContractRules.MaximumCompletionTracks;
    public const int MaximumFacesPerCrop = 8;
    public const int MaximumQueryFaces = 16;
    public const int MaximumFailureMessageLength = 2000;
    public const int MaximumDimension = EmbeddingContractRules.MaximumDimension;

    /// <summary>A box coordinate or landmark in crop pixels is finite and within this bound.</summary>
    public const double MaximumCoordinate = 16_384;

    /// <summary>A thumbnail is a 112×112 JPEG; this bounds its bytes.</summary>
    public const int MaximumThumbnailBytes = 64 * 1024;

    /// <summary>
    /// The completion request body bound: a full run's Tracks each with four crops of
    /// <see cref="MaximumFacesPerCrop"/> faces is far above any real run; 64 MB as the embedding plane.
    /// </summary>
    public const long MaximumCompletionBodyBytes = EmbeddingContractRules.MaximumCompletionBodyBytes;

    /// <summary>A query completion: at most <see cref="MaximumQueryFaces"/> faces with vector and thumbnail.</summary>
    public const long MaximumQueryCompletionBodyBytes = 4L * 1024 * 1024;

    public static bool IsCanonicalSha256(string? value) => EmbeddingContractRules.IsCanonicalSha256(value);

    public static float[]? TryDecodeVector(string? encoded, int dimension) => EmbeddingContractRules.TryDecodeVector(encoded, dimension);

    public static string EncodeVector(ReadOnlySpan<float> vector) => EmbeddingContractRules.EncodeVector(vector);

    public static bool IsCoordinate(double? value) => value is { } v && double.IsFinite(v) && v is >= 0 and <= MaximumCoordinate;
}
