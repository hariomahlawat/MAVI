using Mavi.Domain.Common;

namespace Mavi.Domain.Events;

/// <summary>
/// One deterministic event derived by one catalogue rule from the facts of one
/// fact-bearing scene analysis unit (ADR-025).
/// </summary>
/// <remarks>
/// <para>
/// Immutable once written. The typed columns are what a query filters on; the
/// provenance document is evidence detail (participants, input facts and the
/// parameters as applied, each with its source), which is the only shape jsonb is
/// used for.
/// </para>
/// <para>
/// <see cref="Id"/> is supplied, not generated: it is a deterministic function of
/// the catalogue version, the rule, the unit and a rule-specific discriminator, so a
/// recompute of the same unit yields the same identity and drill-through links stay
/// valid.
/// </para>
/// </remarks>
public sealed class AnalyticEvent
{
    public const int MaximumRuleIdLength = 32;
    public const int MaximumVersionLength = 64;

    private AnalyticEvent() { }

    public static AnalyticEvent Create(
        Guid id,
        Guid derivationId,
        Guid sceneAnalysisId,
        Guid processingRunId,
        Guid videoAssetId,
        Guid cameraId,
        Guid sceneRevisionId,
        string analyticsAlgorithmVersion,
        string catalogueVersion,
        string ruleId,
        int ruleVersion,
        Guid? primaryTrackId,
        string? objectClass,
        Guid? zoneId,
        Guid? lineId,
        string? direction,
        long startOffsetMs,
        long endOffsetMs,
        DateTimeOffset startUtc,
        DateTimeOffset endUtc,
        int participantCount,
        string provenanceJson,
        string inputSha256)
    {
        if (id == Guid.Empty || derivationId == Guid.Empty || sceneAnalysisId == Guid.Empty ||
            processingRunId == Guid.Empty || videoAssetId == Guid.Empty || cameraId == Guid.Empty ||
            sceneRevisionId == Guid.Empty) throw Invalid();
        if (!IsToken(analyticsAlgorithmVersion, MaximumVersionLength) ||
            !IsToken(catalogueVersion, MaximumVersionLength) ||
            !IsToken(ruleId, MaximumRuleIdLength)) throw Invalid();
        if (ruleVersion < 1) throw Invalid();
        if (startOffsetMs < 0 || endOffsetMs < startOffsetMs || endUtc < startUtc) throw Invalid();
        if (participantCount < 0) throw Invalid();
        if (string.IsNullOrWhiteSpace(provenanceJson)) throw Invalid();
        if (!IsSha256(inputSha256)) throw Invalid();

        return new AnalyticEvent
        {
            Id = id,
            DerivationId = derivationId,
            SceneAnalysisId = sceneAnalysisId,
            ProcessingRunId = processingRunId,
            VideoAssetId = videoAssetId,
            CameraId = cameraId,
            SceneRevisionId = sceneRevisionId,
            AnalyticsAlgorithmVersion = analyticsAlgorithmVersion,
            CatalogueVersion = catalogueVersion,
            RuleId = ruleId,
            RuleVersion = ruleVersion,
            PrimaryTrackId = primaryTrackId,
            ObjectClass = objectClass,
            ZoneId = zoneId,
            LineId = lineId,
            Direction = direction,
            StartOffsetMs = startOffsetMs,
            EndOffsetMs = endOffsetMs,
            StartUtc = startUtc.ToUniversalTime(),
            EndUtc = endUtc.ToUniversalTime(),
            ParticipantCount = participantCount,
            ProvenanceJson = provenanceJson,
            InputSha256 = inputSha256,
        };
    }

    public Guid Id { get; private set; }
    public Guid DerivationId { get; private set; }
    public Guid SceneAnalysisId { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public Guid VideoAssetId { get; private set; }
    public Guid CameraId { get; private set; }
    public Guid SceneRevisionId { get; private set; }
    public string AnalyticsAlgorithmVersion { get; private set; } = string.Empty;
    public string CatalogueVersion { get; private set; } = string.Empty;
    public string RuleId { get; private set; } = string.Empty;
    public int RuleVersion { get; private set; }
    public Guid? PrimaryTrackId { get; private set; }
    public string? ObjectClass { get; private set; }
    public Guid? ZoneId { get; private set; }
    public Guid? LineId { get; private set; }
    public string? Direction { get; private set; }
    public long StartOffsetMs { get; private set; }
    public long EndOffsetMs { get; private set; }
    public DateTimeOffset StartUtc { get; private set; }
    public DateTimeOffset EndUtc { get; private set; }
    public int ParticipantCount { get; private set; }
    public string ProvenanceJson { get; private set; } = string.Empty;
    public string InputSha256 { get; private set; } = string.Empty;

    internal static bool IsToken(string? value, int maximumLength) =>
        !string.IsNullOrWhiteSpace(value) && value.Length <= maximumLength && value.Trim().Length == value.Length;

    internal static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static DomainValidationException Invalid() =>
        new(AnalyticEventErrorCodes.EventInvalid, "The analytic event is invalid.");
}
