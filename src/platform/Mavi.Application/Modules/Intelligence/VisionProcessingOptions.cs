namespace Mavi.Application.Modules.Intelligence;

public sealed class VisionProcessingOptions
{
    public const string SectionName = "VisionProcessing";
    public string Pipeline { get; init; } = "phase1-detection-tracking";
    public string PipelineVersion { get; init; } = "phase1-v1";
    public int MaximumAttempts { get; init; } = 3;
    public int LeaseSeconds { get; init; } = 120;
    public int HeartbeatExtensionSeconds { get; init; } = 120;
}
