using Mavi.Domain.Common;
using Mavi.Domain.Media;

namespace Mavi.Domain.Tests;

public sealed class VideoAssetTests
{
    // Identifier creation
    [Fact]
    public void CreateGeneratesVersionSevenIdentifier()
    {
        var asset = CreateVideoAsset();

        Assert.Equal(7, asset.Id.Version);
    }

    [Fact]
    public void CreateWithExplicitIdentifierPreservesVersionSevenIdentifier()
    {
        var id = Guid.CreateVersion7();

        var asset = CreateVideoAsset(id);

        Assert.Equal(id, asset.Id);
    }

    [Fact]
    public void CreateWithExplicitIdentifierRejectsEmptyIdentifier()
    {
        var exception = Assert.Throws<DomainValidationException>(() => CreateVideoAsset(Guid.Empty));

        Assert.Equal("video_id_invalid", exception.Code);
    }

    [Fact]
    public void CreateWithExplicitIdentifierRejectsNonVersionSevenIdentifier()
    {
        var exception = Assert.Throws<DomainValidationException>(() => CreateVideoAsset(Guid.NewGuid()));

        Assert.Equal("video_id_invalid", exception.Code);
    }

    // Recording metadata
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

    // Test data
    private static VideoAsset CreateVideoAsset(Guid? id = null)
    {
        var cameraId = Guid.CreateVersion7();
        var artifactId = Guid.CreateVersion7();
        var start = new DateTimeOffset(2026, 9, 8, 8, 30, 0, TimeSpan.Zero);

        return id.HasValue
            ? VideoAsset.Create(
                id.Value, cameraId, artifactId, "gate01.mp4", start,
                90_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1.0)
            : VideoAsset.Create(
                cameraId, artifactId, "gate01.mp4", start,
                90_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1.0);
    }
}
