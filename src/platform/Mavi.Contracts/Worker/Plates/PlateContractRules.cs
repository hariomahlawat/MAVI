namespace Mavi.Contracts.Worker.Plates;

/// <summary>
/// The plate control plane's closed vocabulary and numeric bounds (Stage 4 plan §5.3; ADR-013
/// implementation amendment 2026-10-13, items 11–15).
/// </summary>
/// <remarks>
/// Capability-specific by design (ADR-013 item 11): nothing here is shared with the attribute plane
/// except the run-level bounds both inherit from <see cref="WorkerContractRules"/>. Every byte
/// envelope below is an upper bound on the compact canonical JSON of one element, checked against
/// a maximal encoding by test, so <see cref="WorstCasePredictionArtifactBytes"/> and
/// <see cref="WorstCaseCompletionBodyBytes"/> never under-estimate what an honest worker can send.
/// </remarks>
public static class PlateContractRules
{
    /// <summary>Version of every plate control-plane message.</summary>
    public const string SchemaVersion = "mavi-plate-control-v1";

    /// <summary>The <c>plates</c> role's declared provenance contract (ADR-014 §5).</summary>
    public const string ProvenanceContract = "plate-complete-v1";

    /// <summary>The <c>PlatePredictions</c> artefact schema (ADR-013 item 13).</summary>
    public const string PredictionsSchemaVersion = "mavi-plate-predictions-v1";
    public const string PredictionsMediaType = "application/json";

    /// <summary>The canonical identity document (ADR-013 item 11).</summary>
    public const string IdentitySchemaVersion = "mavi-plate-identity-v1";

    /// <summary>The plate normalisation every identity of this contract version names.</summary>
    public const string NormalisationId = "mavi-plate-normalisation-v1";

    /// <summary>
    /// SHA-256 of <c>contracts/test-vectors/plate-normalisation-v1.json</c> (LF line endings, as
    /// <c>.gitattributes</c> pins every JSON file): the frozen rules and their conformance vectors.
    /// A test re-derives it from the file.
    /// </summary>
    public const string NormalisationSha256 = "84368e30a745da23a68eaef2d6a2667a3f544bd6978ac0653ffb46ab3a1c4bad";

    /// <summary>The only request and response header that carries the lease capability.</summary>
    public const string CapabilityHeader = "X-Mavi-Lease-Capability";
    /// <summary>Attempt and worker for the two routes without a JSON envelope (evidence GET, predictions PUT).</summary>
    public const string AttemptHeader = "X-Mavi-Attempt";
    public const string WorkerHeader = "X-Mavi-Worker-Id";
    /// <summary>The declared SHA-256 of an uploaded prediction artefact.</summary>
    public const string ContentSha256Header = "X-Mavi-Content-Sha256";

    public const string RoutePrefix = "/api/plates/analyses";

    // --- Shape bounds ---------------------------------------------------------------

    /// <summary>The supported Track bound of one analysis: the ProcessingRun bound.</summary>
    public const int MaximumAnalysisTracks = WorkerContractRules.MaximumCompletionTracks;
    /// <summary>The Evidence Set bound: at most four accepted crops per Track.</summary>
    public const int MaximumTrackObservations = WorkerContractRules.MaximumTrackObservations;

    /// <summary>Profile bounds: detector boxes recorded per crop, plates read per crop, readings per plate.</summary>
    public const int MaximumDetectionsPerCrop = 8;
    public const int MaximumReadingsPerPlate = 5;

    /// <summary>The most plate observations one Track can carry under the largest admissible profile.</summary>
    public const int MaximumTrackPlateObservations = MaximumTrackObservations * MaximumDetectionsPerCrop;

    /// <summary>Raw OCR text: at most 32 UTF-16 code units, at most two lines joined by one LF.</summary>
    public const int MaximumRawTextLength = 32;
    public const int MaximumRawLineCount = 2;

    /// <summary>NFKC expands one UTF-16 code unit into at most four alphanumeric characters (enumerated by test).</summary>
    public const int MaximumNormalisationExpansion = 4;
    public const int MaximumNormalisedTextLength = MaximumRawTextLength * MaximumNormalisationExpansion;

    /// <summary>Decoded evidence-crop dimensions a plate box may be expressed in.</summary>
    public const int MaximumCropDimension = 4096;

    public const int MaximumTokenLength = 64;
    public const int MaximumFailureMessageLength = 4000;

    // --- Byte bounds -----------------------------------------------------------------

    /// <summary>The existing 64 MiB per-artefact bound (ADR-013 §13), applied to the artefact and the completion body.</summary>
    public const long MaximumPredictionArtifactBytes = WorkerContractRules.MaximumCompletionArtifactBytes;
    public const long MaximumCompletionRequestBodyBytes = WorkerContractRules.MaximumCompletionArtifactBytes;

    /// <summary>
    /// The worst-case canonical-JSON size of one raw text: every code unit escaped as <c>\uXXXX</c>.
    /// </summary>
    public const int RawTextWorstCaseBytes = MaximumRawTextLength * 6;

