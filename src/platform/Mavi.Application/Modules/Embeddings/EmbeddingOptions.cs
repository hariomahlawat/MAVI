using Mavi.Domain.Embeddings;

namespace Mavi.Application.Modules.Embeddings;

/// <summary>
/// The platform's embedding lifecycle configuration (PoC S4; ADR-021). Nothing is configured by default: with
/// no model manifest and pipeline profile the release expects no embeddings (<c>NotConfigured</c>), queues and
/// leases nothing, and similarity endpoints answer <c>notConfigured</c>.
/// </summary>
public sealed class EmbeddingOptions
{
    public const string SectionName = "Embeddings";
    public const int MinimumLeaseSeconds = 60;
    public const int MaximumReanalysisRunsCeiling = 100;

    /// <summary>Runs the authority loop: activation, queueing, the deadline and exhaustion sweeps.</summary>
    public bool Enabled { get; init; }

    /// <summary>The committed model manifest (manifest v2, capability <c>embedding</c>).</summary>
    public string ModelManifestPath { get; init; } = string.Empty;

    /// <summary>The embedding pipeline profile (<c>mavi-embedding-pipeline-v1</c>).</summary>
    public string PipelineProfilePath { get; init; } = string.Empty;

    public int LeaseSeconds { get; init; } = 120;
    public int HeartbeatExtensionSeconds { get; init; } = 120;
    public int MaximumAttempts { get; init; } = 3;
    public int MaximumAnalysisDurationSeconds { get; init; } = 6 * 3600;
    public int ReconcileIntervalSeconds { get; init; } = 15;
    public int ReconcileBatchSize { get; init; } = 100;
    public int TextQueryLeaseSeconds { get; init; } = 30;

    /// <summary>How long an appearance search waits for a new text's vector before answering 503 (ADR-021 §4).</summary>
    public int AppearanceQueryWaitMilliseconds { get; init; } = 10_000;

    public int MaximumRunsPerReanalysisRequest { get; init; } = 100;

    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ModelManifestPath) || !string.IsNullOrWhiteSpace(PipelineProfilePath);

    public EmbeddingLeasePolicy LeasePolicy => new(
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
        if (TextQueryLeaseSeconds is < 5 or > 600)
            problems.Add($"{SectionName}:TextQueryLeaseSeconds must be between 5 and 600.");
        if (AppearanceQueryWaitMilliseconds is < 0 or > 60_000)
            problems.Add($"{SectionName}:AppearanceQueryWaitMilliseconds must be between 0 and 60000.");
        if (MaximumRunsPerReanalysisRequest is < 1 or > MaximumReanalysisRunsCeiling)
            problems.Add($"{SectionName}:MaximumRunsPerReanalysisRequest must be between 1 and {MaximumReanalysisRunsCeiling}.");
        if (string.IsNullOrWhiteSpace(ModelManifestPath) != string.IsNullOrWhiteSpace(PipelineProfilePath))
            problems.Add($"{SectionName}:ModelManifestPath and {SectionName}:PipelineProfilePath are configured together or not at all.");
        return problems;
    }
}
