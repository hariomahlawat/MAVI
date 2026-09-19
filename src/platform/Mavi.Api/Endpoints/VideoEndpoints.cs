using Mavi.Application.Modules.Media;
using Mavi.Contracts.Api.Videos;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;
using Mavi.Application.Modules.Evidence;

namespace Mavi.Api.Endpoints;

public static class VideoEndpoints
{
    // Route registration
    public static IEndpointRouteBuilder MapVideoEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var videos = endpoints.MapGroup("/api/videos");
        videos.MapPost("/import", ImportAsync).DisableAntiforgery();
        videos.MapGet("/", ListAsync);
        videos.MapGet("/{id:guid}", GetAsync).WithName("GetVideo");
        videos.MapPost("/{id:guid}/process", ProcessAsync);
        videos.MapGet("/{id:guid}/processing", ProcessingAsync);
        videos.MapGet("/{id:guid}/content", ContentAsync);
        return endpoints;
    }

    // Commands
    private static async Task<IResult> ImportAsync(
        [FromForm] Guid cameraId,
        [FromForm] DateTime recordingStartLocal,
        IFormFile file,
        VideoImportService service,
        IOptions<VideoImportOptions> options,
        CancellationToken cancellationToken)
    {
        if (file.Length > options.Value.MaximumFileSizeBytes)
            return Problem(StatusCodes.Status400BadRequest, "video_file_too_large", "The uploaded video exceeds the configured limit.");

        try
        {
            await using var content = file.OpenReadStream();
            var result = await service.ImportAsync(
                new ImportVideoCommand(cameraId, recordingStartLocal, file.FileName, content), cancellationToken);
            if (!result.IsSuccess) return Error(result);
            var response = ToResponse(result.Video!);
            return Results.Created($"/api/videos/{response.Id}", response);
        }
        catch (DomainValidationException)
        {
            return Problem(StatusCodes.Status400BadRequest, VideoImportErrorCodes.MetadataInvalid,
                "The video metadata is invalid.");
        }
    }

    // Queries
    private static async Task<IResult> ProcessAsync(Guid id, IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        var result = await orchestrator.QueueAsync(id, cancellationToken);
        if (result.IsSuccess) return Results.Accepted($"/api/videos/{id}/processing", new QueueProcessingResponse(result.ProcessingRunId!.Value));
        return result.ErrorCode == "video_not_found"
            ? Problem(404, result.ErrorCode, "Video was not found.")
            : Problem(409, result.ErrorCode!, "Video processing is already active.");
    }

    private static async Task<IResult> ProcessingAsync(Guid id, IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        var result = await orchestrator.GetStatusAsync(id, cancellationToken);
        if (!result.Found)
            return Problem(404, "video_not_found", "Video was not found.");

        var latestRun = result.LatestRun is null
            ? null
            : new ProcessingRunStatusResponse(
                result.LatestRun.ProcessingRunId,
                result.LatestRun.Status,
                result.LatestRun.Pipeline,
                result.LatestRun.PipelineVersion,
                result.LatestRun.WorkerId,
                result.LatestRun.QueuedAtUtc,
                result.LatestRun.StartedAtUtc,
                result.LatestRun.CompletedAtUtc,
                result.LatestRun.ProgressPercent,
                result.LatestRun.AttemptCount,
                result.LatestRun.FailureCode,
                result.LatestRun.FramesProcessed,
                result.LatestRun.TracksCreated);

        return Results.Ok(new ProcessingStatusResponse(result.VideoStatus, latestRun));
    }

    private static async Task<IResult> ContentAsync(
        Guid id,
        HttpContext context,
        ContentReadService service,
        CancellationToken cancellationToken)
    {
        var result = await service.OpenVideoAsync(id, cancellationToken);
        if (!result.IsSuccess)
        {
            return Problem(
                result.IsNotFound ? 404 : 500,
                result.ErrorCode!,
                result.IsNotFound
                    ? "Video was not found."
                    : "Video content is unavailable.");
        }

        return ArtifactEndpoints.StreamResult(
            context,
            result.Descriptor!,
            result.Stream!);
    }

    private static async Task<IResult> GetAsync(Guid id, IVideoCatalog catalog, CancellationToken cancellationToken)
    {
        var video = await catalog.GetAsync(id, cancellationToken);
        return video is null
            ? Problem(StatusCodes.Status404NotFound, "video_not_found", "Video was not found.")
            : Results.Ok(ToResponse(video));
    }

    private static async Task<IResult> ListAsync(IVideoCatalog catalog, CancellationToken cancellationToken) =>
        Results.Ok((await catalog.ListAsync(cancellationToken)).Select(ToResponse));

    // Safe API mapping
    private static IResult Error(VideoImportResult result) => result.ErrorCode switch
    {
        VideoImportErrorCodes.CameraNotFound => Problem(404, result.ErrorCode, "Camera was not found."),
        VideoImportErrorCodes.CameraInactive => Problem(409, result.ErrorCode, "Camera is inactive."),
        VideoImportErrorCodes.Duplicate when result.ExistingVideoAssetId is Guid existingId =>
            Problem(409, result.ErrorCode, "Video has already been imported.",
                new Dictionary<string, object?> { ["videoAssetId"] = existingId }),
        VideoImportErrorCodes.Duplicate =>
            Problem(500, "video_duplicate_unresolved", "The existing imported video could not be resolved."),
        VideoImportErrorCodes.InvalidRecordingTime => Problem(400, result.ErrorCode, "Recording time is invalid or ambiguous."),
        VideoImportErrorCodes.FormatUnsupported => Problem(400, result.ErrorCode, "Video format is unsupported."),
        VideoImportErrorCodes.ContainerUnsupported => Problem(400, result.ErrorCode, "Video container is unsupported."),
        VideoImportErrorCodes.FileTooLarge => Problem(400, result.ErrorCode, "The uploaded video exceeds the configured limit."),
        VideoImportErrorCodes.InvalidFileName => Problem(400, result.ErrorCode, "Video filename is invalid."),
        _ => Problem(400, VideoImportErrorCodes.MetadataInvalid, "Video metadata is invalid."),
    };

    private static VideoAssetResponse ToResponse(VideoAsset video) => new(
        video.Id, video.CameraId, video.OriginalFileName, video.RecordingStartUtc, video.RecordingEndUtc,
        video.RecordingTimeZoneId, video.RecordingUtcOffsetMinutes,
        video.DurationMs, video.Width, video.Height, video.FrameRateNumerator, video.FrameRateDenominator,
        video.Codec, video.ProcessingStatus.ToString(), video.ImportedAtUtc);

    private static IResult Problem(
        int statusCode,
        string code,
        string detail,
        IReadOnlyDictionary<string, object?>? additionalExtensions = null)
    {
        var extensions = new Dictionary<string, object?> { ["code"] = code };
        if (additionalExtensions is not null)
        {
            foreach (var (key, value) in additionalExtensions)
                extensions[key] = value;
        }

        return Results.Problem(statusCode: statusCode, detail: detail, extensions: extensions);
    }
}
