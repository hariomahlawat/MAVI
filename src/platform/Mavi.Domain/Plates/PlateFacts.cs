using Mavi.Domain.Common;

namespace Mavi.Domain.Plates;

/// <summary>One recorded attempt failure: the unit's diagnostic history.</summary>
public sealed class PlateAttemptFailure
{
    private PlateAttemptFailure() { }

    public static PlateAttemptFailure Create(
        Guid analysisId, int attemptNumber, string failureCode, bool retryable, string? failureDetails, DateTimeOffset failedAtUtc)
    {
        if (analysisId == Guid.Empty || attemptNumber < 1 || !PlateAnalysis.IsFailureCode(failureCode) ||
            failureDetails?.Length > PlateAnalysis.MaximumFailureDetailsLength)
            throw new DomainValidationException("plate_failure_invalid", "The attempt failure is invalid.");
        return new PlateAttemptFailure
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            AttemptNumber = attemptNumber,
            FailureCode = failureCode,
            Retryable = retryable,
            FailureDetails = failureDetails,
            FailedAtUtc = failedAtUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public Guid AnalysisId { get; private set; }
    public int AttemptNumber { get; private set; }
    public string FailureCode { get; private set; } = string.Empty;
    public bool Retryable { get; private set; }
    public string? FailureDetails { get; private set; }
    public DateTimeOffset FailedAtUtc { get; private set; }
}

/// <summary>
/// When a preferred plate identity became the release's (ADR-013 §9: no automatic backfill). A run is
/// queued automatically only if it completed after the current activation began.
/// </summary>
/// <remarks>
/// The activation keeps the exact parameters and summary-policy bytes the identity pins by SHA-256, so a
/// unit of an identity that is no longer preferred can still be validated against its own rules after
/// the release moved on (ADR-013 implementation amendment 2026-10-13, item 11).
/// </remarks>
public sealed class PlateIdentityActivation
{
    public const int MaximumCanonicalIdentityLength = 4096;
    public const int MaximumDocumentLength = 64 * 1024;

    private PlateIdentityActivation() { }

    public static PlateIdentityActivation Create(
        string fingerprint, string canonicalIdentity, string parametersJson, string summaryPolicyJson, DateTimeOffset activatedAtUtc)
    {
        if (!CanonicalSha256.IsCanonical(fingerprint) ||
            string.IsNullOrWhiteSpace(canonicalIdentity) || canonicalIdentity.Length > MaximumCanonicalIdentityLength ||
            string.IsNullOrWhiteSpace(parametersJson) || parametersJson.Length > MaximumDocumentLength ||
            string.IsNullOrWhiteSpace(summaryPolicyJson) || summaryPolicyJson.Length > MaximumDocumentLength)
            throw new DomainValidationException("plate_activation_invalid", "The identity activation is invalid.");
        return new PlateIdentityActivation
        {
            Id = Guid.CreateVersion7(),
            Fingerprint = fingerprint,
            CanonicalIdentity = canonicalIdentity,
            ParametersJson = parametersJson,
            SummaryPolicyJson = summaryPolicyJson,
            ActivatedAtUtc = activatedAtUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public string Fingerprint { get; private set; } = string.Empty;
    public string CanonicalIdentity { get; private set; } = string.Empty;
    /// <summary>The exact parameters file text the identity pins by SHA-256.</summary>
    public string ParametersJson { get; private set; } = string.Empty;
    /// <summary>The exact summary-policy file text the identity pins by SHA-256.</summary>
    public string SummaryPolicyJson { get; private set; } = string.Empty;
    public DateTimeOffset ActivatedAtUtc { get; private set; }
}

public enum PlateTrackOutcomeKind
{
    Analysed,
    Unavailable,
}

/// <summary>
/// The Track-level outcome of one completed plate analysis: exactly one per Vehicle Track of the run
/// (ADR-013 §12; implementation amendment 2026-10-13, item 15). <see cref="PlateTrackOutcomeKind.Analysed"/>
/// with no plate observation means "no plate was found in the scored evidence", never "no plate";
/// <see cref="PlateTrackOutcomeKind.Unavailable"/> always carries a reason and no plate observation.
/// </summary>
public sealed class PlateTrackOutcome
{
    public const int MaximumReasonLength = 64;
    public const int MaximumPlateObservations = 32;

    private PlateTrackOutcome() { }

    public static PlateTrackOutcome Analysed(Guid analysisId, Guid trackId, int plateObservationCount, int distinctTextCount)
    {
        if (plateObservationCount is < 0 or > MaximumPlateObservations || distinctTextCount < 0 || distinctTextCount > plateObservationCount)
            throw Invalid();
        return Create(analysisId, trackId, PlateTrackOutcomeKind.Analysed, null, plateObservationCount, distinctTextCount);
    }

    public static PlateTrackOutcome Unavailable(Guid analysisId, Guid trackId, string reason) =>
        Create(analysisId, trackId, PlateTrackOutcomeKind.Unavailable, reason, 0, 0);

    private static PlateTrackOutcome Create(
        Guid analysisId, Guid trackId, PlateTrackOutcomeKind outcome, string? reason, int plateObservationCount, int distinctTextCount)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty ||
            (outcome == PlateTrackOutcomeKind.Analysed) != (reason is null) ||
            (reason is not null && !IsReason(reason)))
            throw Invalid();
        return new PlateTrackOutcome
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            Outcome = outcome,
            Reason = reason,
            PlateObservationCount = plateObservationCount,
            DistinctTextCount = distinctTextCount,
        };
    }

