using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>Completion 3.0 wire boundary: capability probe, version scoping, binding bounds, body size.</summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class WorkerContractV3Tests(ITestOutputHelper output)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow,
    };

    [Fact]
    public void CanonicalV3ExampleRoundTripsThroughPublicContract()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        using var expected = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(directory!.FullName, "contracts/examples/vision-job-complete-v3.example.json")));

        var contract = JsonSerializer.Deserialize<VisionJobCompleteRequest>(expected.RootElement.GetRawText(), Json)!;
        using var actual = JsonDocument.Parse(JsonSerializer.Serialize(contract, Json));

        Assert.Equal("3.0", contract.SchemaVersion);
        Assert.Equal(4, contract.Tracks![0].Observations!.Count);
        Assert.Null(contract.Tracks[0].Representative);
        Assert.True(JsonElement.DeepEquals(expected.RootElement, actual.RootElement));
    }

    [Fact]
    public async Task ContractProbeAdvertisesControlPlaneAndBothSynchronousCompletionVersionsByDefault()
    {
        // The default (F2-only) deployment: asynchronous finalization is not activated, so the
        // probe still lists the synchronous 2.0 and 3.0 and never 3.1 (plan §15.2).
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var response = await client.GetAsync("/api/vision/contract");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.True(JsonElement.DeepEquals(
            JsonDocument.Parse("""{"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}""").RootElement,
            body.RootElement));
    }

    [Fact]
    public async Task LeaseHeartbeatAndFailStayOnControlPlaneVersion2()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var jobId = Guid.CreateVersion7();
        const string token = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

        foreach (var (path, payload) in new (string, object)[]
                 {
                     ("/api/vision/jobs/lease", new VisionJobLeaseRequest("3.0", "gpu-sdd-01")),
                     ($"/api/vision/jobs/{jobId}/heartbeat", new VisionJobHeartbeatRequest("3.0", "gpu-sdd-01", token, 10)),
                     ($"/api/vision/jobs/{jobId}/fail", new VisionJobFailRequest("3.0", "gpu-sdd-01", token, "ffmpeg_decode_failed", null)),
                 })
        {
            using var response = await client.PostAsJsonAsync(path, payload);
            Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
            Assert.Contains("worker_contract_version_unsupported", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }
    }

    [Theory]
    [InlineData("1.0", false)]
    [InlineData("3.1", false)] // not activated: no job may enter Finalizing without a finalizer
    [InlineData("4.0", false)]
    [InlineData("1.0", true)]
    [InlineData("3.0", true)] // retired at activation; never reinterpreted as 3.1
    [InlineData("4.0", true)]
    public async Task CompletionRejectsUnacceptedVersions(string version, bool asynchronousFinalization)
    {
        using var factory = new ApiTestFactory { EnableAsynchronousFinalization = asynchronousFinalization };
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var response = await client.PostAsync(
            $"/api/vision/jobs/{Guid.CreateVersion7()}/complete",
            new StringContent($$"""{"schemaVersion":"{{version}}"}""", Encoding.UTF8, "application/json"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("worker_contract_version_unsupported", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    [Fact]
    public void ObservationCollectionIsBoundedDuringJsonBinding()
    {
        static string Body(int observations) =>
            "{\"schemaVersion\":\"3.0\",\"tracks\":[{\"observations\":[" +
            string.Join(',', Enumerable.Repeat("{}", observations)) + "]}]}";

        var bound = JsonSerializer.Deserialize<VisionJobCompleteRequest>(Body(WorkerContractRules.MaximumTrackObservations), Json)!;
        Assert.Equal(WorkerContractRules.MaximumTrackObservations, bound.Tracks![0].Observations!.Count);
        Assert.Throws<JsonException>(() =>
            JsonSerializer.Deserialize<VisionJobCompleteRequest>(Body(WorkerContractRules.MaximumTrackObservations + 1), Json));
    }

    [Fact]
    public async Task FiveObservationsAreRejectedAtTheHttpBoundary()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var body = "{\"schemaVersion\":\"3.1\",\"tracks\":[{\"observations\":[" +
                   string.Join(',', Enumerable.Repeat("{}", 5)) + "]}]}";

        using var response = await client.PostAsync(
            $"/api/vision/jobs/{Guid.CreateVersion7()}/complete", new StringContent(body, Encoding.UTF8, "application/json"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Theory]
    [InlineData("""{"tracks":[{"observations":[{"role":"representative","unknown":1}]}]}""")]
    [InlineData("""{"evidenceAccounting":{"nearView":{}}}""")]
    [InlineData("""{"evidenceAccounting":{"representative":{"candidates":1,"extra":0}}}""")]
    [InlineData("""{"evidenceAccounting":{"representative":{"candidates":1.5}}}""")]
    [InlineData("""{"tracks":[{"observations":[{"rank":0.5}]}]}""")]
    // Version-exclusive members are absent or objects/arrays; an explicit null is rejected (review P3-1).
    [InlineData("""{"schemaVersion":"2.0","evidenceAccounting":null}""")]
    [InlineData("""{"schemaVersion":"2.0","tracks":[{"observations":null}]}""")]
    [InlineData("""{"schemaVersion":"3.0","tracks":[{"representative":null}]}""")]
    public void V3MembersRejectUnknownNamesAndFractionalIntegers(string json) =>
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisionJobCompleteRequest>(json, Json));

    [Fact]
    public async Task CompletionBodyAboveFortyEightMebibytesIsRejectedBeforeBinding()
    {
        Assert.Equal(48L * 1024 * 1024, WorkerContractRules.MaximumCompletionRequestBodyBytes);
        using var factory = new ApiTestFactory();
        using var client = factory.CreateClient();
        using var content = new StringContent("{}", Encoding.UTF8, "application/json");
        content.Headers.ContentLength = WorkerContractRules.MaximumCompletionRequestBodyBytes + 1;

        using var response = await client.PostAsync($"/api/vision/jobs/{Guid.CreateVersion7()}/complete", content);

        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
    }

    [Fact]
    public void WorstShapeBodyFitsUnderLimit()
    {
        // 10,000 Tracks x 4 observations with every string at its bound and every
        // number at its longest canonical form, through the real DTOs (plan §7.4).
        var jobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
        var prefix = $"staging/{jobId:D}/attempt-9999";
        const double longDouble = 0.12345678901234568;
        const long longOffset = 9_007_199_254_740_991;
        var sha = new string('f', 64);
        var roles = new[] { "representative", "near-view", "early-diverse", "late-diverse" };
        var tracks = Enumerable.Range(0, WorkerContractRules.MaximumCompletionTracks).Select(index =>
        {
            var trackId = new string('a', 58) + index.ToString("D6", System.Globalization.CultureInfo.InvariantCulture);
            return new VisionTrackResultContract(
                trackId, "vehicle", longOffset, longOffset, int.MaxValue, longDouble, longDouble, null,
                new VisionArtifactDescriptorContract($"{prefix}/trajectories/{trackId}.msgpack", "application/msgpack", WorkerContractRules.MaximumCompletionArtifactBytes, sha),
                [.. roles.Select((role, rank) => new VisionTrackObservationContract(
                    role, rank, longOffset, longOffset, longDouble, longDouble, longDouble,
                    new VisionBoundingBoxContract(longDouble, longDouble, longDouble, longDouble),
                    new VisionArtifactDescriptorContract($"{prefix}/evidence/{trackId}-{role}.jpg", "image/jpeg", WorkerContractRules.MaximumSupplementalCropBytes, sha)))]);
        }).ToArray();
        var role = new VisionEvidenceRoleAccountingContract(int.MaxValue, int.MaxValue, int.MaxValue, long.MaxValue, long.MaxValue);
        var request = new VisionJobCompleteRequest(
            "3.1", jobId, new string('w', 128), "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 9999, longOffset, longOffset,
            null, tracks, new VisionEvidenceAccountingContract(role, role, role, role));

        var bytes = JsonSerializer.SerializeToUtf8Bytes(request, Json).LongLength;

        // The provenance block is bounded separately and far below 1 MiB.
        output.WriteLine($"Worst-shape completion 3.1 body without provenance: {bytes:N0} bytes ({bytes / 1024.0 / 1024.0:F2} MiB).");
        Assert.True(bytes <= 32L * 1024 * 1024, $"Worst shape {bytes} bytes exceeds the 32 MiB plan stop condition.");
        Assert.True(bytes <= WorkerContractRules.MaximumCompletionRequestBodyBytes - 8L * 1024 * 1024);
    }
}
