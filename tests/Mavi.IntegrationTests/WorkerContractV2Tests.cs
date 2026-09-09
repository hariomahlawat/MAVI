using System.Net;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker;

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

    private static JsonSerializerOptions JsonOptions() => new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow
    };

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root was not found.");
    }
}