    public const int ArtifactHeaderBytes = 4096;
    public const int ArtifactTrackEnvelopeBytes = 160;
    public const int ArtifactCropEnvelopeBytes = 256;
    public const int ArtifactDetectionEnvelopeBytes = 96;
    public const int ArtifactPlateEnvelopeBytes = 64;
    public const int ArtifactReadingEnvelopeBytes = 96;
    public const int ArtifactTextEnvelopeBytes = 160;

    public const int CompletionHeaderBytes = 16 * 1024;
    public const int CompletionTrackEnvelopeBytes = 160;
    public const int CompletionObservationEnvelopeBytes = 288;
    public const int CompletionReadingEnvelopeBytes = 96;
    public const int CompletionTextEnvelopeBytes = 192;

    public const long MaximumLeaseRequestBodyBytes = 4 * 1024;
    public const long MaximumHeartbeatRequestBodyBytes = 4 * 1024;
    public const long MaximumFailRequestBodyBytes = 16 * 1024;
    /// <summary>A lease response at the worst supported shape fits under this; the worker refuses more.</summary>
    public const long MaximumLeaseResponseBytes = 16L * 1024 * 1024;

    /// <summary>
    /// The largest <c>PlatePredictions</c> artefact an honest worker can produce under a profile at the
    /// supported bound (10,000 Tracks × 4 crops, every crop recording its maximum detections, plates and
    /// readings, every raw text at its longest escaped form, one Track text per plate).
    /// </summary>
    public static long WorstCasePredictionArtifactBytes(int maxDetectionsPerCrop, int maxPlatesPerCrop, int maxReadingsPerPlate)
    {
        RequireProfileShape(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate);
        long reading = ArtifactReadingEnvelopeBytes + RawTextWorstCaseBytes;
        long plate = ArtifactPlateEnvelopeBytes + maxReadingsPerPlate * reading;
        long crop = ArtifactCropEnvelopeBytes + (long)maxDetectionsPerCrop * ArtifactDetectionEnvelopeBytes + maxPlatesPerCrop * plate;
        long texts = (long)MaximumTrackObservations * maxPlatesPerCrop * ArtifactTextEnvelopeBytes;
        long track = ArtifactTrackEnvelopeBytes + MaximumTrackObservations * crop + texts;
        return ArtifactHeaderBytes + MaximumAnalysisTracks * track;
    }

    /// <summary>The largest completion body an honest worker can send under a profile at the supported bound.</summary>
    public static long WorstCaseCompletionBodyBytes(int maxDetectionsPerCrop, int maxPlatesPerCrop, int maxReadingsPerPlate)
    {
        RequireProfileShape(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate);
        long reading = CompletionReadingEnvelopeBytes + RawTextWorstCaseBytes;
        long observation = CompletionObservationEnvelopeBytes + maxReadingsPerPlate * reading;
        long plates = (long)MaximumTrackObservations * maxPlatesPerCrop;
        long track = CompletionTrackEnvelopeBytes + plates * observation + plates * CompletionTextEnvelopeBytes;
        return CompletionHeaderBytes + MaximumAnalysisTracks * track;
    }

    /// <summary>Whether a profile's shape is in range and both worst cases fit the 64 MiB cap (ADR-013 item 13).</summary>
    public static bool IsAdmissibleProfileShape(int maxDetectionsPerCrop, int maxPlatesPerCrop, int maxReadingsPerPlate) =>
        IsProfileShapeInRange(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate) &&
        WorstCasePredictionArtifactBytes(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate) <= MaximumPredictionArtifactBytes &&
        WorstCaseCompletionBodyBytes(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate) <= MaximumCompletionRequestBodyBytes;

    public static bool IsProfileShapeInRange(int maxDetectionsPerCrop, int maxPlatesPerCrop, int maxReadingsPerPlate) =>
        maxDetectionsPerCrop is >= 1 and <= MaximumDetectionsPerCrop &&
        maxPlatesPerCrop >= 1 && maxPlatesPerCrop <= maxDetectionsPerCrop &&
        maxReadingsPerPlate is >= 1 and <= MaximumReadingsPerPlate;

    private static void RequireProfileShape(int maxDetectionsPerCrop, int maxPlatesPerCrop, int maxReadingsPerPlate)
    {
        if (!IsProfileShapeInRange(maxDetectionsPerCrop, maxPlatesPerCrop, maxReadingsPerPlate))
            throw new ArgumentOutOfRangeException(nameof(maxDetectionsPerCrop), "plate_profile_shape_out_of_range");
    }

    // --- Vocabulary ------------------------------------------------------------------

    public const string ObjectClassVehicle = "vehicle";

    public const string CapabilityOcr = "ocr";
    public const string CapabilityPlateDetector = "plate-detector";

    /// <summary>The capability pairs of an identity, in canonical (ordinal) order.</summary>
    public static IReadOnlyList<string> Capabilities { get; } = [CapabilityOcr, CapabilityPlateDetector];

