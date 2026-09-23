namespace Mavi.Infrastructure.Storage;

/// <summary>Configuration of the platform staging janitor (S1.2 plan §6.5, §10.5).</summary>
public sealed class StagingJanitorOptions
{
    public const string SectionName = "StagingJanitor";

    /// <summary>
    /// Disabling stops reclamation without affecting completion, leasing or serving;
    /// worker staging then accumulates until it is re-enabled.
    /// </summary>
    public bool Enabled { get; init; } = true;

    public int IntervalMinutes { get; init; } = 15;

    /// <summary>Delay after a terminal transition, so the worker's own fast-path cleanup runs first.</summary>
    public int GraceMinutes { get; init; } = 5;

    /// <summary>Age a job directory with no VisionJob row must reach before it is reclaimed.</summary>
    public int UnknownJobGraceHours { get; init; } = 24;

    public int MaxDirectoriesPerCycle { get; init; } = 1000;

    public int WarnOldestEligibleMinutes { get; init; } = 60;

    public int ErrorOldestEligibleMinutes { get; init; } = 360;

    public TimeSpan Interval => TimeSpan.FromMinutes(IntervalMinutes);
    public TimeSpan Grace => TimeSpan.FromMinutes(GraceMinutes);
    public TimeSpan UnknownJobGrace => TimeSpan.FromHours(UnknownJobGraceHours);

    public bool IsValid =>
        IntervalMinutes is >= 1 and <= 1440 &&
        GraceMinutes is >= 0 and <= 1440 &&
        UnknownJobGraceHours is >= 1 and <= 8760 &&
        MaxDirectoriesPerCycle is >= 1 and <= 100_000 &&
        WarnOldestEligibleMinutes >= 1 &&
        ErrorOldestEligibleMinutes > WarnOldestEligibleMinutes;
}
