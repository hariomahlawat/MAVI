using System.Net.Http.Json;
using System.Text.Json;

namespace Mavi.IntegrationTests;

public sealed class SystemConfigApiTests
{
    [Fact]
    public async Task ReturnsOnlyConfiguredSafeDisplayTimeZone()
    {
        using var factory = new ApiTestFactory();
        using var client = factory.CreateClient();
        var json = await client.GetStringAsync("/api/system/config");
        using var document = JsonDocument.Parse(json);
        Assert.Single(document.RootElement.EnumerateObject());
        Assert.Equal("Asia/Kolkata", document.RootElement.GetProperty("displayTimeZoneId").GetString());
    }
}
