using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Tests;

/// <summary>
/// The analysis engine emits its vocabularies as string constants in
/// <c>Mavi.Application</c>; the persisted side restates them in
/// <see cref="SceneAnalyticsVocabulary"/> because the Domain may not reference the
/// Application layer. These tests are what stops the two copies drifting.
/// </summary>
/// <remarks>
/// The database check constraints are built from the Domain copy, so a drift here is
/// not cosmetic: it is an engine output the database would reject at the final fact
/// commit, discovered in production rather than in CI.
/// </remarks>
public sealed class SceneAnalyticsVocabularyTests
{
    [Fact]
    public void HeadingsMatchTheEngineExactly()
    {
        Assert.Equal(
            [
                AnalysisHeading.None,
                AnalysisHeading.North,
                AnalysisHeading.NorthEast,
                AnalysisHeading.East,
                AnalysisHeading.SouthEast,
                AnalysisHeading.South,
                AnalysisHeading.SouthWest,
                AnalysisHeading.West,
                AnalysisHeading.NorthWest,
            ],
            SceneAnalyticsVocabulary.Headings);
    }

    [Fact]
    public void CrossingDirectionsMatchTheEngineExactly()
    {
        Assert.Equal(
            [CrossingDirection.AToB, CrossingDirection.BToA],
            SceneAnalyticsVocabulary.CrossingDirections);
    }

    [Fact]
    public void ReferencePointsMatchTheEngineExactly()
    {
        Assert.Equal(
            [AnalysisReferencePoint.BoundingBoxCentre],
            SceneAnalyticsVocabulary.ReferencePoints);
    }

    [Fact]
    public void TrackUnavailableReasonsMatchTheEngineExactly()
    {
        Assert.Equal(
            [
                TrajectoryFailureReasons.Missing,
                TrajectoryFailureReasons.IntegrityFailed,
                TrajectoryFailureReasons.Invalid,
                TrajectoryFailureReasons.TooShort,
            ],
            SceneAnalyticsErrorCodes.TrackUnavailableReasons);
    }

    /// <summary>
    /// The column width is derived from the vocabularies, so a longer member added
    /// later must force a migration rather than silently truncate.
    /// </summary>
    [Fact]
    public void NoVocabularyMemberExceedsTheColumnWidth()
    {
        string[] every =
        [
            .. SceneAnalyticsVocabulary.Headings,
            .. SceneAnalyticsVocabulary.CrossingDirections,
            .. SceneAnalyticsVocabulary.ReferencePoints,
        ];

        Assert.All(every, value => Assert.True(value.Length <= SceneAnalyticsVocabulary.MaximumLength));
    }

    /// <summary>Every engine outcome reason is accepted by the Domain guard.</summary>
    [Fact]
    public void EveryEngineReasonIsAcceptedAndNothingElseIs()
    {
        Assert.All(
            SceneAnalyticsErrorCodes.TrackUnavailableReasons,
            reason => Assert.True(SceneAnalyticsErrorCodes.IsTrackUnavailableReason(reason)));

        Assert.False(SceneAnalyticsErrorCodes.IsTrackUnavailableReason("trajectory_missing "));
        Assert.False(SceneAnalyticsErrorCodes.IsTrackUnavailableReason("Trajectory_Missing"));
        Assert.False(SceneAnalyticsErrorCodes.IsTrackUnavailableReason(null));
        Assert.False(SceneAnalyticsVocabulary.IsHeading("north"));
        Assert.False(SceneAnalyticsVocabulary.IsReferencePoint("BoundingBoxCentre"));
    }
}
