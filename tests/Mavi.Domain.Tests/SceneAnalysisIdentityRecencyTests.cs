using Mavi.Domain.SceneAnalytics;

namespace Mavi.Domain.Tests;

/// <summary>
/// The rule that decides which of a run's successful identities is current. It must be
/// total and deterministic, because it runs inside a completion transaction where the
/// alternative — letting whichever attempt committed last win — is the defect it exists
/// to prevent.
/// </summary>
public sealed class SceneAnalysisIdentityRecencyTests
{
    private const string V1 = "scene-analytics-v1";
    private const string V2 = "scene-analytics-v2";

    [Fact]
    public void ANewerRevisionIsNewer()
    {
        Assert.True(SceneAnalysisIdentityRecency.IsNewerThan(Order(5, V1), Order(4, V1)));
        Assert.False(SceneAnalysisIdentityRecency.IsNewerThan(Order(4, V1), Order(5, V1)));
    }

    [Fact]
    public void WithinOneRevisionANewerEngineIsNewer()
    {
        Assert.True(SceneAnalysisIdentityRecency.IsNewerThan(Order(4, V2), Order(4, V1)));
        Assert.False(SceneAnalysisIdentityRecency.IsNewerThan(Order(4, V1), Order(4, V2)));
    }

    [Fact]
    public void AnIdentityIsNotNewerThanItself() =>
        Assert.False(SceneAnalysisIdentityRecency.IsNewerThan(Order(4, V1), Order(4, V1)));

    /// <summary>Revision dominates, so a newer revision wins even with an older engine.</summary>
    [Fact]
    public void RevisionRecencyOutranksEngineRecency()
    {
        Assert.True(SceneAnalysisIdentityRecency.IsNewerThan(Order(5, V1), Order(4, V2)));
        Assert.False(SceneAnalysisIdentityRecency.IsNewerThan(Order(4, V2), Order(5, V1)));
    }

    /// <summary>
    /// An ordinal comparison would call v10 older than v9, which would silently invert
    /// currency at the tenth engine version.
    /// </summary>
    [Fact]
    public void EngineVersionsCompareByMajorNumberNotAsText()
    {
        Assert.True(SceneAnalysisIdentityRecency.CompareAlgorithmVersions(
            "scene-analytics-v10", "scene-analytics-v9") > 0);
        Assert.True(string.CompareOrdinal("scene-analytics-v10", "scene-analytics-v9") < 0);
    }

    /// <summary>
    /// The order must stay total for a value the domain never mints, because the
    /// alternative is throwing inside a completion transaction.
    /// </summary>
    [Fact]
    public void AnUnparseableVersionStillOrdersDeterministically()
    {
        Assert.Equal(0, SceneAnalysisIdentityRecency.CompareAlgorithmVersions("legacy", "legacy"));
        Assert.Equal(
            Math.Sign(string.CompareOrdinal("legacy", V1)),
            Math.Sign(SceneAnalysisIdentityRecency.CompareAlgorithmVersions("legacy", V1)));
    }

    /// <summary>The comparison is antisymmetric, which is what makes "newer" unambiguous.</summary>
    [Theory]
    [InlineData(4, V1, 5, V1)]
    [InlineData(4, V1, 4, V2)]
    [InlineData(5, V1, 4, V2)]
    [InlineData(4, V1, 4, V1)]
    public void ComparisonIsAntisymmetric(int leftRevision, string leftVersion, int rightRevision, string rightVersion)
    {
        var left = Order(leftRevision, leftVersion);
        var right = Order(rightRevision, rightVersion);

        Assert.Equal(
            Math.Sign(SceneAnalysisIdentityRecency.Compare(left, right)),
            -Math.Sign(SceneAnalysisIdentityRecency.Compare(right, left)));
    }

    private static SceneAnalysisIdentityOrder Order(int revisionNumber, string algorithmVersion) =>
        new(revisionNumber, algorithmVersion);
}
