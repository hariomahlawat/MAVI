using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes;

/// <summary>
/// The platform's Visual Attribute lifecycle configuration (S2b plan §8, §15).
/// </summary>
/// <remarks>
/// <para>
/// Nothing is configured by default: with no Component Binding and pipeline profile path
/// the release expects no attribute analysis (<c>NotConfigured</c>), queues nothing and
/// leases nothing. The shipped release sets neither.
/// </para>
/// <para>
/// <b>Heartbeat margin.</b> The worker renews at <c>min(interval, remaining − margin)</c>
/// and validates that its interval plus margin plus request timeout stays under
/// <see cref="MinimumLeaseSeconds"/>; the platform refuses any lease or extension shorter
/// than that floor. Together the two rules keep every granted lease longer than the
/// worker's renewal cadence (plan §8).
/// </para>
/// </remarks>
public sealed class VisualAttributeOptions
{
    public const string SectionName = "VisualAttributes";
    public const int MinimumLeaseSeconds = 60;

    /// <summary>Runs the reconciler, deadline sweep and staging janitor host.</summary>
    public bool Enabled { get; init; }

    /// <summary>The release Component Binding the worker composes from.</summary>
    public string ComponentBindingPath { get; init; } = string.Empty;

    /// <summary>The attribute pipeline profile; its siblings are read from the same directory.</summary>
    public string PipelineProfilePath { get; init; } = string.Empty;

    public int LeaseSeconds { get; init; } = 120;
    public int HeartbeatExtensionSeconds { get; init; } = 120;
    public int MaximumAttempts { get; init; } = 3;

    /// <summary>The absolute bound from the first claim to publication (ADR-013 §9).</summary>
    public int MaximumAnalysisDurationSeconds { get; init; } = 6 * 3600;

    public int ReconcileIntervalSeconds { get; init; } = 30;
    public int ReconcileBatchSize { get; init; } = 100;

    /// <summary>A READY worker polls at least this often; longer silence reads as "no READY worker".</summary>
    public int WorkerPresenceSeconds { get; init; } = 180;

    /// <summary>Terminal analyses' staging is reclaimed this long after they end.</summary>
    public int StagingGraceMinutes { get; init; } = 15;

    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ComponentBindingPath) || !string.IsNullOrWhiteSpace(PipelineProfilePath);

    public VisualAttributeLeasePolicy LeasePolicy => new(
        TimeSpan.FromSeconds(LeaseSeconds),
        TimeSpan.FromSeconds(HeartbeatExtensionSeconds),
        MaximumAttempts,
        TimeSpan.FromSeconds(MaximumAnalysisDurationSeconds));

    public IReadOnlyList<string> Validate()
    {
        var problems = new List<string>();
        if (LeaseSeconds is < MinimumLeaseSeconds or > 86_400)
            problems.Add($"{SectionName}:LeaseSeconds must be between {MinimumLeaseSeconds} and 86400.");
        if (HeartbeatExtensionSeconds is < MinimumLeaseSeconds or > 86_400)
            problems.Add($"{SectionName}:HeartbeatExtensionSeconds must be between {MinimumLeaseSeconds} and 86400.");
        if (MaximumAttempts is < 1 or > 100)
            problems.Add($"{SectionName}:MaximumAttempts must be between 1 and 100.");
        if (MaximumAnalysisDurationSeconds < LeaseSeconds || MaximumAnalysisDurationSeconds > 7 * 86_400)
            problems.Add($"{SectionName}:MaximumAnalysisDurationSeconds must be at least LeaseSeconds and at most 604800.");
        if (ReconcileIntervalSeconds is < 1 or > 3600)
            problems.Add($"{SectionName}:ReconcileIntervalSeconds must be between 1 and 3600.");
        if (ReconcileBatchSize is < 1 or > 1000)
            problems.Add($"{SectionName}:ReconcileBatchSize must be between 1 and 1000.");
        if (WorkerPresenceSeconds is < 10 or > 86_400)
            problems.Add($"{SectionName}:WorkerPresenceSeconds must be between 10 and 86400.");
        if (StagingGraceMinutes is < 0 or > 1440)
            problems.Add($"{SectionName}:StagingGraceMinutes must be between 0 and 1440.");
        if (string.IsNullOrWhiteSpace(ComponentBindingPath) != string.IsNullOrWhiteSpace(PipelineProfilePath))
            problems.Add($"{SectionName}:ComponentBindingPath and {SectionName}:PipelineProfilePath are configured together or not at all.");
        return problems;
    }
}
