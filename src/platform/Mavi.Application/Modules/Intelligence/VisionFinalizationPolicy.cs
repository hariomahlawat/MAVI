namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The finalizer's ownership policy, as the lifecycle and the domain consume it (F3 plan §6.1).
/// <see cref="MaximumDuration"/> is the single source of the absolute deadline for the SQL
/// pre-filters and for every domain check (§5.4, §8.6).
/// </summary>
public sealed record VisionFinalizationPolicy(
    TimeSpan ClaimDuration,
    TimeSpan ClaimExtension,
    int MaximumAttempts,
    TimeSpan MaximumDuration,
    int SealingBatchSize)
{
    public TimeSpan ClaimDuration { get; } = Validated(ClaimDuration, ClaimExtension, MaximumAttempts, MaximumDuration, SealingBatchSize);

    private static TimeSpan Validated(TimeSpan ClaimDuration, TimeSpan ClaimExtension, int MaximumAttempts, TimeSpan MaximumDuration, int SealingBatchSize)
    {
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(ClaimDuration, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(ClaimExtension, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(ClaimExtension, ClaimDuration);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaximumAttempts, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaximumDuration, ClaimDuration);
        ArgumentOutOfRangeException.ThrowIfLessThan(SealingBatchSize, 1);
        return ClaimDuration;
    }
}
