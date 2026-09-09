using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Time;
using Mavi.Application.Modules.Cameras;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Modules.Media;

public sealed record ImportVideoCommand(
    Guid CameraId,
    DateTime RecordingStartLocal,
    string OriginalFileName,
    Stream Content);

public sealed record VideoImportResult(bool IsSuccess, VideoAsset? Video, string? ErrorCode)
{
    public static VideoImportResult Success(VideoAsset video) => new(true, video, null);
    public static VideoImportResult Failure(string errorCode) => new(false, null, errorCode);
}

public static class VideoImportErrorCodes
{
    public const string CameraNotFound = "camera_not_found";
    public const string CameraInactive = "camera_inactive";
    public const string InvalidRecordingTime = "invalid_recording_time";
    public const string FormatUnsupported = "video_format_unsupported";
    public const string MetadataInvalid = "video_metadata_invalid";
    public const string Duplicate = "video_duplicate";
    public const string InvalidFileName = "video_filename_invalid";
    public const string FileTooLarge = "video_file_too_large";
    public const string ContainerUnsupported = "video_container_unsupported";
}

public sealed class VideoImportService(
    ICameraRepository cameras,
    IVideoCatalog catalog,
    IMediaStore mediaStore,
    IVideoMetadataReader metadataReader,
    ITimeZoneService timeZones,
    TimeProvider timeProvider,
    IOptions<VideoImportOptions> options,
    ILogger<VideoImportService> logger)
{
    private static readonly Action<ILogger, string, Exception?> LogCleanupFailure =
        LoggerMessage.Define<string>(LogLevel.Error, new EventId(1, nameof(LogCleanupFailure)),
            "Failed to delete managed media {StorageKey} after an unsuccessful import.");

    // Import workflow
    public async Task<VideoImportResult> ImportAsync(ImportVideoCommand command, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(command);
        ArgumentNullException.ThrowIfNull(command.Content);
        var camera = await cameras.GetAsync(command.CameraId, cancellationToken);
        if (camera is null) return VideoImportResult.Failure(VideoImportErrorCodes.CameraNotFound);
        if (!camera.IsActive) return VideoImportResult.Failure(VideoImportErrorCodes.CameraInactive);

        if (!TryNormalizeFileName(command.OriginalFileName, out var fileName))
            return VideoImportResult.Failure(VideoImportErrorCodes.InvalidFileName);
        var extension = Path.GetExtension(fileName);
        if (!options.Value.AllowedExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase))
            return VideoImportResult.Failure(VideoImportErrorCodes.FormatUnsupported);
        if (command.RecordingStartLocal.Kind != DateTimeKind.Unspecified)
            return VideoImportResult.Failure(VideoImportErrorCodes.InvalidRecordingTime);

        DateTimeOffset recordingStartUtc;
        TimeSpan recordingOffset;
        try
        {
            if (timeZones.IsAmbiguous(command.RecordingStartLocal, camera.TimeZoneId) ||
                timeZones.IsInvalid(command.RecordingStartLocal, camera.TimeZoneId))
                return VideoImportResult.Failure(VideoImportErrorCodes.InvalidRecordingTime);
            recordingStartUtc = timeZones.ConvertLocalToUtc(command.RecordingStartLocal, camera.TimeZoneId);
            recordingOffset = timeZones.GetUtcOffset(command.RecordingStartLocal, camera.TimeZoneId);
        }
        catch (MaviTimeZoneException)
        {
            return VideoImportResult.Failure(VideoImportErrorCodes.InvalidRecordingTime);
        }

        var videoId = Guid.CreateVersion7();
        var localDate = command.RecordingStartLocal;
        var storageKey = $"source/{camera.Id:D}/{localDate:yyyy/MM/dd}/{videoId:D}.mp4".ToLowerInvariant();
        var mediaWritten = false;
        try
        {
            MediaWriteResult write;
            try
            {
                var boundedContent = new MaximumLengthReadStream(command.Content, options.Value.MaximumFileSizeBytes);
                write = await mediaStore.WriteAsync(storageKey, boundedContent, cancellationToken);
            }
            catch (VideoFileTooLargeException)
            {
                return VideoImportResult.Failure(VideoImportErrorCodes.FileTooLarge);
            }
            mediaWritten = true;
            VideoMetadata metadata;
            try
            {
                metadata = await metadataReader.ReadAsync(storageKey, cancellationToken);
            }
            catch (VideoMetadataException)
            {
                return VideoImportResult.Failure(VideoImportErrorCodes.MetadataInvalid);
            }
            if (!metadata.FormatName.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
                    .Contains("mp4", StringComparer.OrdinalIgnoreCase))
                return VideoImportResult.Failure(VideoImportErrorCodes.ContainerUnsupported);

            if (await catalog.FindSourceVideoBySha256Async(write.Sha256, cancellationToken) is not null)
                return VideoImportResult.Failure(VideoImportErrorCodes.Duplicate);

            var nowUtc = timeProvider.GetUtcNow();
            var artifact = Artifact.Create(ArtifactType.SourceVideo, storageKey, "video/mp4", write.SizeBytes, write.Sha256,
                createdAtUtc: nowUtc);
            var video = VideoAsset.Create(videoId, camera.Id, artifact.Id, fileName, recordingStartUtc,
                metadata.DurationMs, metadata.FrameRateNumerator, metadata.FrameRateDenominator,
                metadata.Width, metadata.Height, metadata.CodecName, TimestampSource.Manual, 1.0,
                camera.TimeZoneId, checked((int)recordingOffset.TotalMinutes), nowUtc);
            await catalog.AddAsync(artifact, video, cancellationToken);
            try
            {
                await catalog.SaveChangesAsync(cancellationToken);
            }
            catch (DuplicateSourceVideoException)
            {
                return VideoImportResult.Failure(VideoImportErrorCodes.Duplicate);
            }

            mediaWritten = false;
            return VideoImportResult.Success(video);
        }
        finally
        {
            if (mediaWritten)
            {
                try
                {
                    await mediaStore.DeleteAsync(storageKey, CancellationToken.None);
                }
                catch (Exception exception)
                {
                    LogCleanupFailure(logger, storageKey, exception);
                }
            }
        }
    }

    // Untrusted filename normalization
    private static bool TryNormalizeFileName(string? original, out string fileName)
    {
        fileName = string.Empty;
        if (string.IsNullOrWhiteSpace(original)) return false;
        var segments = original.Replace('\\', '/').Split('/');
        fileName = segments[^1].Trim();
        return fileName.Length is > 0 and <= 255 && fileName is not "." and not ".." &&
            !fileName.Any(char.IsControl);
    }
}
