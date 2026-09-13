using Mavi.Application.Abstractions.Storage;

namespace Mavi.Application.Modules.Evidence;

public sealed record OpenContentResult(
    bool IsSuccess,
    ContentDescriptor? Descriptor,
    Stream? Stream,
    string? ErrorCode)
{
    public static OpenContentResult NotFound(string code) => new(false, null, null, code);
    public static OpenContentResult Unavailable(ContentDescriptor descriptor, string code) =>
        new(false, descriptor, null, code);
    public static OpenContentResult Success(ContentDescriptor descriptor, Stream stream) =>
        new(true, descriptor, stream, null);
}

public sealed class ContentReadService(
    IContentCatalog catalog,
    IMediaStore mediaStore,
    IAcceptedEvidenceReader evidenceReader)
{
    public async Task<OpenContentResult> OpenVideoAsync(
        Guid videoAssetId,
        CancellationToken cancellationToken)
    {
        if (videoAssetId == Guid.Empty)
            return OpenContentResult.NotFound("video_not_found");

        var descriptor = await catalog.GetVideoContentAsync(videoAssetId, cancellationToken);
        if (descriptor is null)
            return OpenContentResult.NotFound("video_not_found");

        return await OpenAsync(
            descriptor,
            "video_content_unavailable",
            cancellationToken);
    }

    public async Task<OpenContentResult> OpenEvidenceAsync(
        Guid artifactId,
        CancellationToken cancellationToken)
    {
        if (artifactId == Guid.Empty)
            return OpenContentResult.NotFound("artifact_not_found");

        var descriptor = await catalog.GetEvidenceContentAsync(artifactId, cancellationToken);
        if (descriptor is null)
            return OpenContentResult.NotFound("artifact_not_found");

        return await OpenAsync(
            descriptor,
            "artifact_content_unavailable",
            cancellationToken);
    }

    private async Task<OpenContentResult> OpenAsync(
        ContentDescriptor descriptor,
        string unavailableCode,
        CancellationToken cancellationToken)
    {
        if (!DescriptorIsValid(descriptor))
            return OpenContentResult.Unavailable(descriptor, unavailableCode);

        Stream? stream = null;
        try
        {
            stream = descriptor.StorageKind switch
            {
                ContentStorageKind.ManagedMedia =>
                    await mediaStore.OpenReadAsync(descriptor.StorageKey, cancellationToken),
                ContentStorageKind.AcceptedEvidence =>
                    await evidenceReader.OpenReadAsync(descriptor.StorageKey, cancellationToken),
                _ => throw new InvalidOperationException("Unsupported content storage kind."),
            };

            if (!stream.CanRead || !stream.CanSeek || stream.Length != descriptor.SizeBytes)
            {
                await stream.DisposeAsync();
                return OpenContentResult.Unavailable(descriptor, unavailableCode);
            }

            return OpenContentResult.Success(descriptor, stream);
        }
        catch (Exception exception) when (
            exception is FileNotFoundException or
            DirectoryNotFoundException or
            IOException or
            UnauthorizedAccessException or
            ArgumentException or
            NotSupportedException)
        {
            if (stream is not null)
                await stream.DisposeAsync();
            return OpenContentResult.Unavailable(descriptor, unavailableCode);
        }
    }

    private static bool DescriptorIsValid(ContentDescriptor descriptor)
    {
        if (descriptor.ArtifactId == Guid.Empty ||
            descriptor.SizeBytes < 0 ||
            descriptor.Sha256 is not { Length: 64 } ||
            descriptor.Sha256.Any(character =>
                character is not (>= '0' and <= '9' or >= 'a' and <= 'f')))
            return false;

        return descriptor switch
        {
            {
                ArtifactType: Mavi.Domain.Media.ArtifactType.SourceVideo,
                StorageKind: ContentStorageKind.ManagedMedia,
                MimeType: "video/mp4"
            } => true,
            {
                ArtifactType: Mavi.Domain.Media.ArtifactType.Thumbnail,
                StorageKind: ContentStorageKind.AcceptedEvidence,
                MimeType: "image/jpeg"
            } => true,
            {
                ArtifactType: Mavi.Domain.Media.ArtifactType.TrackTrajectory,
                StorageKind: ContentStorageKind.AcceptedEvidence,
                MimeType: "application/msgpack"
            } => true,
            _ => false,
        };
    }
}