    private static bool IsReason(string value) =>
        value is { Length: >= 1 and <= MaximumReasonLength } &&
        value[0] is >= 'a' and <= 'z' &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_');

    private static DomainValidationException Invalid() =>
        new("plate_track_outcome_invalid", "The plate Track outcome is invalid.");

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public PlateTrackOutcomeKind Outcome { get; private set; }
    public string? Reason { get; private set; }
    public int PlateObservationCount { get; private set; }
    public int DistinctTextCount { get; private set; }
}

public enum PlateObservationOutcome
{
    Read,
    Unreadable,
}

public enum PlateNormalisationOutcome
{
    Ok,
    Rejected,
}

/// <summary>One kept reading's values, before it is attached to its plate observation.</summary>
public sealed record PlateReadingValues(
    int Rank,
    string RawText,
    int RawLineCount,
    double Confidence,
    string? NormalisedText,
    PlateNormalisationOutcome NormalisationOutcome,
    string? NormalisationReason,
    string? FormatClass);

/// <summary>
/// One selected plate of one leased evidence crop (ADR-013 implementation amendment 2026-10-13, items
/// 12–13): the plate box in the decoded crop's pixel space and the crop's decoded size, so the plate
/// region is a deterministic function of the sealed source crop. <see cref="PlateObservationOutcome.Read"/>
/// carries its kept readings as ranks <c>0..m-1</c> in non-increasing confidence;
/// <see cref="PlateObservationOutcome.Unreadable"/> carries none.
/// </summary>
public sealed class PlateObservation
{
    public const int MaximumPlateIndex = 7;
    public const int MaximumCropDimension = 4096;
    public const int MaximumReadings = 5;

    private readonly List<PlateReading> _readings = [];

    private PlateObservation() { }

    public static PlateObservation Create(
        Guid analysisId,
        Guid trackId,
        Guid sourceObservationId,
        int plateIndex,
        int boxX,
        int boxY,
        int boxWidth,
        int boxHeight,
        int cropWidth,
        int cropHeight,
        double detectorConfidence,
        PlateObservationOutcome outcome,
        IReadOnlyList<PlateReadingValues> readings)
    {
        ArgumentNullException.ThrowIfNull(readings);
        if (analysisId == Guid.Empty || trackId == Guid.Empty || sourceObservationId == Guid.Empty ||
            plateIndex is < 0 or > MaximumPlateIndex ||
            cropWidth is < 1 or > MaximumCropDimension || cropHeight is < 1 or > MaximumCropDimension ||
            boxX < 0 || boxY < 0 || boxWidth < 1 || boxHeight < 1 ||
            (long)boxX + boxWidth > cropWidth || (long)boxY + boxHeight > cropHeight ||
            !IsConfidence(detectorConfidence) || !Enum.IsDefined(outcome))
            throw Invalid();

        if (outcome == PlateObservationOutcome.Unreadable ? readings.Count != 0 : readings.Count is < 1 or > MaximumReadings)
            throw Invalid();
        for (var index = 0; index < readings.Count; index++)
        {
            if (readings[index].Rank != index ||
                (index > 0 && readings[index].Confidence > readings[index - 1].Confidence))
                throw Invalid();
        }

        var observation = new PlateObservation
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            TrackId = trackId,
            SourceObservationId = sourceObservationId,
            PlateIndex = plateIndex,
            BoxX = boxX,
            BoxY = boxY,
            BoxWidth = boxWidth,
            BoxHeight = boxHeight,
            CropWidth = cropWidth,
            CropHeight = cropHeight,
            DetectorConfidence = detectorConfidence,
            Outcome = outcome,
        };
        foreach (var values in readings)
            observation._readings.Add(PlateReading.Create(observation.Id, values));
        return observation;
    }

    internal static bool IsConfidence(double value) => double.IsFinite(value) && value is >= 0 and <= 1;

    private static DomainValidationException Invalid() =>
        new("plate_observation_invalid", "The plate observation is invalid.");

    public Guid Id { get; private set; }
    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid SourceObservationId { get; private set; }
    public int PlateIndex { get; private set; }
    public int BoxX { get; private set; }
    public int BoxY { get; private set; }
    public int BoxWidth { get; private set; }
    public int BoxHeight { get; private set; }
    public int CropWidth { get; private set; }
    public int CropHeight { get; private set; }
    public double DetectorConfidence { get; private set; }
    public PlateObservationOutcome Outcome { get; private set; }
    public IReadOnlyList<PlateReading> Readings => _readings;
}

