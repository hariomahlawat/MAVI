using Mavi.Domain.Common;

namespace Mavi.Domain.Media;

public sealed class VideoAsset
{
    // Construction
    private VideoAsset() { }

    public static VideoAsset Create(
        Guid cameraId,
        Guid sourceArtifactId,
        string originalFileName,
        DateTimeOffset recordingStartUtc,
        long durationMs,
        int frameRateNumerator,
        int frameRateDenominator,
        int width,
        int height,
        string? codec,
        TimestampSource timestampSource,
        double timestampConfidence,
        string recordingTimeZoneId = "UTC",
        int recordingUtcOffsetMinutes = 0,
        DateTimeOffset? importedAtUtc = null)
        => CreateCore(
            Guid.CreateVersion7(), cameraId, sourceArtifactId, originalFileName, recordingStartUtc,
            durationMs, frameRateNumerator, frameRateDenominator, width, height, codec,
            timestampSource, timestampConfidence, recordingTimeZoneId, recordingUtcOffsetMinutes, importedAtUtc);

    public static VideoAsset Create(
        Guid id,
        Guid cameraId,
        Guid sourceArtifactId,
        string originalFileName,
        DateTimeOffset recordingStartUtc,
        long durationMs,
        int frameRateNumerator,
        int frameRateDenominator,
        int width,
        int height,
        string? codec,
        TimestampSource timestampSource,
        double timestampConfidence,
        string recordingTimeZoneId = "UTC",
        int recordingUtcOffsetMinutes = 0,
        DateTimeOffset? importedAtUtc = null)
        => CreateCore(
            id, cameraId, sourceArtifactId, originalFileName, recordingStartUtc,
            durationMs, frameRateNumerator, frameRateDenominator, width, height, codec,
            timestampSource, timestampConfidence, recordingTimeZoneId, recordingUtcOffsetMinutes, importedAtUtc);

    private static VideoAsset CreateCore(
        Guid id,
        Guid cameraId,
        Guid sourceArtifactId,
        string originalFileName,
        DateTimeOffset recordingStartUtc,
        long durationMs,
        int frameRateNumerator,
        int frameRateDenominator,
        int width,
        int height,
        string? codec,
        TimestampSource timestampSource,
        double timestampConfidence,
        string recordingTimeZoneId,
        int recordingUtcOffsetMinutes,
        DateTimeOffset? importedAtUtc)
    {
        if (id == Guid.Empty || id.Version != 7)
            throw new DomainValidationException("video_id_invalid", "Video asset ID must be a non-empty UUID version 7.");
        if (cameraId == Guid.Empty || sourceArtifactId == Guid.Empty)
            throw new DomainValidationException("video_reference_required", "Camera and source artifact are required.");
        if (string.IsNullOrWhiteSpace(originalFileName) || originalFileName.Trim().Length > 255)
            throw new DomainValidationException("video_filename_invalid", "A valid original filename is required.");
        if (durationMs <= 0)
            throw new DomainValidationException("video_duration_invalid", "Video duration must be positive.");
        if (frameRateNumerator <= 0 || frameRateDenominator <= 0)
            throw new DomainValidationException("video_frame_rate_invalid", "Frame rate values must be positive.");
        if (width <= 0 || height <= 0)
            throw new DomainValidationException("video_dimensions_invalid", "Video dimensions must be positive.");
        if (codec?.Length > 64)
            throw new DomainValidationException("video_codec_too_long", "Codec must not exceed 64 characters.");
        if (!double.IsFinite(timestampConfidence) || timestampConfidence is < 0 or > 1)
            throw new DomainValidationException("video_timestamp_confidence_invalid", "Timestamp confidence must be between zero and one.");
        if (string.IsNullOrWhiteSpace(recordingTimeZoneId) || recordingTimeZoneId.Trim().Length > 64)
            throw new DomainValidationException("video_recording_timezone_invalid", "Recording timezone is required.");
        if (recordingUtcOffsetMinutes is < -840 or > 840)
            throw new DomainValidationException("video_recording_offset_invalid", "Recording UTC offset is outside supported bounds.");

        var startUtc = recordingStartUtc.ToUniversalTime();
        return new VideoAsset
        {
            Id = id,
            CameraId = cameraId,
            SourceArtifactId = sourceArtifactId,
            OriginalFileName = originalFileName.Trim(),
            SourceType = VideoSourceType.UploadedFile,
            RecordingStartUtc = startUtc,
            RecordingTimeZoneId = recordingTimeZoneId.Trim(),
            RecordingUtcOffsetMinutes = recordingUtcOffsetMinutes,
            RecordingEndUtc = startUtc.AddMilliseconds(durationMs),
            DurationMs = durationMs,
            FrameRateNumerator = frameRateNumerator,
            FrameRateDenominator = frameRateDenominator,
            Width = width,
            Height = height,
            Codec = codec,
            TimestampSource = timestampSource,
            TimestampConfidence = timestampConfidence,
            ProcessingStatus = VideoProcessingStatus.NotQueued,
            ImportedAtUtc = (importedAtUtc ?? DateTimeOffset.UtcNow).ToUniversalTime(),
        };
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid CameraId { get; private set; }
    public Guid SourceArtifactId { get; private set; }
    public string OriginalFileName { get; private set; } = string.Empty;
    public VideoSourceType SourceType { get; private set; }
    public string? SourceReference { get; private set; }
    public DateTimeOffset RecordingStartUtc { get; private set; }
    public string RecordingTimeZoneId { get; private set; } = string.Empty;
    public int RecordingUtcOffsetMinutes { get; private set; }
    public DateTimeOffset RecordingEndUtc { get; private set; }
    public long DurationMs { get; private set; }
    public int FrameRateNumerator { get; private set; }
    public int FrameRateDenominator { get; private set; }
    public int Width { get; private set; }
    public int Height { get; private set; }
    public string? Codec { get; private set; }
    public TimestampSource TimestampSource { get; private set; }
    public double TimestampConfidence { get; private set; }
    public VideoProcessingStatus ProcessingStatus { get; private set; }
    public DateTimeOffset ImportedAtUtc { get; private set; }
}
