namespace Mavi.Domain.Media;

public enum TimestampSource
{
    Manual,
    VideoMetadata,
    FilenamePattern,
    VmsMetadata,
    StreamTimestamp,
    SystemClockDerived,
}