    public const string RoleRepresentative = "representative";
    public const string RoleNearView = "near-view";
    public const string RoleEarlyDiverse = "early-diverse";
    public const string RoleLateDiverse = "late-diverse";

    public static IReadOnlyList<string> EvidenceRoles { get; } = [RoleRepresentative, RoleNearView, RoleEarlyDiverse, RoleLateDiverse];

    public const string TrackOutcomeAnalysed = "analysed";
    public const string TrackOutcomeUnavailable = "unavailable";

    public const string PlateOutcomeRead = "read";
    public const string PlateOutcomeUnreadable = "unreadable";

    public const string CropScored = "scored";
    public const string CropAbstained = "abstained";
    public const string CropExcluded = "excluded";
    public const string CropUnavailable = "unavailable";

    /// <summary>Why a verified crop produced no inference result (ADR-013 item 15). Never a negative fact.</summary>
    public static IReadOnlySet<string> CropAbstentionReasons { get; } = new HashSet<string>(StringComparer.Ordinal)
    {
        "decode_failed",
        "detector_error",
        "ocr_error",
        "ocr_output_invalid",
    };

    /// <summary>Platform-authoritative evidence conditions a crop may report (ADR-013 item 3).</summary>
    public static IReadOnlySet<string> CropUnavailableReasons { get; } = new HashSet<string>(StringComparer.Ordinal)
    {
        "evidence_missing",
        "evidence_integrity_failed",
    };

    /// <summary>
    /// The Track-level Unavailable reasons, most severe first: a Track with no scored crop reports the
    /// first of these that one of its crops caused, or <c>no_accepted_evidence</c>.
    /// </summary>
    public static IReadOnlyList<string> TrackUnavailableReasonsBySeverity { get; } =
    [
        "evidence_integrity_failed",
        "evidence_missing",
        "evidence_decode_failed",
        "plate_inference_failed",
        "no_accepted_evidence",
    ];

    /// <summary>Worker failure codes and whether each is retryable. Anything else is refused.</summary>
    public static IReadOnlyDictionary<string, bool> FailureCodeRetryable { get; } =
        new Dictionary<string, bool>(StringComparer.Ordinal)
        {
            ["plate_evidence_transport_failed"] = true,
            ["plate_upload_transport_failed"] = true,
            ["plate_capability_unavailable"] = true,
            ["plate_inference_failed"] = true,
            ["plate_output_invalid"] = false,
            ["plate_contract_violation"] = false,
        };

    /// <summary>Platform-owned terminal codes; a worker can never send them.</summary>
    public const string DeadlineExceededCode = "plate_deadline_exceeded";
    public const string AttemptsExhaustedCode = "plate_attempts_exhausted";

    /// <summary>An upload or completion whose bytes do not match their declared descriptor (ADR-013 §10).</summary>
    public const string ArtifactIntegrityFailedCode = "vision_result_artifact_integrity_failed";

    /// <summary>A body that names the capability would put it where it may be persisted or logged.</summary>
    public const string ForbiddenBodyTokenProperty = "leaseToken";

    public static bool IsEvidenceRole(string? value) =>
        value is RoleRepresentative or RoleNearView or RoleEarlyDiverse or RoleLateDiverse;

    public static bool IsPlateCapability(string? value) => value is CapabilityOcr or CapabilityPlateDetector;

    /// <summary>
    /// Raw OCR text admissible on the wire (ADR-013 item 13): 1–32 well-formed UTF-16 code units; no C0
    /// control character except LF, no DEL and no U+FFFE/U+FFFF noncharacter; at most one LF, never first
    /// or last, so two non-empty lines at most.
    /// </summary>
    /// <remarks>
    /// The noncharacters are excluded because .NET's NFKC refuses U+FFFE while Python's accepts it, so the
    /// shared normalisation would diverge on them; neither can be a plate character.
    /// </remarks>
    public static bool IsRawText(string? value)
    {
        if (value is not { Length: >= 1 and <= MaximumRawTextLength }) return false;
        var lineFeeds = 0;
        for (var index = 0; index < value.Length; index++)
        {
            var character = value[index];
            if (char.IsHighSurrogate(character))
            {
                if (index + 1 >= value.Length || !char.IsLowSurrogate(value[index + 1])) return false;
                index++;
                continue;
            }

            if (char.IsLowSurrogate(character)) return false;
            if (character == '\n')
            {
                lineFeeds++;
                if (index == 0 || index == value.Length - 1) return false;
                continue;
            }

            if (character < 0x20 || character is '\u007f' or '￾' or '￿') return false;
        }

        return lineFeeds < MaximumRawLineCount;
    }

    /// <summary>The line count a raw text declares: one plus its LF count.</summary>
    public static int RawLineCount(string value)
    {
        ArgumentNullException.ThrowIfNull(value);
        return 1 + value.Count(character => character == '\n');
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
}
