namespace Mavi.IntegrationTests;

/// <summary>
/// The test-database naming rules that keep concurrent worktrees and agents off each other's schema. Pure:
/// no database is touched.
/// </summary>
public sealed class TestDatabaseTests
{
    [Theory]
    [InlineData("pr4", "mavi_test_pr4")]
    [InlineData("wt0123456789ab", "mavi_test_wt0123456789ab")]
    public void ASimpleRunIdIsUsedAsIs(string runId, string expected) =>
        Assert.Equal(expected, TestDatabase.DerivedDatabaseName(runId));

    [Theory]
    [InlineData("stage4/pr4-plate-search")]
    [InlineData("PR4")]
    [InlineData("a-b")]
    [InlineData("an-extremely-long-run-identifier-that-exceeds-forty-characters-by-far")]
    public void ALossyOrLongRunIdIsShortenedWithAHashAndStaysValid(string runId)
    {
        var name = TestDatabase.DerivedDatabaseName(runId);

        Assert.True(TestDatabase.IsTestDatabaseName(name), name);
        Assert.Equal(name, TestDatabase.DerivedDatabaseName(runId));
    }

    [Fact]
    public void DifferentRunIdsNeverShareADatabase()
    {
        string[] ids = ["a-b", "a_b", "ab", "AB", "stage4/pr4", "stage4-pr4", "stage4_pr4"];
        var names = ids.Select(TestDatabase.DerivedDatabaseName).ToArray();

        Assert.Equal(names.Length, names.Distinct(StringComparer.Ordinal).Count());
    }

    [Fact]
    public void EachWorktreeDerivesItsOwnStableDatabase()
    {
        var first = TestDatabase.WorktreeRunId(@"E:\work\MAVI2\.claude\worktrees\agent-a");
        var again = TestDatabase.WorktreeRunId(@"E:\work\MAVI2\.claude\worktrees\agent-a\");
        var other = TestDatabase.WorktreeRunId(@"E:\work\MAVI2\.claude\worktrees\agent-b");

        Assert.Equal(first, again);
        Assert.NotEqual(first, other);
        Assert.True(TestDatabase.IsTestDatabaseName(TestDatabase.DerivedDatabaseName(first)));
    }

    [Theory]
    [InlineData("mavi_test", true)]
    [InlineData("mavi_test_pr4", true)]
    [InlineData("mavi_dev", false)]
    [InlineData("mavi", false)]
    [InlineData("postgres", false)]
    [InlineData("mavi_test_", false)]
    [InlineData("mavi_test_PR4", false)]
    [InlineData("mavi_test_pr4; DROP DATABASE mavi", false)]
    [InlineData(null, false)]
    public void OnlyTheBaseOrADerivedNameMayBeReset(string? name, bool allowed) =>
        Assert.Equal(allowed, TestDatabase.IsTestDatabaseName(name));
}
