using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

public sealed class WorkerContractV2Tests
{
    [Fact]
    public void CanonicalLeaseExampleRoundTripsThroughPublicContract()
    {
        var path = Path.Combine(FindRepositoryRoot(), "contracts/examples/vision-job-lease-v2.example.json");
        using var expected = JsonDocument.Parse(File.ReadAllText(path));
        var contract = JsonSerializer.Deserialize<VisionJobLeaseContract>(expected.RootElement.GetRawText(), JsonOptions())!;
        using var actual = JsonDocument.Parse(JsonSerializer.Serialize(contract, JsonOptions()));

        Assert.Equal("2.0", contract.SchemaVersion);
        Assert.Equal("gpu-sdd-01", contract.WorkerId);
        Assert.True(JsonElement.DeepEquals(expected.RootElement, actual.RootElement));
    }

    [Theory]
    [InlineData("source/camera/2026/09/09/video.mp4", true)]
    [InlineData("/source/video.mp4", false)]
    [InlineData("source//video.mp4", false)]
    [InlineData("source/../video.mp4", false)]
    [InlineData("source/./video.mp4", false)]
    [InlineData("D:\\MAVI-Data\\video.mp4", false)]
    [InlineData("file:///mnt/video.mp4", false)]
    public void LogicalStorageKeyInvariantIsComplete(string value, bool expected) =>
        Assert.Equal(expected, WorkerContractRules.IsLogicalStorageKey(value));

    [Fact]
    public async Task WorkerRequestsRejectV1MissingVersionAndUnknownMembers()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        foreach (var json in new[] {
            "{\"schemaVersion\":\"1.0\",\"workerId\":\"worker-a\"}",
            "{\"workerId\":\"worker-a\"}",
            "{\"schemaVersion\":\"2.0\",\"workerId\":\"worker-a\",\"unknown\":true}" })
        {
            using var response = await client.PostAsync("/api/vision/jobs/lease", new StringContent(json, Encoding.UTF8, "application/json"));
            Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        }
    }

    [Fact]
    public async Task EverySharedWorkerRequestVectorIsRejectedByTheRealHttpBoundary()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        using var leaseResponse = await client.PostAsJsonAsync(
            "/api/vision/jobs/lease",
            new VisionJobLeaseRequest(WorkerContractRules.SchemaVersion, "gpu-sdd-01"));
        leaseResponse.EnsureSuccessStatusCode();
        var lease = (await leaseResponse.Content.ReadFromJsonAsync<VisionJobLeaseContract>())!;

        var vectorsPath = Path.Combine(FindRepositoryRoot(), "contracts/test-vectors/control-plane-v2-invalid.json");
        using var vectors = JsonDocument.Parse(await File.ReadAllTextAsync(vectorsPath));
        foreach (var vector in vectors.RootElement.EnumerateArray()
                     .Where(x => x.GetProperty("direction").GetString() == "worker-request"))
        {
            var name = vector.GetProperty("name").GetString()!;
            var schema = vector.GetProperty("schema").GetString()!;
            var payload = JsonNode.Parse(vector.GetProperty("payload").GetRawText())!.AsObject();
            if (schema is "vision-job-heartbeat-v2" or "vision-job-fail-v2" &&
                name != "malformed trailing token bits")
            {
                payload["leaseToken"] = lease.LeaseToken;
            }

            var endpoint = schema switch
            {
                "vision-job-lease-request-v2" => "/api/vision/jobs/lease",
                "vision-job-heartbeat-v2" => $"/api/vision/jobs/{lease.JobId}/heartbeat",
                "vision-job-fail-v2" => $"/api/vision/jobs/{lease.JobId}/fail",
                _ => throw new InvalidOperationException($"No HTTP endpoint mapping exists for {schema}.")
            };
            using var response = await client.PostAsync(
                endpoint,
                new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json"));

            Assert.True((int)response.StatusCode is >= 400 and < 500,
                $"Vector '{name}' returned unexpected HTTP {(int)response.StatusCode}.");
        }
    }

    [Theory]
    [InlineData("gpu-sdd-01", true)]
    [InlineData(" gpu-sdd-01", false)]
    [InlineData("gpu-sdd-01 ", false)]
    [InlineData(" gpu-sdd-01 ", false)]
    public void WorkerIdentityMustAlreadyBeCanonical(string value, bool expected) =>
        Assert.Equal(expected, WorkerContractRules.TryNormalizeWorkerId(value, out _));

    [Theory]
    [InlineData("vision_dummy_not_implemented", true)]
    [InlineData("ffmpeg_decode_failed", true)]
    [InlineData("bad code", false)]
    [InlineData("https://failure", false)]
    [InlineData("UPPERCASE", false)]
    public void FailureCodeUsesCanonicalMachineSyntax(string value, bool expected) =>
        Assert.Equal(expected, WorkerContractRules.IsFailureCode(value));

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void FailureMessageIsOptionalAndNullable(bool includeNull)
    {
        var suffix = includeNull ? ",\"failureMessage\":null" : string.Empty;
        var json = $$"""{"schemaVersion":"2.0","workerId":"gpu-sdd-01","leaseToken":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","failureCode":"ffmpeg_decode_failed"{{suffix}}}""";
        var request = JsonSerializer.Deserialize<VisionJobFailRequest>(json, JsonOptions());
        Assert.NotNull(request);
        Assert.Null(request.FailureMessage);
    }

    private static JsonSerializerOptions JsonOptions() => new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow
    };

    private static async Task<Guid> SeedVideoAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var nowUtc = new DateTimeOffset(2026, 9, 9, 2, 30, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-VECTORS", "Contract vectors", "UTC", nowUtc);
        var artifact = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            100,
            new string('c', 64),
            createdAtUtc: nowUtc);
        var video = VideoAsset.Create(
            camera.Id, artifact.Id, "vectors.mp4", nowUtc, 1_000, 25, 1, 160, 90,
            "h264", TimestampSource.Manual, 1, importedAtUtc: nowUtc);
        db.AddRange(camera, artifact, video);
        await db.SaveChangesAsync();
        return video.Id;
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root was not found.");
    }
}
