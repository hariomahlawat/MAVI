using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Api.Cameras;
using Mavi.Contracts.Api.Scene;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneApiContractTests(PostgresFixture database)
{
    // Reading
    [Fact]
    public async Task NeverConfiguredCameraReportsItselfAsUnconfigured()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S001");

        var scene = await client.GetFromJsonAsync<CameraSceneResponse>($"/api/cameras/{cameraId}/scene");

        Assert.NotNull(scene);
        Assert.Equal(cameraId, scene.CameraId);
        Assert.False(scene.Configured);
        Assert.Null(scene.ActiveRevision);
        Assert.Empty(scene.History);
    }

    [Fact]
    public async Task MissingCameraIsNotFound()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();

        using var response = await client.GetAsync($"/api/cameras/{Guid.CreateVersion7()}/scene");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("camera_not_found", await ReadProblemCodeAsync(response));
    }

    // Saving
    [Fact]
    public async Task FirstSaveCreatesRevisionOneAndActivatesIt()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S002");

        using var response = await SaveAsync(client, cameraId, Request(null, Zone("Gate"), lines: [Line("Kerb")]));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Equal(
            $"/api/cameras/{cameraId}/scene/revisions/1",
            response.Headers.Location?.OriginalString);

        var revision = await response.Content.ReadFromJsonAsync<SceneRevisionResponse>();
        Assert.NotNull(revision);
        Assert.Equal(1, revision.RevisionNumber);
        Assert.Equal(cameraId, revision.CameraId);
        Assert.Equal(SceneContractRules.UnattributedDevelopmentActor, revision.CreatedBy);
        Assert.True(revision.AnalyticsEnabled);
        Assert.Equal("Gate", Assert.Single(revision.Zones).Name);
        Assert.Equal("General", revision.Zones[0].Kind);
        Assert.Equal(4, revision.Zones[0].Vertices.Count);
        Assert.Equal("Kerb", Assert.Single(revision.TripLines).Name);
    }

    [Fact]
    public async Task SecondSaveIncrementsAndKeepsTheHistory()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S003");
        var first = await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));

        var second = await SaveRevisionAsync(
            client,
            cameraId,
            Request(1, Zone("Gate", zoneId: first.Zones[0].ZoneId), Zone("Yard", offset: 0.5)));

        Assert.Equal(2, second.RevisionNumber);
        Assert.Equal(2, second.Zones.Count);

        var scene = await client.GetFromJsonAsync<CameraSceneResponse>($"/api/cameras/{cameraId}/scene");
        Assert.True(scene!.Configured);
        Assert.Equal(second.RevisionId, scene.ActiveRevision!.RevisionId);
        Assert.Equal([1, 2], scene.History.Select(entry => entry.RevisionNumber));
        Assert.Equal([1, 2], scene.History.Select(entry => entry.ZoneCount));
        Assert.All(scene.History, entry => Assert.True(entry.AnalyticsEnabled));
    }

    [Fact]
    public async Task HistoricalRevisionRemainsReadableAndUnchanged()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S004");
        var first = await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));
        await SaveRevisionAsync(client, cameraId, Request(1, Zone("Replacement")));

        var stored = await client.GetFromJsonAsync<SceneRevisionResponse>(
            $"/api/cameras/{cameraId}/scene/revisions/1");

        Assert.Equal(first.RevisionId, stored!.RevisionId);
        Assert.Equal("Gate", Assert.Single(stored.Zones).Name);
    }

    [Fact]
    public async Task UnknownRevisionNumberIsNotFound()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S005");
        await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));

        using var response = await client.GetAsync($"/api/cameras/{cameraId}/scene/revisions/7");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("scene_revision_not_found", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task SavingAnEmptyRevisionDisablesAnalyticsWithoutDeletingAnything()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S006");
        await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));

        var disabled = await SaveRevisionAsync(
            client,
            cameraId,
            new SaveSceneRequest(1, "Disable analytics", null, null, [], []));

        Assert.False(disabled.AnalyticsEnabled);
        Assert.Empty(disabled.Zones);

        var scene = await client.GetFromJsonAsync<CameraSceneResponse>($"/api/cameras/{cameraId}/scene");
        Assert.True(scene!.Configured);
        Assert.False(scene.ActiveRevision!.AnalyticsEnabled);
        Assert.Equal(2, scene.History.Count);
        Assert.True(scene.History[0].AnalyticsEnabled);
    }

    [Fact]
    public async Task RevisionWhoseGeometryIsAllDisabledIsAlsoDisabled()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S007");

        var revision = await SaveRevisionAsync(
            client,
            cameraId,
            Request(null, Zone("Gate", enabled: false)));

        Assert.False(revision.AnalyticsEnabled);
        Assert.Single(revision.Zones);
        Assert.False(revision.Zones[0].Enabled);
    }

    // Conflict
    [Fact]
    public async Task SaveFromAStaleRevisionNumberConflicts()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S008");
        await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));
        await SaveRevisionAsync(client, cameraId, Request(1, Zone("Gate")));

        using var response = await SaveAsync(client, cameraId, Request(1, Zone("Gate")));

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("scene_revision_conflict", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task FirstSaveAgainstAnAlreadyConfiguredCameraConflicts()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S009");
        await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));

        using var response = await SaveAsync(client, cameraId, Request(null, Zone("Gate")));

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("scene_revision_conflict", await ReadProblemCodeAsync(response));
    }

    // Validation
    [Fact]
    public async Task SavingForAMissingCameraIsNotFound()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();

        using var response = await SaveAsync(client, Guid.CreateVersion7(), Request(null, Zone("Gate")));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("camera_not_found", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task VertexOutsideTheFrameIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S010");
        var zone = new SaveSceneZoneRequest(
            null,
            "Gate",
            null,
            true,
            [Point(0.1, 0.1), Point(1.4, 0.1), Point(0.1, 0.4)],
            null);

        using var response = await SaveAsync(client, cameraId, new SaveSceneRequest(null, null, null, null, [zone], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_zone_vertex_range", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task MissingVertexComponentIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S011");
        var zone = new SaveSceneZoneRequest(
            null,
            "Gate",
            null,
            true,
            [Point(0.1, 0.1), new ScenePointRequest(0.4, null), Point(0.1, 0.4)],
            null);

        using var response = await SaveAsync(client, cameraId, new SaveSceneRequest(null, null, null, null, [zone], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_zone_vertex_range", await ReadProblemCodeAsync(response));
    }

    [Theory]
    [InlineData(2, "scene_zone_vertex_count")]
    public async Task ZoneWithTooFewVerticesIsRejected(int vertexCount, string code)
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S012");
        var zone = new SaveSceneZoneRequest(
            null,
            "Gate",
            null,
            true,
            [.. Enumerable.Range(0, vertexCount).Select(index => Point(0.1 + (index * 0.1), 0.1))],
            null);

        using var response = await SaveAsync(client, cameraId, new SaveSceneRequest(null, null, null, null, [zone], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(code, await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task SelfIntersectingZoneIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S013");
        var zone = new SaveSceneZoneRequest(
            null,
            "Bow tie",
            null,
            true,
            [Point(0.1, 0.1), Point(0.9, 0.9), Point(0.9, 0.1), Point(0.1, 0.9)],
            null);

        using var response = await SaveAsync(client, cameraId, new SaveSceneRequest(null, null, null, null, [zone], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_zone_self_intersecting", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task DuplicateZoneNameIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S014");

        using var response = await SaveAsync(
            client, cameraId, Request(null, Zone("Gate"), Zone("gate", offset: 0.5)));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_zone_name_duplicate", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task UnknownZoneKindIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S015");

        using var response = await SaveAsync(client, cameraId, Request(null, Zone("Gate", kind: "Perimeter")));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_zone_kind_invalid", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task TripLineWithCoincidentEndpointsIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S016");
        var line = new SaveSceneTripLineRequest(
            null, "Kerb", true, Point(0.5, 0.5), Point(0.501, 0.5), false, null, null);

        using var response = await SaveAsync(client, cameraId, new SaveSceneRequest(null, null, null, null, [], [line]));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_line_endpoints_identical", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task UnknownStableIdentityIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S017");
        await SaveRevisionAsync(client, cameraId, Request(null, Zone("Gate")));

        using var response = await SaveAsync(
            client, cameraId, Request(1, Zone("Gate", zoneId: Guid.CreateVersion7())));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_identity_unknown", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task IdentityFromAnotherCameraIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var first = await CreateCameraAsync(client, "CAM-S018");
        var second = await CreateCameraAsync(client, "CAM-S019");
        var foreign = await SaveRevisionAsync(client, second, Request(null, Zone("Gate")));

        using var response = await SaveAsync(
            client, first, Request(null, Zone("Gate", zoneId: foreign.Zones[0].ZoneId)));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_identity_unknown", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task HalfAReferenceFrameIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S020");

        using var response = await SaveAsync(
            client,
            cameraId,
            new SaveSceneRequest(null, null, Guid.CreateVersion7(), null, [Zone("Gate")], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_reference_frame_incomplete", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task ReferenceFrameVideoThatDoesNotExistIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S021");

        using var response = await SaveAsync(
            client,
            cameraId,
            new SaveSceneRequest(null, null, Guid.CreateVersion7(), 1_000, [Zone("Gate")], []));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("scene_reference_frame_not_found", await ReadProblemCodeAsync(response));
    }

    // Strictness and information exposure
    [Fact]
    public async Task RequestCarryingAServerOwnedMemberIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S022");

        using var response = await PostRawAsync(client, cameraId, """
            {"expectedRevisionNumber":null,"createdBy":"someone","zones":[],"tripLines":[]}
            """);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task CoordinateSentAsAStringIsRejected()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S023");

        using var response = await PostRawAsync(client, cameraId, """
            {"zones":[{"name":"Gate","vertices":[{"x":"0.1","y":0.1},{"x":0.4,"y":0.1},{"x":0.4,"y":0.4}]}],
             "tripLines":[]}
            """);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task ProblemResponsesNameACodeAndNoInternalDetail()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        var cameraId = await CreateCameraAsync(client, "CAM-S024");

        using var response = await SaveAsync(client, cameraId, Request(null, Zone("Gate", kind: "Perimeter")));
        var body = await response.Content.ReadAsStringAsync();

        Assert.Contains("scene_zone_kind_invalid", body, StringComparison.Ordinal);
        Assert.DoesNotContain("Mavi.", body, StringComparison.Ordinal);
        Assert.DoesNotContain("/home/", body, StringComparison.Ordinal);
        Assert.DoesNotContain("Exception", body, StringComparison.Ordinal);
    }

    // Test infrastructure
    private async Task<ApiTestFactory> CreateFactoryAsync()
    {
        Assert.Equal(database.ConnectionString, Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION"));
        var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        return factory;
    }

    private static async Task<Guid> CreateCameraAsync(HttpClient client, string code)
    {
        var response = await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest(code, code, "UTC"));
        response.EnsureSuccessStatusCode();
        var camera = await response.Content.ReadFromJsonAsync<CameraResponse>();
        return camera!.Id;
    }

    private static Task<HttpResponseMessage> SaveAsync(HttpClient client, Guid cameraId, SaveSceneRequest request) =>
        client.PutAsJsonAsync($"/api/cameras/{cameraId}/scene", request);

    private static async Task<SceneRevisionResponse> SaveRevisionAsync(
        HttpClient client,
        Guid cameraId,
        SaveSceneRequest request)
    {
        using var response = await SaveAsync(client, cameraId, request);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Content.ReadFromJsonAsync<SceneRevisionResponse>())!;
    }

    private static Task<HttpResponseMessage> PostRawAsync(HttpClient client, Guid cameraId, string json) =>
        client.PutAsync(
            $"/api/cameras/{cameraId}/scene",
            new StringContent(json, Encoding.UTF8, "application/json"));

    private static async Task<string?> ReadProblemCodeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.TryGetProperty("code", out var code) ? code.GetString() : null;
    }

    private static SaveSceneRequest Request(
        int? expectedRevisionNumber,
        params SaveSceneZoneRequest[] zones) =>
        new(expectedRevisionNumber, null, null, null, zones, []);

    private static SaveSceneRequest Request(
        int? expectedRevisionNumber,
        SaveSceneZoneRequest zone,
        IReadOnlyList<SaveSceneTripLineRequest> lines) =>
        new(expectedRevisionNumber, null, null, null, [zone], lines);

    private static SaveSceneZoneRequest Zone(
        string name,
        Guid? zoneId = null,
        bool enabled = true,
        string? kind = null,
        double offset = 0) =>
        new(
            zoneId,
            name,
            kind,
            enabled,
            [
                Point(0.1 + offset, 0.1),
                Point(0.4 + offset, 0.1),
                Point(0.4 + offset, 0.4),
                Point(0.1 + offset, 0.4),
            ],
            null);

    private static SaveSceneTripLineRequest Line(string name) =>
        new(null, name, true, Point(0.1, 0.5), Point(0.9, 0.5), true, "inbound", "outbound");

    private static ScenePointRequest Point(double x, double y) => new(x, y);
}
