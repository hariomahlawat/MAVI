using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Contracts.Api.Cameras;
using Mavi.Contracts.Api.Videos;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VideoImportApiTests(PostgresFixture database)
{
    private static readonly JsonSerializerOptions WebJsonOptions = new(JsonSerializerDefaults.Web);
    // End-to-end managed ownership
    [Fact]
    public async Task ImportOwnsMediaAndCatalogReturnsSafeMetadata()
    {
        using var factory = new ApiTestFactory();
        Assert.Equal(database.ConnectionString, factory.ConnectionString);
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var camera = await CreateCameraAsync(client);
        var sourcePath = await GenerateVideoAsync();
        try
        {
            using var response = await ImportAsync(client, camera.Id, sourcePath);
            Assert.Equal(HttpStatusCode.Created, response.StatusCode);
            var video = await response.Content.ReadFromJsonAsync<VideoAssetResponse>();
            Assert.NotNull(video);
            Assert.Equal($"/api/videos/{video.Id}", response.Headers.Location?.OriginalString);
            Assert.Equal("NotQueued", video.ProcessingStatus);
            Assert.Equal("Asia/Kolkata", video.RecordingTimeZoneId);
            Assert.Equal(330, video.RecordingUtcOffsetMinutes);

            File.Delete(sourcePath);
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var storedVideo = await db.VideoAssets.SingleAsync(item => item.Id == video.Id);
            var artifact = await db.Artifacts.SingleAsync(item => item.Id == storedVideo.SourceArtifactId);
            Assert.Equal(ArtifactType.SourceVideo, artifact.ArtifactType);
            var managedPath = Path.Combine(factory.MediaRoot, artifact.StorageKey.Replace('/', Path.DirectorySeparatorChar));
            Assert.True(File.Exists(managedPath));
            Assert.True(new FileInfo(managedPath).Length > 0);
            Assert.Equal(1, await db.VideoAssets.CountAsync());
            Assert.Equal(1, await db.Artifacts.CountAsync());

            var fetched = await client.GetFromJsonAsync<VideoAssetResponse>($"/api/videos/{video.Id}");
            Assert.Equal(video.Id, fetched!.Id);
            Assert.DoesNotContain("storage", JsonSerializer.Serialize(fetched), StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            if (File.Exists(sourcePath)) File.Delete(sourcePath);
        }
    }

    [Fact]
    public async Task RenamedNonMp4ContainerIsRejectedWithoutOrphans()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var camera = await CreateCameraAsync(client);
        var sourcePath = await GenerateVideoAsync(".mkv");
        try
        {
            using var response = await ImportAsync(client, camera.Id, sourcePath, "renamed.mp4");
            Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
            Assert.Equal("video_container_unsupported", await ReadCodeAsync(response));
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            Assert.Empty(await db.VideoAssets.ToArrayAsync());
            Assert.Empty(await db.Artifacts.ToArrayAsync());
            Assert.Empty(Directory.GetFiles(factory.MediaRoot, "*", SearchOption.AllDirectories));
        }
        finally { File.Delete(sourcePath); }
    }

    [Fact]
    public async Task VideoListIsDeterministicAndExposesOnlyOperatorDto()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var camera = await CreateCameraAsync(client);
        var firstPath = await GenerateVideoAsync();
        var secondPath = await GenerateVideoAsync(durationSeconds: 2);
        try
        {
            using var first = await ImportAsync(client, camera.Id, firstPath);
            using var second = await ImportAsync(client, camera.Id, secondPath, "second.mp4", "2026-09-09T14:00:00");
            first.EnsureSuccessStatusCode(); second.EnsureSuccessStatusCode();
            var json = await client.GetStringAsync("/api/videos");
            var videos = JsonSerializer.Deserialize<VideoAssetResponse[]>(json, WebJsonOptions)!;
            Assert.Equal(2, videos.Length);
            Assert.True(videos[0].RecordingStartUtc > videos[1].RecordingStartUtc);
            Assert.DoesNotContain("storageKey", json, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("sha256", json, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain(factory.MediaRoot, json, StringComparison.OrdinalIgnoreCase);
        }
        finally { File.Delete(firstPath); File.Delete(secondPath); }
    }

    [Fact]
    public async Task DuplicateCorruptAndUnsupportedImportsReturnStableProblemsWithoutOrphans()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var camera = await CreateCameraAsync(client);
        var sourcePath = await GenerateVideoAsync();
        var corruptPath = Path.Combine(Path.GetTempPath(), $"corrupt-{Guid.NewGuid():N}.mp4");
        await File.WriteAllTextAsync(corruptPath, "not video");
        try
        {
            using var accepted = await ImportAsync(client, camera.Id, sourcePath);
            Assert.Equal(HttpStatusCode.Created, accepted.StatusCode);
            using var duplicate = await ImportAsync(client, camera.Id, sourcePath);
            Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
            Assert.Equal("video_duplicate", await ReadCodeAsync(duplicate));
            using var corrupt = await ImportAsync(client, camera.Id, corruptPath);
            Assert.Equal(HttpStatusCode.BadRequest, corrupt.StatusCode);
            Assert.Equal("video_metadata_invalid", await ReadCodeAsync(corrupt));
            using var unsupported = await ImportAsync(client, camera.Id, corruptPath, "bad.avi");
            Assert.Equal(HttpStatusCode.BadRequest, unsupported.StatusCode);
            Assert.Equal("video_format_unsupported", await ReadCodeAsync(unsupported));

            Assert.Single(Directory.GetFiles(factory.MediaRoot, "*.mp4", SearchOption.AllDirectories));
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            Assert.Equal(1, await db.VideoAssets.CountAsync());
            Assert.Equal(1, await db.Artifacts.CountAsync());
        }
        finally
        {
            File.Delete(sourcePath);
            File.Delete(corruptPath);
        }
    }

    [Fact]
    public async Task MissingVideoReturnsStableProblem()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/videos/{Guid.CreateVersion7()}");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("video_not_found", await ReadCodeAsync(response));
    }

    // HTTP helpers
    private static async Task<CameraResponse> CreateCameraAsync(HttpClient client)
    {
        using var response = await client.PostAsJsonAsync("/api/cameras/",
            new CreateCameraRequest("CAM-IMPORT", "Import Camera", "Asia/Kolkata"));
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<CameraResponse>())!;
    }

    private static async Task<HttpResponseMessage> ImportAsync(HttpClient client, Guid cameraId, string path, string? fileName = null,
        string recordingStartLocal = "2026-09-08T14:00:00")
    {
        var form = new MultipartFormDataContent
        {
            { new StringContent(cameraId.ToString("D")), "cameraId" },
            { new StringContent(recordingStartLocal), "recordingStartLocal" },
        };
        var stream = File.OpenRead(path);
        form.Add(new StreamContent(stream), "file", fileName ?? Path.GetFileName(path));
        try { return await client.PostAsync("/api/videos/import", form); }
        finally { form.Dispose(); }
    }

    private static async Task<string> ReadCodeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("code").GetString()!;
    }

    private static async Task<string> GenerateVideoAsync(string extension = ".mp4", int durationSeconds = 1)
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-import-{Guid.NewGuid():N}{extension}");
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = "ffmpeg",
            UseShellExecute = false,
            RedirectStandardError = true,
        }.AddArguments("-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25", "-t", durationSeconds.ToString(CultureInfo.InvariantCulture),
            "-pix_fmt", "yuv420p", path))!;
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        Assert.True(process.ExitCode == 0, error);
        return path;
    }
}
