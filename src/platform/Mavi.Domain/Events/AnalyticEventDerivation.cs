using Mavi.Domain.Common;

namespace Mavi.Domain.Events;

/// <summary>
/// The record that one fact-bearing scene analysis unit was evaluated by one
/// catalogue version (ADR-025 §3).
/// </summary>
/// <remarks>
/// (<see cref="SceneAnalysisId"/>, <see cref="CatalogueVersion"/>) is unique, which is
/// the backstop against a second writer. A unit's facts never change once it has
/// completed, so a derivation is written once, in the same transaction as its
/// events, and never updated.
/// </remarks>
public sealed class AnalyticEventDerivation
{
    private AnalyticEventDerivation() { }

    public static AnalyticEventDerivation Create(
        Guid sceneAnalysisId,
        Guid processingRunId,
        Guid cameraId,
        Guid sceneRevisionId,
        string analyticsAlgorithmVersion,
        string catalogueVersion,
        string catalogueSha256,
        string inputsSha256,
        int eventCount,
        string ruleStatesJson,
        DateTimeOffset derivedAtUtc)
    {
        if (sceneAnalysisId == Guid.Empty || processingRunId == Guid.Empty || cameraId == Guid.Empty ||
            sceneRevisionId == Guid.Empty) throw Invalid();
        if (!AnalyticEvent.IsToken(analyticsAlgorithmVersion, AnalyticEvent.MaximumVersionLength) ||
            !AnalyticEvent.IsToken(catalogueVersion, AnalyticEvent.MaximumVersionLength)) throw Invalid();
        if (!AnalyticEvent.IsSha256(catalogueSha256) || !AnalyticEvent.IsSha256(inputsSha256)) throw Invalid();
        if (eventCount < 0 || string.IsNullOrWhiteSpace(ruleStatesJson)) throw Invalid();

        return new AnalyticEventDerivation
        {
            Id = Guid.CreateVersion7(),
            SceneAnalysisId = sceneAnalysisId,
            ProcessingRunId = processingRunId,
            CameraId = cameraId,
            SceneRevisionId = sceneRevisionId,
            AnalyticsAlgorithmVersion = analyticsAlgorithmVersion,
            CatalogueVersion = catalogueVersion,
            CatalogueSha256 = catalogueSha256,
            InputsSha256 = inputsSha256,
            EventCount = eventCount,
            RuleStatesJson = ruleStatesJson,
            DerivedAtUtc = derivedAtUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public Guid SceneAnalysisId { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public Guid CameraId { get; private set; }
    public Guid SceneRevisionId { get; private set; }
    public string AnalyticsAlgorithmVersion { get; private set; } = string.Empty;
    public string CatalogueVersion { get; private set; } = string.Empty;
    public string CatalogueSha256 { get; private set; } = string.Empty;
    public string InputsSha256 { get; private set; } = string.Empty;
    public int EventCount { get; private set; }
    public string RuleStatesJson { get; private set; } = string.Empty;
    public DateTimeOffset DerivedAtUtc { get; private set; }

    private static DomainValidationException Invalid() =>
        new(AnalyticEventErrorCodes.DerivationInvalid, "The analytic event derivation is invalid.");
}
