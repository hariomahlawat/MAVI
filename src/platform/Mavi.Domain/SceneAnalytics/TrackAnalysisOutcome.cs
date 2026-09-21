using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// What happened to one Track in one analysis unit. Exactly one row per Track per
/// unit, always — including Tracks that produced no facts.
/// </summary>
/// <remarks>
/// The "always" is the invariant that matters. A Track whose evidence could not be
/// read and a Track that simply did nothing are indistinguishable if the unusable
/// one is omitted, and the difference between "we could not look" and "we looked and
/// found nothing" is exactly what an operator is owed.
/// </remarks>
public sealed class TrackAnalysisOutcome
{
    private TrackAnalysisOutcome() { }

    /// <summary>Records a Track that was read and evaluated.</summary>
    public static TrackAnalysisOutcome Analysed(
        Guid analysisId,
        Guid trackId,
        string referencePoint,
        int sampleCount,
        int gapCount,
        long gapTotalMs)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty) throw Invalid();
        if (!SceneAnalyticsVocabulary.IsReferencePoint(referencePoint)) throw Invalid();
        if (sampleCount < 0 || gapCount < 0 || gapTotalMs < 0) throw Invalid();

        return new TrackAnalysisOutcome
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            Outcome = TrackAnalysisOutcomeKind.Analysed,
            Reason = null,
            ReferencePoint = referencePoint,
            SampleCount = sampleCount,
            GapCount = gapCount,
            GapTotalMs = gapTotalMs
        };
    }

    /// <summary>
    /// Records a Track whose evidence is permanently unusable, with the reason.
    /// </summary>
    /// <remarks>
    /// Only the reasons in <see cref="SceneAnalyticsErrorCodes.TrackUnavailableReasons"/>
    /// are accepted: each is permanent for this evidence, so retrying the unit would
    /// reach the same conclusion. A transient fault is an attempt failure, not an
    /// outcome, and must not be recorded here.
    /// </remarks>
    public static TrackAnalysisOutcome Unavailable(Guid analysisId, Guid trackId, string reason)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty) throw Invalid();
        if (!SceneAnalyticsErrorCodes.IsTrackUnavailableReason(reason)) throw Invalid();

        return new TrackAnalysisOutcome
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            Outcome = TrackAnalysisOutcomeKind.Unavailable,
            Reason = reason,
            ReferencePoint = null,
            SampleCount = 0,
            GapCount = 0,
            GapTotalMs = 0
        };
    }

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public TrackAnalysisOutcomeKind Outcome { get; private set; }
    public string? Reason { get; private set; }
    public string? ReferencePoint { get; private set; }
    public int SampleCount { get; private set; }
    public int GapCount { get; private set; }
    public long GapTotalMs { get; private set; }

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The track analysis outcome is invalid.");
}
