using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ContentApiTests
{
    [Fact]
    public async Task VideoContentSupportsFullAndRangeReads()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);

        using var client = factory.CreateClient();
        using var full = await client.GetAsync($"/api/videos/{video.VideoId:D}/content");

        Assert.Equal(HttpStatusCode.OK, full.StatusCode);
        Assert.Equal("video/mp4", full.Content.Headers.ContentType?.MediaType);
        Assert.Equal(video.SourceBytes.Length, full.Content.Headers.ContentLength);
        Assert.Contains("bytes", full.Headers.AcceptRanges);
        Assert.NotNull(full.Headers.ETag);
        Assert.Equal(video.SourceBytes, await full.Content.ReadAsByteArrayAsync());

        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            $"/api/videos/{video.VideoId:D}/content");
        request.Headers.Range = new RangeHeaderValue(0, 99);
        using var partial = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.PartialContent, partial.StatusCode);
        Assert.Equal(100, partial.Content.Headers.ContentLength);
        Assert.Equal(0, partial.Content.Headers.ContentRange?.From);
        Assert.Equal(99, partial.Content.Headers.ContentRange?.To);
        Assert.Equal(video.SourceBytes.Length, partial.Content.Headers.ContentRange?.Length);
        Assert.Equal(video.SourceBytes[..100], await partial.Content.ReadAsByteArrayAsync());
    }

    [Fact]
    public async Task VideoContentSupportsSuffixOpenEndedAndUnsatisfiableRanges()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        using var client = factory.CreateClient();

        using var suffixRequest = new HttpRequestMessage(
            HttpMethod.Get,
            $"/api/videos/{video.VideoId:D}/content");
        suffixRequest.Headers.Range = new RangeHeaderValue(null, 10);
        using var suffix = await client.SendAsync(suffixRequest);
        Assert.Equal(HttpStatusCode.PartialContent, suffix.StatusCode);
        Assert.Equal(video.SourceBytes[^10..], await suffix.Content.ReadAsByteArrayAsync());

        using var openEndedRequest = new HttpRequestMessage(
            HttpMethod.Get,
            $"/api/videos/{video.VideoId:D}/content");
        openEndedRequest.Headers.Range = new RangeHeaderValue(500, null);
        using var openEnded = await client.SendAsync(openEndedRequest);
        Assert.Equal(HttpStatusCode.PartialContent, openEnded.StatusCode);
        Assert.Equal(video.SourceBytes[500..], await openEnded.Content.ReadAsByteArrayAsync());

        using var invalidRequest = new HttpRequestMessage(
            HttpMethod.Get,
            $"/api/videos/{video.VideoId:D}/content");
        invalidRequest.Headers.Range = new RangeHeaderValue(1000, 1100);
        using var invalid = await client.SendAsync(invalidRequest);
        Assert.Equal(HttpStatusCode.RequestedRangeNotSatisfiable, invalid.StatusCode);
    }

    [Fact]
    public async Task ThumbnailAndTrajectoryContentAreServedOnlyThroughAuthoritativeRelations()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var track = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            1_000);

        using var client = factory.CreateClient();
        using var thumbnail = await client.GetAsync(
            $"/api/artifacts/{track.ThumbnailArtifactId:D}/content");
        using var trajectory = await client.GetAsync(
            $"/api/artifacts/{track.TrajectoryArtifactId:D}/content");

        Assert.Equal(HttpStatusCode.OK, thumbnail.StatusCode);
        Assert.Equal("image/jpeg", thumbnail.Content.Headers.ContentType?.MediaType);
        Assert.NotNull(thumbnail.Headers.ETag);
        Assert.Equal(HttpStatusCode.OK, trajectory.StatusCode);
        Assert.Equal("application/msgpack", trajectory.Content.Headers.ContentType?.MediaType);

        using var sourceViaArtifact = await client.GetAsync(
            $"/api/artifacts/{video.SourceArtifactId:D}/content");
        Assert.Equal(HttpStatusCode.NotFound, sourceViaArtifact.StatusCode);
    }

    [Theory]
    [InlineData(ArtifactType.Thumbnail)]
    [InlineData(ArtifactType.EvidenceCrop)]
    public async Task UnreferencedEvidenceArtifactIsNotPubliclyReadable(ArtifactType artifactType)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var bytes = new byte[] { 1, 2, 3, 4 };
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var artifact = Artifact.Create(
            artifactType,
            $"evidence/unreferenced/{sha}.jpg",
            "image/jpeg",
            bytes.Length,
            sha);
        Task14TestData.WriteEvidence(factory, artifact.StorageKey, bytes);

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            db.Artifacts.Add(artifact);
            await db.SaveChangesAsync();
        }

        using var client = factory.CreateClient();
        using var response = await client.GetAsync(
            $"/api/artifacts/{artifact.Id:D}/content");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Contains(
            "artifact_not_found",
            await response.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task MissingOrLengthMismatchedAuthoritativeEvidenceFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var track = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            1_000);

        string thumbnailKey;
        string trajectoryKey;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            thumbnailKey = (await db.Artifacts.SingleAsync(x => x.Id == track.ThumbnailArtifactId)).StorageKey;
            trajectoryKey = (await db.Artifacts.SingleAsync(x => x.Id == track.TrajectoryArtifactId)).StorageKey;
        }

        var thumbnailPath = EvidencePath(factory, thumbnailKey);
        File.Delete(thumbnailPath);

        using var client = factory.CreateClient();
        using var missing = await client.GetAsync(
            $"/api/artifacts/{track.ThumbnailArtifactId:D}/content");
        Assert.Equal(HttpStatusCode.InternalServerError, missing.StatusCode);
        Assert.Contains(
            "artifact_content_unavailable",
            await missing.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);

        var trajectoryPath = EvidencePath(factory, trajectoryKey);
        await using (var append = new FileStream(
            trajectoryPath,
            FileMode.Append,
            FileAccess.Write,
            FileShare.None,
            bufferSize: 4096,
            FileOptions.Asynchronous))
        {
            await append.WriteAsync(new byte[] { 9, 9, 9 });
        }

        using var mismatched = await client.GetAsync(
            $"/api/artifacts/{track.TrajectoryArtifactId:D}/content");
        Assert.Equal(HttpStatusCode.InternalServerError, mismatched.StatusCode);
        Assert.Contains(
            "artifact_content_unavailable",
            await mismatched.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task LinkedEvidenceParentReturnsStableContentUnavailable()
    {
        if (!OperatingSystem.IsLinux() && !OperatingSystem.IsWindows())
            return;

        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var track = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            1_000);

        string thumbnailKey;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            thumbnailKey = (await db.Artifacts
                .SingleAsync(x => x.Id == track.ThumbnailArtifactId))
                .StorageKey;
        }

        var thumbnailPath = EvidencePath(factory, thumbnailKey);
        var parent = Path.GetDirectoryName(thumbnailPath)!;
        var fileName = Path.GetFileName(thumbnailPath);
        var bytes = await File.ReadAllBytesAsync(thumbnailPath);
        var external = Path.Combine(factory.EvidenceRoot, "linked-parent-target");
        Directory.CreateDirectory(external);
        await File.WriteAllBytesAsync(Path.Combine(external, fileName), bytes);

        Directory.Delete(parent, recursive: true);
        try
        {
            Directory.CreateSymbolicLink(parent, external);
        }
        catch (Exception exception) when (
            exception is UnauthorizedAccessException or
            IOException or
            PlatformNotSupportedException)
        {
            return;
        }

        using var client = factory.CreateClient();
        using var response = await client.GetAsync(
            $"/api/artifacts/{track.ThumbnailArtifactId:D}/content");

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains(
            "artifact_content_unavailable",
            await response.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExistingVideoWithWrongSourceArtifactTypeFailsAsIntegrityIncident()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var now = new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-BROKEN", "Broken Source", "UTC", now.AddMinutes(-5));
        var bytes = new byte[] { 1, 2, 3 };
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var wrongSource = Artifact.Create(
            ArtifactType.Thumbnail,
            $"evidence/broken/{sha}.jpg",
            "image/jpeg",
            bytes.Length,
            sha,
            createdAtUtc: now.AddMinutes(-4));
        var video = VideoAsset.Create(
            Guid.CreateVersion7(),
            camera.Id,
            wrongSource.Id,
            "broken.mp4",
            now,
            10_000,
            25,
            1,
            640,
            480,
            "h264",
            TimestampSource.Manual,
            1.0,
            "UTC",
            0,
            now.AddMinutes(-3));

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            db.Cameras.Add(camera);
            db.Artifacts.Add(wrongSource);
            db.VideoAssets.Add(video);
            await db.SaveChangesAsync();
        }

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/videos/{video.Id:D}/content");

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains(
            "video_content_unavailable",
            await response.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task MissingSourceVideoFileFailsAsOperationalIntegrityIncident()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var sourcePath = Path.Combine(
            factory.MediaRoot,
            video.SourceStorageKey.Replace('/', Path.DirectorySeparatorChar));
        File.Delete(sourcePath);

        using var client = factory.CreateClient();
        using var response = await client.GetAsync(
            $"/api/videos/{video.VideoId:D}/content");

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains(
            "video_content_unavailable",
            await response.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    private static string EvidencePath(ApiTestFactory factory, string storageKey)
    {
        const string prefix = "evidence/";
        var relative = storageKey[prefix.Length..]
            .Replace('/', Path.DirectorySeparatorChar);
        return Path.Combine(factory.EvidenceRoot, relative);
    }
}
