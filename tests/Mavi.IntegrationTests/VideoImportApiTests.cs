using System.Diagnostics;
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

    private static async Task<HttpResponseMessage> ImportAsync(HttpClient client, Guid cameraId, string path, string? fileName = null)
    {
        var form = new MultipartFormDataContent
        {
            { new StringContent(cameraId.ToString("D")), "cameraId" },
            { new StringContent("2026-09-08T14:00:00"), "recordingStartLocal" },
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

    private static async Task<string> GenerateVideoAsync()
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-import-{Guid.NewGuid():N}.mp4");
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = "ffmpeg",
            UseShellExecute = false,
            RedirectStandardError = true,
        }.AddArguments("-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25", "-t", "1",
            "-pix_fmt", "yuv420p", path))!;
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        Assert.True(process.ExitCode == 0, error);
        return path;
    }
}
