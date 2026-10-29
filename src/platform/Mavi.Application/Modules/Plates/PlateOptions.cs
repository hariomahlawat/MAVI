using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Plates;

/// <summary>
/// The platform's plate lifecycle configuration (Stage 4 plan §2.2, §5.3; ADR-013 implementation
/// amendment 2026-10-13, item 11).
/// </summary>
/// <remarks>
/// Nothing is configured by default: with no Component Binding and pipeline profile path the release
/// expects no plate analysis (<c>NotConfigured</c>), queues nothing and leases nothing. The lease
/// bounds follow the attribute plane's (a worker renews at <c>min(interval, remaining − margin)</c>
/// and never below <see cref="MinimumLeaseSeconds"/>).
/// </remarks>
public sealed class PlateOptions
{
    public const string SectionName = "Plates";
    public const int MinimumLeaseSeconds = 60;
    /// <summary>The plan's bound on one explicit re-analysis request (Stage 4 plan §2.2: at most 100 runs).</summary>
    public const int MaximumReanalysisRunsCeiling = 100;

    /// <summary>
    /// Plate analysis of new work: the preferred identity's activation and the queueing of eligible runs. Off, nothing
    /// new is activated or queued, but the authority loop keeps running: the deadline and attempts-exhausted sweep and
    /// the plate staging janitor govern every unit already queued or leased, so disabling plates never strands a lease
    /// or its staging (PoC S3, closing the Stage-4 PR-3 limit "<c>Plates:Enabled</c> off stops the whole authority
    /// loop"). Already-queued units are still served to a READY worker.
    /// </summary>
    public bool Enabled { get; init; }

    /// <summary>The release Component Binding the plates worker composes from.</summary>
    public string ComponentBindingPath { get; init; } = string.Empty;

    /// <summary>The plate pipeline profile; its siblings are read from the same directory.</summary>
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

    /// <summary>The most runs one explicit re-analysis request may queue (plan §2.2: bounded, never automatic).</summary>
    public int MaximumRunsPerReanalysisRequest { get; init; } = 100;

    /// <summary>
    /// The interim authorisation of <c>POST /api/plates/reanalysis</c> (PoC S3; replaced by ADR-010 operator identity in
    /// S11-min): the lowercase SHA-256 of the operator key a request must present in
    /// <see cref="ReanalysisOperatorKeyHeader"/>. Empty — the default — refuses every request (fails closed); the key
    /// itself is never configured, logged or stored by the platform.
    /// </summary>
    public string ReanalysisOperatorKeySha256 { get; init; } = string.Empty;

    /// <summary>The request header carrying the re-analysis operator key.</summary>
    public const string ReanalysisOperatorKeyHeader = "X-Mavi-Operator-Key";

    public bool IsReanalysisAuthorisationConfigured => !string.IsNullOrEmpty(ReanalysisOperatorKeySha256);

    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ComponentBindingPath) || !string.IsNullOrWhiteSpace(PipelineProfilePath);

    public PlateLeasePolicy LeasePolicy => new(
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
        if (MaximumRunsPerReanalysisRequest is < 1 or > MaximumReanalysisRunsCeiling)
            problems.Add($"{SectionName}:MaximumRunsPerReanalysisRequest must be between 1 and {MaximumReanalysisRunsCeiling}.");
        if (string.IsNullOrWhiteSpace(ComponentBindingPath) != string.IsNullOrWhiteSpace(PipelineProfilePath))
            problems.Add($"{SectionName}:ComponentBindingPath and {SectionName}:PipelineProfilePath are configured together or not at all.");
        if (IsReanalysisAuthorisationConfigured &&
            (ReanalysisOperatorKeySha256.Length != 64 || !ReanalysisOperatorKeySha256.All(char.IsAsciiHexDigitLower)))
            problems.Add($"{SectionName}:ReanalysisOperatorKeySha256 must be empty or a lowercase SHA-256 (64 hexadecimal characters).");
        return problems;
    }
}
