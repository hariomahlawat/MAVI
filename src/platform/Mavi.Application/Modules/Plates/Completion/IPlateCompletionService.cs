using Mavi.Contracts.Worker.Plates;

namespace Mavi.Application.Modules.Plates.Completion;

public enum PlateCompletionStatus
{
    /// <summary>Published now, or an exact replay of what was published.</summary>
    Completed,
    /// <summary>Published as history: an identity that is not the preferred one.</summary>
    Superseded,
    Refused,
}

/// <summary>Wall-clock of each phase of one publication, for the 10,000-Track measurement.</summary>
public sealed record PlateCompletionTimings(
    TimeSpan PhaseA,
    TimeSpan ArtefactValidation,
    TimeSpan PhaseB,
    TimeSpan PhaseC,
    TimeSpan PhaseCRowWrites,
    TimeSpan BarrierHold);

public sealed record PlateCompletionResult(
    PlateCompletionStatus Status,
    string? Code,
    int HttpStatus,
    Guid? ProcessingRunId,
    DateTimeOffset? CompletedAtUtc,
    int TracksAnalysed,
    int TracksUnavailable,
    bool IsReplay,
    PlateCompletionTimings? Timings = null)
{
    public static PlateCompletionResult Refused(int httpStatus, string code) =>
        new(PlateCompletionStatus.Refused, code, httpStatus, null, null, 0, 0, false);
}

/// <summary>
/// The three-phase publication protocol of one plate completion (ADR-013 implementation amendment
/// 2026-09-28, item 4, applied by item 11): fenced validation, idempotent content-addressed seal outside
/// any transaction, then re-fence and one atomic publication transaction.
/// </summary>
public interface IPlateCompletionService
{
    Task<PlateCompletionResult> CompleteAsync(Guid analysisId, string leaseToken, PlateCompleteRequest request, CancellationToken cancellationToken);
}
