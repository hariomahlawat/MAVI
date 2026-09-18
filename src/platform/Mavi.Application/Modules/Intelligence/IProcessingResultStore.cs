using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

public sealed record VisionCompletionResult(
    bool IsSuccess,
    string? ErrorCode,
    Guid? ProcessingRunId,
    int TracksAccepted,
    DateTimeOffset? CompletedAtUtc)
{
    public static VisionCompletionResult Success(Guid processingRunId, int tracksAccepted, DateTimeOffset completedAtUtc) =>
        new(true, null, processingRunId, tracksAccepted, completedAtUtc);

    public static VisionCompletionResult Failure(string code) =>
        new(false, code, null, 0, null);
}

public interface IProcessingResultStore
{
    Task<VisionCompletionResult> CompleteAsync(
        Guid jobId,
        string workerId,
        string leaseToken,
        VisionJobCompleteRequest request,
        CancellationToken cancellationToken);
}
