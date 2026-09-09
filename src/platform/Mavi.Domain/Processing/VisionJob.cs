using Mavi.Domain.Common;

namespace Mavi.Domain.Processing;

public sealed class VisionJob
{
    // Construction
    private VisionJob() { }

    public static VisionJob Create(Guid processingRunId, string pipeline, DateTimeOffset nowUtc)
    {
        if (processingRunId == Guid.Empty || string.IsNullOrWhiteSpace(pipeline) || pipeline.Trim().Length > 64) throw Invalid();
        var now = nowUtc.ToUniversalTime();
        return new VisionJob { Id = Guid.CreateVersion7(), ProcessingRunId = processingRunId, Pipeline = pipeline.Trim(), Status = VisionJobStatus.Queued, CreatedAtUtc = now, AvailableAtUtc = now };
    }

    // Leasing
    public bool CanLease(DateTimeOffset nowUtc, int maximumAttempts) => maximumAttempts >= 1 && AttemptCount < maximumAttempts &&
        ((Status == VisionJobStatus.Queued && AvailableAtUtc <= nowUtc) || (Status == VisionJobStatus.Leased && LeaseExpiresAtUtc <= nowUtc));

    public void Lease(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, TimeSpan duration, int maximumAttempts)
    {
        if (!CanLease(nowUtc, maximumAttempts) || string.IsNullOrWhiteSpace(workerId) || workerId.Trim().Length > 128 ||
            leaseTokenHash is not { Length: 32 } || duration <= TimeSpan.Zero) throw Invalid();
        Status = VisionJobStatus.Leased; LeaseOwner = workerId.Trim(); LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(duration); AttemptCount++;
        ProgressPercent = 0; LastHeartbeatUtc = null;
    }

    public void Heartbeat(string workerId, bool leaseTokenMatches, double progressPercent, DateTimeOffset nowUtc, TimeSpan extension)
    {
        RequireValidLease(workerId, leaseTokenMatches, nowUtc);
        if (!double.IsFinite(progressPercent) || progressPercent is < 0 or > 100 || extension <= TimeSpan.Zero) throw Invalid();
        if (progressPercent < ProgressPercent)
            throw new DomainValidationException("vision_job_progress_regression", "Vision job progress cannot decrease.");
        ProgressPercent = progressPercent; LastHeartbeatUtc = nowUtc.ToUniversalTime(); LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(extension);
    }

    public void Complete(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc)
    {
        RequireValidLease(workerId, leaseTokenMatches, nowUtc); Status = VisionJobStatus.Completed; ProgressPercent = 100; CompletedAtUtc = nowUtc.ToUniversalTime();
    }

    public void Fail(string workerId, bool leaseTokenMatches, string code, string? details, DateTimeOffset nowUtc)
    {
        RequireValidLease(workerId, leaseTokenMatches, nowUtc);
        if (string.IsNullOrWhiteSpace(code) || code.Length > 64 || details?.Length > 4000) throw Invalid();
        Status = VisionJobStatus.Failed; FailureCode = code; FailureDetails = details; CompletedAtUtc = nowUtc.ToUniversalTime();
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public string Pipeline { get; private set; } = string.Empty;
    public VisionJobStatus Status { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset AvailableAtUtc { get; private set; }
    public string? LeaseOwner { get; private set; }
    public byte[]? LeaseTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public int AttemptCount { get; private set; }
    public double ProgressPercent { get; private set; }
    public DateTimeOffset? LastHeartbeatUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public string? FailureCode { get; private set; }
    public string? FailureDetails { get; private set; }

    // Validation
    private void RequireValidLease(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc)
    {
        if (Status != VisionJobStatus.Leased || !string.Equals(LeaseOwner, workerId, StringComparison.Ordinal) ||
            !leaseTokenMatches || LeaseExpiresAtUtc <= nowUtc.ToUniversalTime()) throw Invalid();
    }

    public void Exhaust(DateTimeOffset nowUtc)
    {
        if (Status is not (VisionJobStatus.Queued or VisionJobStatus.Leased)) throw Invalid();
        Status = VisionJobStatus.Failed; FailureCode = "vision_job_attempts_exhausted";
        FailureDetails = null; CompletedAtUtc = nowUtc.ToUniversalTime();
        LeaseOwner = null; LeaseTokenHash = null; LeaseExpiresAtUtc = null; LastHeartbeatUtc = null;
    }

    private static DomainValidationException Invalid() => new("vision_job_transition_invalid", "The vision job operation is invalid.");
}
