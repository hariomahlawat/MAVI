namespace Mavi.Contracts.Worker.Attributes;

/// <summary>
/// The attribute control plane's closed vocabulary and numeric bounds (S2b plan §8–§15).
/// </summary>
/// <remarks>
/// Every limit here is intentional and pinned by a test at the limit and at the limit + 1.
/// None is inherited from the video-import request limit. The derivations are recorded in
/// <c>docs/qualification/stage2-s2b/implementation-record.md</c> §4.
/// </remarks>
public static class VisualAttributeContractRules
{
    /// <summary>Version of every attribute control-plane message.</summary>
    public const string SchemaVersion = "mavi-visual-attribute-control-v1";

    /// <summary>The role's declared provenance contract (ADR-014 §5).</summary>
    public const string ProvenanceContract = "visual-attribute-complete-v1";

    /// <summary>The <c>AttributePredictions</c> artefact schema (ADR-013 §13).</summary>
    public const string PredictionsSchemaVersion = "mavi-attribute-predictions-v1";
    public const string PredictionsMediaType = "application/json";

    /// <summary>The only request and response header that carries the lease capability.</summary>
    public const string CapabilityHeader = "X-Mavi-Lease-Capability";
    /// <summary>Attempt and worker for the two routes without a JSON envelope (evidence GET, predictions PUT).</summary>
    public const string AttemptHeader = "X-Mavi-Attempt";
    public const string WorkerHeader = "X-Mavi-Worker-Id";
    /// <summary>The declared SHA-256 of an uploaded prediction artefact.</summary>
    public const string ContentSha256Header = "X-Mavi-Content-Sha256";

    public const string RoutePrefix = "/api/attributes/analyses";

    // --- Shape bounds ---------------------------------------------------------------

    /// <summary>The supported Track bound of one analysis: the ProcessingRun bound.</summary>
    public const int MaximumAnalysisTracks = WorkerContractRules.MaximumCompletionTracks;
    /// <summary>The Evidence Set bound: at most four accepted crops per Track.</summary>
    public const int MaximumTrackObservations = WorkerContractRules.MaximumTrackObservations;
    public const int MaximumSchemaAttributeTypes = 16;
    public const int MaximumAttributeTypesPerObjectClass = 8;
    public const int MaximumAttributeValues = 32;
    public const int MaximumTokenLength = 64;
    public const int MaximumFailureMessageLength = 4000;

    // --- Byte bounds (see the implementation record, §4) -----------------------------

    /// <summary>The existing 64 MiB per-artefact bound (ADR-013 §13).</summary>
    public const long MaximumPredictionArtifactBytes = WorkerContractRules.MaximumCompletionArtifactBytes;
    public const long MaximumLeaseRequestBodyBytes = 4 * 1024;
    public const long MaximumHeartbeatRequestBodyBytes = 4 * 1024;
    public const long MaximumFailRequestBodyBytes = 16 * 1024;
    public const long MaximumCompletionRequestBodyBytes = 32L * 1024 * 1024;
    /// <summary>A lease response at the worst supported shape fits under this; the worker refuses more.</summary>
    public const long MaximumLeaseResponseBytes = 16L * 1024 * 1024;

    // --- Vocabulary ------------------------------------------------------------------

    public const string OutcomeAnalysed = "analysed";
    public const string OutcomeUnavailable = "unavailable";
    public const string OutcomeObserved = "observed";
    public const string OutcomeUnknown = "unknown";

    public const string ObjectClassPerson = "person";
    public const string ObjectClassVehicle = "vehicle";

    public const string CapabilityPersonAttributes = "person-attributes";
    public const string CapabilityVehicleAttributes = "vehicle-attributes";

    /// <summary>The Track-level Unavailable reasons. Only platform-authoritative evidence conditions qualify.</summary>
    public static IReadOnlySet<string> UnavailableReasons { get; } = new HashSet<string>(StringComparer.Ordinal)
    {
        "evidence_missing",
        "evidence_integrity_failed",
        "evidence_decode_failed",
        "no_accepted_evidence",
    };

    /// <summary>Worker failure codes and whether each is retryable. Anything else is refused.</summary>
    public static IReadOnlyDictionary<string, bool> FailureCodeRetryable { get; } =
        new Dictionary<string, bool>(StringComparer.Ordinal)
        {
            // Retryable: the attempt ended for a reason a later attempt may not meet.
            ["visual_attribute_evidence_transport_failed"] = true,
            ["visual_attribute_upload_transport_failed"] = true,
            ["visual_attribute_capability_unavailable"] = true,
            ["visual_attribute_inference_failed"] = true,
            // Terminal: the same inputs will produce the same refusal.
            ["visual_attribute_output_invalid"] = false,
            ["visual_attribute_contract_violation"] = false,
        };

    /// <summary>Platform-owned terminal codes; a worker can never send them.</summary>
    public const string DeadlineExceededCode = "visual_attribute_deadline_exceeded";
    public const string AttemptsExhaustedCode = "visual_attribute_attempts_exhausted";

    /// <summary>An upload or completion whose bytes do not match their declared descriptor (ADR-013 §10).</summary>
    public const string ArtifactIntegrityFailedCode = "vision_result_artifact_integrity_failed";

    public static bool IsObjectClass(string? value) => value is ObjectClassPerson or ObjectClassVehicle;

    public static bool IsAttributeCapability(string? value) =>
        value is CapabilityPersonAttributes or CapabilityVehicleAttributes;

    /// <summary>Kebab-case schema token: <c>[a-z][a-z0-9-]*</c>, at most 64 characters, no trailing or doubled hyphen.</summary>
    public static bool IsSchemaToken(string? value)
    {
        if (value is not { Length: >= 1 and <= MaximumTokenLength } || value[0] is not (>= 'a' and <= 'z')) return false;
        if (value[^1] == '-' || value.Contains("--", StringComparison.Ordinal)) return false;
        foreach (var character in value)
        {
            if (character is not (>= 'a' and <= 'z' or >= '0' and <= '9' or '-')) return false;
        }

        return true;
    }

    public static bool IsCanonicalSha256(string? value)
    {
        if (value is not { Length: 64 }) return false;
        foreach (var character in value)
        {
            if (character is not (>= '0' and <= '9' or >= 'a' and <= 'f')) return false;
        }

        return true;
    }

    /// <summary>A body that names the capability would put it where it may be persisted or logged.</summary>
    public const string ForbiddenBodyTokenProperty = "leaseToken";
}
