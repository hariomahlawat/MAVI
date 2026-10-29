using System.Buffers.Binary;

namespace Mavi.Contracts.Worker.Embeddings;

/// <summary>
/// The embedding control plane's closed vocabulary and bounds (PoC S4; ADR-021 §3–§4).
/// </summary>
public static class EmbeddingContractRules
{
    public const string SchemaVersion = "mavi-embedding-control-v1";
    public const string IdentitySchemaVersion = "mavi-embedding-identity-v1";
    public const string PipelineSchemaVersion = "mavi-embedding-pipeline-v1";
    public const string RoleId = "embeddings";

    public const string CapabilityHeader = "X-Mavi-Lease-Capability";
    public const string AttemptHeader = "X-Mavi-Attempt";
    public const string WorkerHeader = "X-Mavi-Worker-Id";

    public const string AnalysisRoutePrefix = "/api/embeddings/analyses";
    public const string TextQueryRoutePrefix = "/api/embeddings/text-queries";

    public const string OutcomeEmbedded = "embedded";
    public const string OutcomeUnavailable = "unavailable";

    public const string ReasonNoEvidence = "no_evidence";
    public const string ReasonEvidenceTooSmall = "evidence_too_small";
    public const string ReasonEvidenceUnavailable = "evidence_unavailable";

    public static readonly IReadOnlySet<string> UnavailableReasons =
        new HashSet<string>(StringComparer.Ordinal) { ReasonNoEvidence, ReasonEvidenceTooSmall, ReasonEvidenceUnavailable };

    public static readonly IReadOnlySet<string> ObjectClasses = new HashSet<string>(StringComparer.Ordinal) { "Person", "Vehicle" };

    public static readonly IReadOnlySet<string> ExecutionProviders =
        new HashSet<string>(StringComparer.Ordinal) { "CPUExecutionProvider", "CUDAExecutionProvider" };

    /// <summary>The analysis failure vocabulary and whether each code may be retried.</summary>
    public static readonly IReadOnlyDictionary<string, bool> FailureCodeRetryable = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        ["embedding_runtime_failed"] = true,
        ["embedding_evidence_transport_failed"] = true,
        ["embedding_model_unavailable"] = true,
        ["embedding_cancelled"] = true,
        ["embedding_output_invalid"] = false,
    };

    /// <summary>The text-query failure vocabulary.</summary>
    public static readonly IReadOnlyDictionary<string, bool> TextFailureCodeRetryable = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        ["embedding_text_runtime_failed"] = true,
        ["embedding_text_invalid"] = false,
    };

    public const int MaximumAnalysisTracks = WorkerContractRules.MaximumCompletionTracks;
    public const int MaximumTrackObservations = WorkerContractRules.MaximumTrackObservations;
    public const int MaximumFailureMessageLength = 2000;
    public const int MaximumDimension = 4096;

    /// <summary>Appearance text after normalisation: 1–200 characters (ADR-021 §4).</summary>
    public const int MaximumAppearanceTextLength = 200;

    /// <summary>A vector's L2 norm must be 1 within this tolerance.</summary>
    public const double NormTolerance = 1e-3;

    /// <summary>
    /// The completion request body bound: every Track embedded at the largest dimension, with its four source
    /// ids and the JSON around them, plus the envelope. 10,000 × (4 × 4096 / 3 × 4 + 4 × 40 + 160) ≈ 58 MB at
    /// dimension 4096; at the SigLIP 2 dimension (768) a full run is about 45 MB smaller.
    /// </summary>
    public const long MaximumCompletionBodyBytes = 64L * 1024 * 1024;

    public static bool IsCanonicalSha256(string? value) =>
        value is { Length: 64 } && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    /// <summary>
    /// Decodes a base64 float32 little-endian vector of exactly <paramref name="dimension"/> components and
    /// checks it is finite and L2-normalised. Returns null when it is not.
    /// </summary>
    public static float[]? TryDecodeVector(string? encoded, int dimension)
    {
        if (encoded is null || dimension is < 1 or > MaximumDimension) return null;
        var expectedBytes = dimension * 4;
        if (encoded.Length != (expectedBytes + 2) / 3 * 4) return null;
        byte[] bytes;
        try
        {
            bytes = Convert.FromBase64String(encoded);
        }
        catch (FormatException)
        {
            return null;
        }

        if (bytes.Length != expectedBytes) return null;
        var vector = new float[dimension];
        double sum = 0;
        for (var index = 0; index < dimension; index++)
        {
            var value = BinaryPrimitives.ReadSingleLittleEndian(bytes.AsSpan(index * 4, 4));
            if (!float.IsFinite(value)) return null;
            vector[index] = value;
            sum += (double)value * value;
        }

        return Math.Abs(Math.Sqrt(sum) - 1.0) <= NormTolerance ? vector : null;
    }

    public static string EncodeVector(ReadOnlySpan<float> vector)
    {
        var bytes = new byte[vector.Length * 4];
        for (var index = 0; index < vector.Length; index++)
            BinaryPrimitives.WriteSingleLittleEndian(bytes.AsSpan(index * 4, 4), vector[index]);
        return Convert.ToBase64String(bytes);
    }

    /// <summary>
    /// Appearance text normalisation (ADR-021 §4): trim, collapse every whitespace run to one space,
    /// lower-case (invariant). Null when the result is empty or longer than 200 characters, or holds a control
    /// character.
    /// </summary>
    public static string? NormaliseAppearanceText(string? text)
    {
        if (text is null) return null;
        var builder = new System.Text.StringBuilder(text.Length);
        var pendingSpace = false;
        foreach (var character in text.Trim())
        {
            if (char.IsWhiteSpace(character))
            {
                pendingSpace = true;
                continue;
            }

            if (char.IsControl(character)) return null;
            if (pendingSpace && builder.Length > 0) builder.Append(' ');
            pendingSpace = false;
            builder.Append(char.ToLowerInvariant(character));
        }

        var normalised = builder.ToString();
        return normalised.Length is >= 1 and <= MaximumAppearanceTextLength ? normalised : null;
    }
}
