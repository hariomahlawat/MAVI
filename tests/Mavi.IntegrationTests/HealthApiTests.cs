using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class HealthApiTests(PostgresFixture database)
{
    [Fact]
    public async Task GetHealthUsesConfiguredTestDatabase()
    {
        using var factory = new ApiTestFactory();
        Assert.Equal(database.ConnectionString, factory.ConnectionString);
        await factory.ResetAndMigrateAsync();
        using var scope = factory.Services.CreateScope();
        var configuredDatabase = scope.ServiceProvider
            .GetRequiredService<MaviDbContext>()
            .Database.GetDbConnection().Database;
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/api/health");

        response.EnsureSuccessStatusCode();
        Assert.Equal("mavi_test", configuredDatabase);
    }
}
