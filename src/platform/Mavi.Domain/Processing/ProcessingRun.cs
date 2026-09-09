using Mavi.Domain.Common;

namespace Mavi.Domain.Processing;

public sealed class ProcessingRun
{
    // Construction
    private ProcessingRun() { }

    public static ProcessingRun Create(Guid videoAssetId, string pipelineVersion, string configurationJson, DateTimeOffset nowUtc)
    {
        if (videoAssetId == Guid.Empty) throw Invalid("processing_video_required");
        if (string.IsNullOrWhiteSpace(pipelineVersion) || pipelineVersion.Trim().Length > 64) throw Invalid("processing_pipeline_invalid");
        if (string.IsNullOrWhiteSpace(configurationJson)) throw Invalid("processing_configuration_required");
        return new ProcessingRun
        {
            Id = Guid.CreateVersion7(), VideoAssetId = videoAssetId, Status = ProcessingRunStatus.Queued,
            PipelineVersion = pipelineVersion.Trim(), ConfigurationJson = configurationJson,
            QueuedAtUtc = nowUtc.ToUniversalTime(),
        };
    }

    // State transitions
    public void MarkRunning(string workerId, DateTimeOffset startedAtUtc)
    {
        if (Status != ProcessingRunStatus.Queued || !IsCanonicalWorkerId(workerId)) throw Invalid("processing_transition_invalid");
        Status = ProcessingRunStatus.Running; WorkerId = workerId; StartedAtUtc = startedAtUtc.ToUniversalTime();
    }

    public void AssignLease(string workerId, DateTimeOffset nowUtc)
    {
        if (!IsCanonicalWorkerId(workerId) ||
            Status is ProcessingRunStatus.Completed or ProcessingRunStatus.Failed or ProcessingRunStatus.Cancelled)
            throw Invalid("processing_transition_invalid");
        if (Status == ProcessingRunStatus.Queued)
        {
            Status = ProcessingRunStatus.Running;
            StartedAtUtc = nowUtc.ToUniversalTime();
        }
        WorkerId = workerId;
    }

    public void MarkCompleted(long framesProcessed, int tracksCreated, long durationMs, DateTimeOffset completedAtUtc)
    {
        if (Status != ProcessingRunStatus.Running || framesProcessed < 0 || tracksCreated < 0 || durationMs < 0) throw Invalid("processing_transition_invalid");
        Status = ProcessingRunStatus.Completed; FramesProcessed = framesProcessed; TracksCreated = tracksCreated;
        ProcessingDurationMs = durationMs; CompletedAtUtc = completedAtUtc.ToUniversalTime();
    }

    public void MarkFailed(string errorCode, string? details, DateTimeOffset failedAtUtc)
    {
        if (Status is ProcessingRunStatus.Completed or ProcessingRunStatus.Cancelled || string.IsNullOrWhiteSpace(errorCode)) throw Invalid("processing_transition_invalid");
        if (errorCode.Length > 64 || details?.Length > 4000) throw Invalid("processing_failure_invalid");
        Status = ProcessingRunStatus.Failed; ErrorCode = errorCode; ErrorDetails = details;
        CompletedAtUtc = failedAtUtc.ToUniversalTime();
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid VideoAssetId { get; private set; }
    public ProcessingRunStatus Status { get; private set; }
    public string PipelineVersion { get; private set; } = string.Empty;
    public string? DetectorName { get; private set; }
    public string? DetectorVersion { get; private set; }
    public string? TrackerName { get; private set; }
    public string? TrackerVersion { get; private set; }
    public string ConfigurationJson { get; private set; } = string.Empty;
    public string? WorkerId { get; private set; }
    public DateTimeOffset QueuedAtUtc { get; private set; }
    public DateTimeOffset? StartedAtUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public long FramesProcessed { get; private set; }
    public int TracksCreated { get; private set; }
    public long? ProcessingDurationMs { get; private set; }
    public string? ErrorCode { get; private set; }
    public string? ErrorDetails { get; private set; }

    private static bool IsCanonicalWorkerId(string workerId) =>
        !string.IsNullOrWhiteSpace(workerId) && workerId.Length <= 128 &&
        string.Equals(workerId, workerId.Trim(), StringComparison.Ordinal);

    private static DomainValidationException Invalid(string code) => new(code, "The processing run operation is invalid.");
}
