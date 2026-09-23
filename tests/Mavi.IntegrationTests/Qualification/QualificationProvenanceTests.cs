namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The provenance signals the qualification guard depends on are really captured,
/// and really describe this repository.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="QualificationVerdictTests"/> pins how the guard reacts to the two
/// signals, using dictionaries written by hand. That proves the rule and nothing
/// about the thing the rule reads. If <see cref="QualificationGate.CaptureEnvironmentAsync"/>
/// stopped emitting the keys, or emitted them from the wrong directory, those tests
/// would still pass while every qualification run refused itself for a reason that
/// had nothing to do with the source tree.
/// </para>
/// <para>
/// This runs in the ordinary suite. It needs a database only because capture reads
/// the live server alongside the repository state.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class QualificationProvenanceTests(PostgresFixture fixture)
{
    private static readonly string[] BooleanSignals = ["true", "false"];

    [Fact]
    public async Task CaptureEmitsProvenanceSignalsThatDescribeThisRepository()
    {
        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);

        Assert.True(environment.ContainsKey(QualificationGate.GitWorkingTreeCleanKey));
        Assert.True(environment.ContainsKey(QualificationGate.GitCommitObjectPresentKey));

        // Both signals are booleans the guard compares against "true"; anything else
        // would be read as a refusal for the wrong reason.
        Assert.Contains(environment[QualificationGate.GitWorkingTreeCleanKey], BooleanSignals);
        Assert.Contains(environment[QualificationGate.GitCommitObjectPresentKey], BooleanSignals);

        // The test assembly is built inside the repository from a real checkout, so
        // the reported SHA must resolve. A "false" here means capture is asking git
        // from somewhere that is not this repository — the guard would then refuse
        // every run regardless of how clean the tree was.
        Assert.Equal("true", environment[QualificationGate.GitCommitObjectPresentKey]);
        Assert.Matches("^[0-9a-f]{40}$", environment["gitSha"]);
    }

    /// <summary>
    /// A captured environment feeds the guard without translation.
    /// </summary>
    /// <remarks>
    /// The end-to-end shape: whatever this working tree's state is, the guard's
    /// verdict about it agrees with the captured signals. This is what ties the rule
    /// to the measurement, and it holds on a dirty tree as well as a clean one.
    /// </remarks>
    [Fact]
    public async Task TheGuardAgreesWithWhatCaptureObserved()
    {
        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);
        var verdict = new QualificationVerdict(qualificationGrade: true);

        QualificationGate.RequireRepositoryProvenance(verdict, environment);

        var expectedFailures =
            (environment[QualificationGate.GitWorkingTreeCleanKey] == "true" ? 0 : 1)
            + (environment[QualificationGate.GitCommitObjectPresentKey] == "true" ? 0 : 1);

        Assert.Equal(expectedFailures, verdict.BlockingFailures.Count);
    }
}
