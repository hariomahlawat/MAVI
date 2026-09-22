namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The rule that decides whether a measurement may be called evidence.
/// </summary>
/// <remarks>
/// Every qualification harness now routes its expectations through
/// <see cref="QualificationVerdict"/>, so this is the one place the fail-closed
/// behaviour can be pinned without a database or a heavy corpus. It runs in the
/// ordinary suite.
/// </remarks>
public sealed class QualificationVerdictTests
{
    [Fact]
    public void AMeasurementThatDidNotExerciseItsSubjectFailsOnAnyServer()
    {
        // Integrity is about whether the harness measured its subject, which is
        // just as broken on an engineering server as on a qualifying one.
        foreach (var qualificationGrade in new[] { true, false })
        {
            var verdict = new QualificationVerdict(qualificationGrade);
            verdict.RequireIntegrity("the workload ran", satisfied: false, "nothing executed");

            Assert.Single(verdict.BlockingFailures);
            Assert.Equal("qualification failure", verdict.Status);
            var error = Assert.Throws<QualificationFailedException>(() => verdict.Enforce("/tmp/evidence.json"));
            // The message has to name what failed and where to look, or a failed
            // qualification run is just a red test.
            Assert.Contains("the workload ran", error.Message, StringComparison.Ordinal);
            Assert.Contains("/tmp/evidence.json", error.Message, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void AnUnmetPrerequisiteFailsOnlyWhereTheRunCouldHaveQualified()
    {
        // On the required server an undersized workload is a failure, because the
        // run would otherwise be filed as qualification evidence for a workload it
        // never performed.
        var qualifying = new QualificationVerdict(qualificationGrade: true);
        qualifying.RequireForQualification("corpus is large enough", satisfied: false, "too small");
        Assert.Single(qualifying.BlockingFailures);
        Assert.Throws<QualificationFailedException>(() => qualifying.Enforce("/tmp/evidence.json"));

        // Anywhere else the same shortfall is the expected state of affairs: it is
        // recorded, the run stays green, and it is not called evidence.
        var observing = new QualificationVerdict(qualificationGrade: false);
        observing.RequireForQualification("corpus is large enough", satisfied: false, "too small");
        Assert.Empty(observing.BlockingFailures);
        Assert.Single(observing.Unmet);
        Assert.Equal("engineering observation — not qualification evidence", observing.Status);
        observing.Enforce("/tmp/evidence.json");
    }

    [Fact]
    public void OnlyASatisfiedRunOnTheRequiredServerIsCalledEvidence()
    {
        var qualifying = new QualificationVerdict(qualificationGrade: true);
        qualifying.RequireIntegrity("the workload ran", satisfied: true, "executed");
        qualifying.RequireForQualification("corpus is large enough", satisfied: true, "110000 facts");
        Assert.Equal("qualification evidence", qualifying.Status);
        qualifying.Enforce("/tmp/evidence.json");

        // The same satisfied checks on a server that cannot qualify never earn the
        // stronger name, which is what keeps a PostgreSQL 16 run an observation.
        var observing = new QualificationVerdict(qualificationGrade: false);
        observing.RequireIntegrity("the workload ran", satisfied: true, "executed");
        Assert.Equal("engineering observation — not qualification evidence", observing.Status);
    }

    [Fact]
    public void ACountMismatchRecordsBothSidesOfTheComparison()
    {
        var verdict = new QualificationVerdict(qualificationGrade: false);
        verdict.RequireIntegrityEqual("every Track was analysed", expected: 1_000, actual: 40);

        var check = Assert.Single(verdict.Unmet);
        Assert.Equal("expected 1000, measured 40", check.Detail);
    }
}

/// <summary>The switch that decides whether the heavy pass runs at all.</summary>
public sealed class QualificationGateSwitchTests
{
    [Fact]
    public void UnsetMeansSkipAndExactlyOneMeansRun()
    {
        Assert.False(QualificationGate.IsEnabledValue(null));
        Assert.False(QualificationGate.IsEnabledValue(string.Empty));
        Assert.True(QualificationGate.IsEnabledValue("1"));
    }

    [Theory]
    [InlineData("true")]
    [InlineData("yes")]
    [InlineData("0")]
    [InlineData("1 ")]
    [InlineData("TRUE")]
    public void AnythingElseThrowsRatherThanSkippingSilently(string value)
    {
        // An operator who typed MAVI_QUALIFICATION=true believes the qualification
        // ran. Skipping quietly would be a run that passed without executing, which
        // is the exact failure this harness exists to make impossible.
        var error = Assert.Throws<InvalidOperationException>(() => QualificationGate.IsEnabledValue(value));
        Assert.Contains(value, error.Message, StringComparison.Ordinal);
    }
}