/// <summary>
/// One kept reading of a <see cref="PlateObservationOutcome.Read"/> plate (ADR-013 implementation
/// amendment 2026-10-13, item 13). Raw text is immutable OCR output; the normalised text, its outcome
/// and the advisory format class are the platform's <c>mavi-plate-normalisation-v1</c> derivation, so an
/// <c>ok</c> reading always has a normalised text and a format class and a <c>rejected</c> one has
/// neither. No reading is ever a confirmed registration.
/// </summary>
public sealed class PlateReading
{
    public const int MaximumRawTextLength = 32;
    public const int MaximumNormalisedTextLength = 128;

    private PlateReading() { }

    internal static PlateReading Create(Guid plateObservationId, PlateReadingValues values)
    {
        ArgumentNullException.ThrowIfNull(values);
        if (plateObservationId == Guid.Empty || values.Rank is < 0 or >= PlateObservation.MaximumReadings ||
            !IsRawText(values.RawText) || values.RawLineCount != 1 + values.RawText.Count(character => character == '\n') ||
            !PlateObservation.IsConfidence(values.Confidence) || !Enum.IsDefined(values.NormalisationOutcome))
            throw Invalid();

        var shapeValid = values.NormalisationOutcome switch
        {
            PlateNormalisationOutcome.Ok => IsNormalisedText(values.NormalisedText) && values.NormalisationReason is null &&
                values.FormatClass is "in-standard" or "in-bh" or "other",
            _ => values.NormalisedText is null && values.FormatClass is null &&
                values.NormalisationReason is "empty" or "non-alphanumeric",
        };
        if (!shapeValid) throw Invalid();

        return new PlateReading
        {
            PlateObservationId = plateObservationId,
            Rank = values.Rank,
            RawText = values.RawText,
            RawLineCount = values.RawLineCount,
            Confidence = values.Confidence,
            NormalisedText = values.NormalisedText,
            NormalisationOutcome = values.NormalisationOutcome,
            NormalisationReason = values.NormalisationReason,
            FormatClass = values.FormatClass,
        };
    }

    /// <summary>1–32 UTF-16 code units, no NUL (PostgreSQL text cannot hold it), at most two lines.</summary>
    private static bool IsRawText(string? value) =>
        value is { Length: >= 1 and <= MaximumRawTextLength } &&
        !value.Contains('\0', StringComparison.Ordinal) &&
        value.Count(character => character == '\n') <= 1;

    internal static bool IsNormalisedText(string? value) =>
        value is { Length: >= 1 and <= MaximumNormalisedTextLength } &&
        value.All(character => character is >= 'A' and <= 'Z' or >= '0' and <= '9');

    private static DomainValidationException Invalid() =>
        new("plate_reading_invalid", "The plate reading is invalid.");

    public Guid PlateObservationId { get; private set; }
    public int Rank { get; private set; }
    public string RawText { get; private set; } = string.Empty;
    public int RawLineCount { get; private set; }
    public double Confidence { get; private set; }
    public string? NormalisedText { get; private set; }
    public PlateNormalisationOutcome NormalisationOutcome { get; private set; }
    public string? NormalisationReason { get; private set; }
    public string? FormatClass { get; private set; }
}

/// <summary>
/// A search-acceleration row (plan §2.7): one distinct normalised rank-0 text among a Track's
/// <see cref="PlateObservationOutcome.Read"/> plates under the analysis's summary policy, with its
/// support, its best confidence and the plate that carries it. It never replaces the readings and is
/// never a Track-level "the plate".
/// </summary>
public sealed class PlateTrackText
{
    private PlateTrackText() { }

    public static PlateTrackText Create(
        Guid analysisId, Guid trackId, string normalisedText, int supportCount, double maxConfidence, Guid bestPlateObservationId)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty || bestPlateObservationId == Guid.Empty ||
            !PlateReading.IsNormalisedText(normalisedText) ||
            supportCount is < 1 or > PlateTrackOutcome.MaximumPlateObservations ||
            !PlateObservation.IsConfidence(maxConfidence))
            throw new DomainValidationException("plate_track_text_invalid", "The plate Track text is invalid.");
        return new PlateTrackText
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            NormalisedText = normalisedText,
            SupportCount = supportCount,
            MaxConfidence = maxConfidence,
            BestPlateObservationId = bestPlateObservationId,
        };
    }

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public string NormalisedText { get; private set; } = string.Empty;
    public int SupportCount { get; private set; }
    public double MaxConfidence { get; private set; }
    public Guid BestPlateObservationId { get; private set; }
}
