using Mavi.Domain.Faces;

namespace Mavi.Application.Modules.Faces;

/// <summary>
/// The platform's face lifecycle configuration (PoC S6; ADR-022). Nothing is configured by default: with no model
/// manifest and pipeline profile the release expects no faces, queues and leases nothing, and every face surface
/// answers <c>faces_not_configured</c>.
/// </summary>
public sealed class FaceOptions
{
    public const string SectionName = "Faces";
    public const int MinimumLeaseSeconds = 60;

    /// <summary>Runs the authority loop: queueing, the deadline and exhaustion sweeps, the query purge.</summary>
    public bool Enabled { get; init; }

    /// <summary>The committed face pipeline manifest (manifest v2, capability <c>embedding</c>).</summary>
    public string ModelManifestPath { get; init; } = string.Empty;

    /// <summary>The face pipeline profile (<c>mavi-face-pipeline-v1</c>).</summary>
    public string PipelineProfilePath { get; init; } = string.Empty;

    public int LeaseSeconds { get; init; } = 120;
    public int HeartbeatExtensionSeconds { get; init; } = 120;
    public int MaximumAttempts { get; init; } = 3;
    public int MaximumAnalysisDurationSeconds { get; init; } = 6 * 3600;
    public int ReconcileIntervalSeconds { get; init; } = 15;
    public int ReconcileBatchSize { get; init; } = 100;
    public int QueryLeaseSeconds { get; init; } = 30;

    /// <summary>At most this many query images wait for the worker at once (ADR-022 §4).</summary>
    public int MaximumPendingQueries { get; init; } = 20;

    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ModelManifestPath) || !string.IsNullOrWhiteSpace(PipelineProfilePath);

    public FaceLeasePolicy LeasePolicy => new(
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
        if (QueryLeaseSeconds is < 5 or > 600)
            problems.Add($"{SectionName}:QueryLeaseSeconds must be between 5 and 600.");
        if (MaximumPendingQueries is < 1 or > 1000)
            problems.Add($"{SectionName}:MaximumPendingQueries must be between 1 and 1000.");
        if (string.IsNullOrWhiteSpace(ModelManifestPath) != string.IsNullOrWhiteSpace(PipelineProfilePath))
            problems.Add($"{SectionName}:ModelManifestPath and {SectionName}:PipelineProfilePath are configured together or not at all.");
        return problems;
    }
}
