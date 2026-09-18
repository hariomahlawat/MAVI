using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Contracts.Api.Cameras;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class CameraApiTests(PostgresFixture database)
{
    // Creation and retrieval
    [Fact]
    public async Task PostAndGetCameraRoundTripUsesTestDatabaseAndLocationHeader()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();

        var post = await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest(
            " cam-0002 ", "Main Gate", "UTC"));

        Assert.Equal(HttpStatusCode.Created, post.StatusCode);
        var created = await post.Content.ReadFromJsonAsync<CameraResponse>();
        Assert.NotNull(created);
        Assert.Equal("CAM-0002", created.Code);
        Assert.Equal($"/api/cameras/{created.Id}", post.Headers.Location?.OriginalString);

        var get = await client.GetAsync($"/api/cameras/{created.Id}");
        Assert.Equal(HttpStatusCode.OK, get.StatusCode);
        var retrieved = await get.Content.ReadFromJsonAsync<CameraResponse>();
        Assert.NotNull(retrieved);
        Assert.Equal(created.Id, retrieved.Id);
        Assert.Equal(created.Code, retrieved.Code);
        Assert.Equal(created.Name, retrieved.Name);
        Assert.Equal(created.TimeZoneId, retrieved.TimeZoneId);
        Assert.Equal("mavi_test", new Npgsql.NpgsqlConnectionStringBuilder(factory.ConnectionString).Database);
    }

    [Fact]
    public async Task DuplicateNormalizedCodeReturnsConflictCode()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest("CAM-DUP", "One", "UTC"));

        var response = await client.PostAsJsonAsync(
            "/api/cameras", new CreateCameraRequest(" cam-dup ", "Two", "UTC"));

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("camera_code_duplicate", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task InvalidTimezoneReturnsBadRequest()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync(
            "/api/cameras", new CreateCameraRequest("CAM-BAD", "Bad", "Not/A-Time-Zone"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("camera_timezone_invalid", await ReadProblemCodeAsync(response));
    }

    [Theory]
    [InlineData(null, "camera_timezone_required")]
    [InlineData("", "camera_timezone_required")]
    [InlineData("   ", "camera_timezone_required")]
    [InlineData("India Standard Time", "camera_timezone_invalid")]
    public async Task UntrustedTimezoneInputReturnsControlledValidation(string? timeZoneId, string code)
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        using var response = await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest("CAM-TZ", "Timezone", timeZoneId));
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(code, await ReadProblemCodeAsync(response));
    }


    [Fact]
    public async Task MissingCameraReturnsNotFoundCode()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();

        var response = await client.GetAsync($"/api/cameras/{Guid.CreateVersion7()}");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("camera_not_found", await ReadProblemCodeAsync(response));
    }

    [Fact]
    public async Task ListReturnsCreatedCamerasInCodeOrder()
    {
        using var factory = await CreateFactoryAsync();
        using var client = factory.CreateClient();
        await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest("CAM-Z", "Last", "UTC"));
        await client.PostAsJsonAsync("/api/cameras", new CreateCameraRequest("CAM-A", "First", "UTC"));

        var cameras = await client.GetFromJsonAsync<CameraResponse[]>("/api/cameras");

        Assert.Equal(["CAM-A", "CAM-Z"], cameras!.Select(camera => camera.Code));
    }

    // Test infrastructure
    private async Task<ApiTestFactory> CreateFactoryAsync()
    {
        Assert.Equal(database.ConnectionString, Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION"));
        var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        return factory;
    }

    private static async Task<string?> ReadProblemCodeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("code").GetString();
    }
}
