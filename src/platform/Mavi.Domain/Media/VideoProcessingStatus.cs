namespace Mavi.Domain.Media;

public enum VideoProcessingStatus
{
    NotQueued,
    Queued,
    Processing,
    Processed,
    Failed,
}
