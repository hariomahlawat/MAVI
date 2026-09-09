using System.Net;
using System.Text;

namespace Mavi.IntegrationTests;

public sealed class WorkerContractCanonicalizationRegressionTests
{
    [Theory]
    [InlineData("{\"SchemaVersion\":\"2.0\",\"WorkerId\":\"worker-a\"}")]
    [InlineData("{\"schemaVersion\":\"2.0\",\"WorkerID\":\"worker-a\"}")]
    [InlineData("{\"SCHEMAVERSION\":\"2.0\",\"workerId\":\"worker-a\"}")]
    public async Task WorkerLeaseRequestRejectsNonCanonicalPropertyNameCasing(string json)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var response = await client.PostAsync(
            "/api/vision/jobs/lease",
            new StringContent(json, Encoding.UTF8, "application/json"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }
}
