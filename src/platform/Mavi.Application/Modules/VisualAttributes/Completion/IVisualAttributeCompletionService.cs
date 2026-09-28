using Mavi.Contracts.Worker.Attributes;

namespace Mavi.Application.Modules.VisualAttributes.Completion;

public enum VisualAttributeCompletionStatus
{
    /// <summary>Published now, or an exact replay of what was published.</summary>
    Completed,
    /// <summary>Published as history: an identity that is not the preferred one (plan §4).</summary>
    Superseded,
    Refused,
}

/// <summary>Wall-clock of each phase, for the 10,000-Track measurement (plan §13).</summary>
public sealed record VisualAttributeCompletionTimings(
    TimeSpan PhaseA,
    TimeSpan ArtefactValidation,
    TimeSpan PhaseB,
    TimeSpan PhaseC,
    TimeSpan PhaseCRowWrites,
    TimeSpan BarrierHold);

public sealed record VisualAttributeCompletionResult(
    VisualAttributeCompletionStatus Status,
    string? Code,
    int HttpStatus,
    Guid? ProcessingRunId,
    DateTimeOffset? CompletedAtUtc,
    int TracksAnalysed,
    int TracksUnavailable,
    bool IsReplay,
    VisualAttributeCompletionTimings? Timings)
{
    public static VisualAttributeCompletionResult Refused(int httpStatus, string code) =>
        new(VisualAttributeCompletionStatus.Refused, code, httpStatus, null, null, 0, 0, false, null);
}

/// <summary>
/// The three-phase publication protocol (S2b plan §13; ADR-013 implementation amendment
/// 2026-09-28, item 4): fenced validation, idempotent content-addressed seal outside any
/// transaction, then re-fence and one atomic publication transaction.
/// </summary>
public interface IVisualAttributeCompletionService
{
    Task<VisualAttributeCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, VisualAttributeCompleteRequest request, CancellationToken cancellationToken);
}
