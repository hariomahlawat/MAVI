using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>Where the bounded submission work of one hand-off spent its time (plan §14.1, F2 diagnostics).</summary>
public sealed record VisionFinalizationSubmissionTimings(
    TimeSpan Validation,
    TimeSpan PayloadEncoding,
    TimeSpan Persistence,
    TimeSpan Total);

/// <summary>
/// The outcome of a completion 3.1 submission (S1.4 B3 asynchronous finalization plan §5.2,
/// §5.3, §6). A success is either the durable hand-off (<see cref="WorkerContractRules.FinalizationStateFinalizing"/>,
/// first acceptance or its exact replay) or the exact replay of an already published job
/// (<see cref="WorkerContractRules.FinalizationStateCompleted"/>). It never claims publication
/// that has not happened.
/// </summary>
public sealed record VisionFinalizationSubmissionResult(
    bool IsSuccess,
    string? ErrorCode,
    string? State,
    Guid? ProcessingRunId,
    DateTimeOffset? AcceptedAtUtc,
    int TracksSubmitted,
    DateTimeOffset? CompletedAtUtc,
    VisionFinalizationSubmissionTimings? Timings)
{
    public static VisionFinalizationSubmissionResult Finalizing(
        Guid processingRunId, DateTimeOffset acceptedAtUtc, int tracksSubmitted, VisionFinalizationSubmissionTimings timings) =>
        new(true, null, WorkerContractRules.FinalizationStateFinalizing, processingRunId, acceptedAtUtc, tracksSubmitted, null, timings);

    public static VisionFinalizationSubmissionResult Completed(
        Guid processingRunId, DateTimeOffset acceptedAtUtc, int tracksSubmitted, DateTimeOffset completedAtUtc,
        VisionFinalizationSubmissionTimings timings) =>
        new(true, null, WorkerContractRules.FinalizationStateCompleted, processingRunId, acceptedAtUtc, tracksSubmitted, completedAtUtc, timings);

    public static VisionFinalizationSubmissionResult Failure(string code) =>
        new(false, code, null, null, null, 0, null, null);
}

/// <summary>
/// Completion 3.1: one PostgreSQL transaction that authenticates the worker's lease
/// capability, validates the body, retains the capability-free semantic payload and moves the
/// job <c>Leased → Finalizing</c>. It seals nothing, creates no Track/Observation/Artifact
/// row, allocates no visibility sequence and completes neither the run nor the video; that is
/// the platform finalizer's work (F3).
/// </summary>
public interface IVisionFinalizationSubmissionStore
{
    Task<VisionFinalizationSubmissionResult> SubmitAsync(
        Guid jobId,
        string workerId,
        string leaseToken,
        VisionJobCompleteRequest request,
        CancellationToken cancellationToken);
}
