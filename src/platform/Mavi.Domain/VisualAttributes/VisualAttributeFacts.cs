using System.Diagnostics.CodeAnalysis;
using Mavi.Domain.Common;

namespace Mavi.Domain.VisualAttributes;

/// <summary>One recorded attempt failure: the unit's diagnostic history (S2b plan §8).</summary>
public sealed class VisualAttributeAttemptFailure
{
    private VisualAttributeAttemptFailure() { }

    public static VisualAttributeAttemptFailure Create(
        Guid analysisId, int attemptNumber, string failureCode, bool retryable, string? failureDetails, DateTimeOffset failedAtUtc)
    {
        if (analysisId == Guid.Empty || attemptNumber < 1 || !VisualAttributeAnalysis.IsFailureCode(failureCode) ||
            failureDetails?.Length > VisualAttributeAnalysis.MaximumFailureDetailsLength)
            throw new DomainValidationException("visual_attribute_failure_invalid", "The attempt failure is invalid.");
        return new VisualAttributeAttemptFailure
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

public enum VisualAttributeTrackOutcomeKind
{
    Analysed,
    Unavailable,
}

/// <summary>
/// The Track-level outcome of one completed analysis (ADR-013 §12, §14): exactly one per
/// applicable Track. <see cref="VisualAttributeTrackOutcomeKind.Unavailable"/> always carries
/// a reason and never masquerades as Unknown.
/// </summary>
public sealed class VisualAttributeTrackOutcome
{
    public const int MaximumReasonLength = 64;

    private VisualAttributeTrackOutcome() { }

    public static VisualAttributeTrackOutcome Analysed(Guid analysisId, Guid trackId) =>
        Create(analysisId, trackId, VisualAttributeTrackOutcomeKind.Analysed, null);

    public static VisualAttributeTrackOutcome Unavailable(Guid analysisId, Guid trackId, string reason) =>
        Create(analysisId, trackId, VisualAttributeTrackOutcomeKind.Unavailable, reason);

    private static VisualAttributeTrackOutcome Create(Guid analysisId, Guid trackId, VisualAttributeTrackOutcomeKind outcome, string? reason)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty ||
            (outcome == VisualAttributeTrackOutcomeKind.Analysed) != (reason is null) ||
            (reason is not null && !IsReason(reason)))
            throw new DomainValidationException("visual_attribute_track_outcome_invalid", "The Track outcome is invalid.");
        return new VisualAttributeTrackOutcome { AnalysisId = analysisId, TrackId = trackId, Outcome = outcome, Reason = reason };
    }

    private static bool IsReason(string value) =>
        value is { Length: >= 1 and <= MaximumReasonLength } &&
        value[0] is >= 'a' and <= 'z' &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_');

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public VisualAttributeTrackOutcomeKind Outcome { get; private set; }
    public string? Reason { get; private set; }
}

public enum VisualAttributeOutcome
{
    Observed,
    Unknown,
}

/// <summary>
/// A final Track-level attribute fact (ADR-013 §12, §14): exactly one per applicable
/// <c>(analysis, Track, attribute type)</c> of an Analysed Track. Observed carries a schema
/// value, a confidence in [0, 1] and its supporting Observation; Unknown carries none of them
/// and asserts nothing negative. Producer provenance lives on the analysis header only.
/// </summary>
[SuppressMessage("Naming", "CA1711:Identifiers should not have incorrect suffix", Justification = "VisualAttribute is the approved domain term.")]
public sealed class VisualAttribute
{
    public const int MaximumTokenLength = 64;

    private VisualAttribute() { }

    public static VisualAttribute Observed(
        Guid analysisId, Guid trackId, string attributeType, string value, double confidence, Guid supportingObservationId)
    {
        if (!IsKey(analysisId, trackId, attributeType) || !VisualAttributeAnalysis.IsToken(value) ||
            !double.IsFinite(confidence) || confidence is < 0 or > 1 || supportingObservationId == Guid.Empty)
            throw Invalid();
        return new VisualAttribute
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            TrackId = trackId,
            AttributeType = attributeType,
            Outcome = VisualAttributeOutcome.Observed,
            Value = value,
            Confidence = confidence,
            SupportingObservationId = supportingObservationId,
        };
    }

    public static VisualAttribute Unknown(Guid analysisId, Guid trackId, string attributeType)
    {
        if (!IsKey(analysisId, trackId, attributeType)) throw Invalid();
        return new VisualAttribute
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            TrackId = trackId,
            AttributeType = attributeType,
            Outcome = VisualAttributeOutcome.Unknown,
        };
    }

    private static bool IsKey(Guid analysisId, Guid trackId, string attributeType) =>
        analysisId != Guid.Empty && trackId != Guid.Empty && VisualAttributeAnalysis.IsToken(attributeType);

    private static DomainValidationException Invalid() =>
        new("visual_attribute_invalid", "The visual attribute data is invalid.");

    public Guid Id { get; private set; }
    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public string AttributeType { get; private set; } = string.Empty;
    public VisualAttributeOutcome Outcome { get; private set; }
    public string? Value { get; private set; }
    public double? Confidence { get; private set; }
    public Guid? SupportingObservationId { get; private set; }
}

/// <summary>
/// When a preferred identity became the release's (ADR-013 §9: no automatic backfill). A
/// run is queued automatically only if it completed after the current activation began, so
/// a binding change — rollback included — never re-analyses history on its own.
/// </summary>
public sealed class VisualAttributeIdentityActivation
{
    private VisualAttributeIdentityActivation() { }

    public static VisualAttributeIdentityActivation Create(string fingerprint, string canonicalIdentity, DateTimeOffset activatedAtUtc)
    {
        if (!CanonicalSha256.IsCanonical(fingerprint) || string.IsNullOrWhiteSpace(canonicalIdentity) || canonicalIdentity.Length > 4096)
            throw new DomainValidationException("visual_attribute_activation_invalid", "The identity activation is invalid.");
        return new VisualAttributeIdentityActivation
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
