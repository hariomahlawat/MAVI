using Mavi.Domain.Common;
using Mavi.Domain.Media;

namespace Mavi.Domain.Tests;

public sealed class VideoAssetTests
{
    [Fact]
    public void CreateDerivesRecordingEndFromDuration()
    {
        var start = new DateTimeOffset(2026, 9, 8, 8, 30, 0, TimeSpan.Zero);
        var asset = VideoAsset.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), "gate01.mp4", start,
            90_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1.0);

        Assert.Equal(start.AddMilliseconds(90_000), asset.RecordingEndUtc);
        Assert.Equal(VideoProcessingStatus.NotQueued, asset.ProcessingStatus);
    }

    [Fact]
    public void CreateRejectsZeroDuration()
    {
        Assert.Throws<DomainValidationException>(() => VideoAsset.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), "bad.mp4", DateTimeOffset.UtcNow,
            0, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1.0));
    }

    [Theory]
    [InlineData("/absolute/video.mp4")]
    [InlineData("../escape/video.mp4")]
    [InlineData("source\\video.mp4")]
    [InlineData("C:/video.mp4")]
    public void ArtifactRejectsUnsafeStorageKey(string storageKey)
    {
        Assert.Throws<DomainValidationException>(() => Artifact.Create(
            ArtifactType.SourceVideo, storageKey, "video/mp4", 1, new string('a', 64)));
    }
}
