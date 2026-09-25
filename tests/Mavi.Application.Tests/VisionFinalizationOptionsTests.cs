using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Processing;

namespace Mavi.Application.Tests;

/// <summary>The finalizer's options, policy and failure vocabulary (F3 plan §6.1, §9; slice 3).</summary>
public sealed class VisionFinalizationOptionsTests
{
    [Fact]
    public void DefaultsAreDisabledSingleConcurrencyAndValid()
    {
        var options = new VisionFinalizationOptions();

        Assert.False(options.Enabled);
        Assert.Equal(1, options.MaxConcurrentFinalizations);
        Assert.Empty(options.Validate());
        Assert.Equal(TimeSpan.FromSeconds(21_600 + 300), options.EffectiveMaximumFinalizationBound);
        var policy = options.ToPolicy();
        Assert.Equal(TimeSpan.FromSeconds(300), policy.ClaimDuration);
        Assert.Equal(TimeSpan.FromSeconds(300), policy.ClaimExtension);
        Assert.Equal(3, policy.MaximumAttempts);
        Assert.Equal(TimeSpan.FromSeconds(21_600), policy.MaximumDuration);
        Assert.Equal(200, policy.SealingBatchSize);
    }

    [Theory]
    [InlineData(nameof(VisionFinalizationOptions.MaxConcurrentFinalizations), 0)]
    [InlineData(nameof(VisionFinalizationOptions.MaxConcurrentFinalizations), 9)]
    [InlineData(nameof(VisionFinalizationOptions.PollIntervalSeconds), 0)]
    [InlineData(nameof(VisionFinalizationOptions.PollIntervalSeconds), 301)]
    [InlineData(nameof(VisionFinalizationOptions.ClaimSeconds), 29)]
    [InlineData(nameof(VisionFinalizationOptions.ClaimSeconds), 86_401)]
    [InlineData(nameof(VisionFinalizationOptions.ClaimExtensionSeconds), 29)]
    [InlineData(nameof(VisionFinalizationOptions.ClaimExtensionSeconds), 301)] // exceeds ClaimSeconds
    [InlineData(nameof(VisionFinalizationOptions.MaximumFinalizationAttempts), 0)]
    [InlineData(nameof(VisionFinalizationOptions.MaximumFinalizationAttempts), 21)]
    [InlineData(nameof(VisionFinalizationOptions.MaximumFinalizationDurationSeconds), 0)]
    [InlineData(nameof(VisionFinalizationOptions.MaximumFinalizationDurationSeconds), 299)] // below ClaimSeconds
    [InlineData(nameof(VisionFinalizationOptions.MaximumFinalizationDurationSeconds), 604_801)]
    [InlineData(nameof(VisionFinalizationOptions.SealingBatchSize), 0)]
    [InlineData(nameof(VisionFinalizationOptions.SealingBatchSize), 5001)]
    [InlineData(nameof(VisionFinalizationOptions.PayloadCleanupGraceSeconds), -1)]
    [InlineData(nameof(VisionFinalizationOptions.PayloadCleanupGraceSeconds), 86_401)]
    public void OptionsValidationRejectsEveryUnsafeCombination(string property, int value)
    {
        var options = With(property, value);

        var problems = options.Validate();

        // A cross-field rule may fire alongside the range rule; the named property is always cited.
        Assert.NotEmpty(problems);
        Assert.Contains(problems, problem => problem.Contains(property, StringComparison.Ordinal));
    }

    [Fact]
    public void PolicyRecordRefusesItsOwnUnsafeShapes()
    {
        var five = TimeSpan.FromMinutes(5);
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(TimeSpan.Zero, five, 3, TimeSpan.FromHours(1), 10));
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(five, TimeSpan.Zero, 3, TimeSpan.FromHours(1), 10));
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(five, five.Add(TimeSpan.FromTicks(1)), 3, TimeSpan.FromHours(1), 10));
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(five, five, 0, TimeSpan.FromHours(1), 10));
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(five, five, 3, five.Subtract(TimeSpan.FromTicks(1)), 10));
        Assert.Throws<ArgumentOutOfRangeException>(() => new VisionFinalizationPolicy(five, five, 3, TimeSpan.FromHours(1), 0));
        Assert.Equal(five, new VisionFinalizationPolicy(five, five, 3, five, 1).ClaimDuration);
    }

    [Fact]
    public void ADisabledSectionIsStillValidated()
    {
        var options = With(nameof(VisionFinalizationOptions.ClaimSeconds), 0, enabled: false);
        Assert.NotEmpty(options.Validate());
    }

    [Fact]
    public void BoundaryValuesAreAccepted()
    {
        Assert.Empty(With(nameof(VisionFinalizationOptions.ClaimExtensionSeconds), 300).Validate());
        Assert.Empty(With(nameof(VisionFinalizationOptions.MaximumFinalizationDurationSeconds), 300).Validate());
        Assert.Empty(With(nameof(VisionFinalizationOptions.MaxConcurrentFinalizations), 8).Validate());
    }

    [Fact]
    public void FailureCodeVocabularyIsExactlyTheDocumentedSet()
    {
        Assert.Equal(
            ExpectedDeterministic.Order(StringComparer.Ordinal),
            VisionFinalizationFailureCodes.Deterministic.Order(StringComparer.Ordinal));
        Assert.Equal(
            ExpectedTransient.Order(StringComparer.Ordinal),
            VisionFinalizationFailureCodes.Transient.Order(StringComparer.Ordinal));
        Assert.Equal("vision_finalization_exhausted", VisionFinalizationFailureCodes.Exhausted);
        Assert.Equal(11, VisionFinalizationFailureCodes.All.Count);
        Assert.All(VisionFinalizationFailureCodes.All, code => Assert.True(VisionJob.IsFinalizationFailureCode(code), code));
        Assert.False(VisionFinalizationFailureCodes.IsDeterministic(VisionFinalizationFailureCodes.Exhausted));
        Assert.False(VisionFinalizationFailureCodes.IsTransient(VisionFinalizationFailureCodes.Exhausted));
        Assert.Empty(VisionFinalizationFailureCodes.Deterministic.Intersect(VisionFinalizationFailureCodes.Transient));
    }

    private static readonly string[] ExpectedDeterministic =
    [
                "vision_finalization_payload_missing",
                "vision_finalization_payload_integrity_failed",
                "vision_finalization_payload_invalid",
                "vision_finalization_staging_missing",
                "vision_finalization_staging_integrity_failed",
                "vision_finalization_evidence_conflict",
                "vision_finalization_context_invalid",
    ];

    private static readonly string[] ExpectedTransient =
    [
        "vision_finalization_io_transient", "vision_finalization_db_transient", "vision_finalization_publication_ambiguous",
    ];

    private static VisionFinalizationOptions With(string property, int value, bool enabled = true)
    {
        var options = new VisionFinalizationOptions { Enabled = enabled };
        typeof(VisionFinalizationOptions).GetProperty(property)!.SetValue(options, value);
        return options;
    }
}
