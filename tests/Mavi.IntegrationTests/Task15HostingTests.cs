using System.Net;
using System.Net.Http.Json;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class Task15HostingTests
{
    [Fact]
    public async Task PublishedHostKeepsApiAndSpaRoutingSeparated()
    {
        var webRoot = Path.Combine(Path.GetTempPath(), $"mavi-task15-web-{Guid.NewGuid():N}");
        var assets = Path.Combine(webRoot, "assets");
        Directory.CreateDirectory(assets);
        await File.WriteAllTextAsync(Path.Combine(webRoot, "index.html"), "<!doctype html><title>MAVI Task15 Host</title><div id=\"root\"></div>");
        await File.WriteAllTextAsync(Path.Combine(assets, "app.js"), "globalThis.__maviTask15 = true;");

        try
        {
            using var factory = new ApiTestFactory { StaticWebRoot = webRoot };
            using var client = factory.CreateClient();

            using var deepLink = await client.GetAsync($"/processing/{Guid.CreateVersion7()}");
            Assert.Equal(HttpStatusCode.OK, deepLink.StatusCode);
            Assert.Contains("MAVI Task15 Host", await deepLink.Content.ReadAsStringAsync(), StringComparison.Ordinal);

            using var searchLink = await client.GetAsync("/search?objectClass=Person");
            Assert.Equal(HttpStatusCode.OK, searchLink.StatusCode);
            Assert.Contains("MAVI Task15 Host", await searchLink.Content.ReadAsStringAsync(), StringComparison.Ordinal);

            var reviewVideoId = Guid.CreateVersion7();
            var reviewTrackId = Guid.CreateVersion7();
            using var reviewLink = await client.GetAsync($"/review/video/{reviewVideoId}?trackId={reviewTrackId}");
            Assert.Equal(HttpStatusCode.OK, reviewLink.StatusCode);
            Assert.Contains("MAVI Task15 Host", await reviewLink.Content.ReadAsStringAsync(), StringComparison.Ordinal);

            using var health = await client.GetAsync("/api/health");
            Assert.Equal(HttpStatusCode.OK, health.StatusCode);
            Assert.Equal("application/json", health.Content.Headers.ContentType?.MediaType);
            var healthBody = await health.Content.ReadFromJsonAsync<Dictionary<string, object?>>();
            Assert.NotNull(healthBody);
            Assert.True(healthBody.ContainsKey("status"));

            using var unknownApi = await client.GetAsync("/api/task15-unknown");
            Assert.Equal(HttpStatusCode.NotFound, unknownApi.StatusCode);
            Assert.DoesNotContain("MAVI Task15 Host", await unknownApi.Content.ReadAsStringAsync(), StringComparison.Ordinal);

            using var asset = await client.GetAsync("/assets/app.js");
            Assert.Equal(HttpStatusCode.OK, asset.StatusCode);
            Assert.Contains("__maviTask15", await asset.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        }
        finally
        {
            if (Directory.Exists(webRoot))
                Directory.Delete(webRoot, true);
        }
    }
}
