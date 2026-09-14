using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Server.IIS;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class Task15HostingTests
{
    [Fact]
    public void InProcessIisAndMultipartLimitsMatchTask15RequestCeiling()
    {
        using var factory = new ApiTestFactory();
        const long expected = 3L * 1024 * 1024 * 1024 + 1024 * 1024;

        var iis = factory.Services.GetRequiredService<IOptions<IISServerOptions>>().Value;
        var form = factory.Services.GetRequiredService<IOptions<FormOptions>>().Value;

        Assert.Equal(expected, iis.MaxRequestBodySize);
        Assert.Equal(expected, form.MultipartBodyLengthLimit);
    }

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
