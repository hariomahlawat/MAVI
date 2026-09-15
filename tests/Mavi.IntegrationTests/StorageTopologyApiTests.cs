using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Npgsql;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class StorageTopologyApiTests
{
    [Fact]
    public async Task ReportsLiveDatabaseAndHashedStorageRootsWithoutRawPaths()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();

        string expectedDatabaseIdentity;
        await using (var connection = new NpgsqlConnection(factory.ConnectionString))
        {
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand(
                "select current_database() || '|' || " +
                "coalesce(inet_server_addr()::text, 'local-socket') || '|' || " +
                "coalesce(inet_server_port()::text, 'local')",
                connection);
            expectedDatabaseIdentity = (string)(await command.ExecuteScalarAsync())!;
        }

        using var client = factory.CreateClient();
        using var response = await client.GetAsync("/api/system/storage-topology");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;

        Assert.Equal(
            "mavi-storage-topology-attestation-v1",
            root.GetProperty("schemaVersion").GetString());
        var hostIdentity = root.GetProperty("operationalHostIdentitySha256").GetString();
        Assert.NotNull(hostIdentity);
        Assert.Matches("^[0-9a-f]{64}$", hostIdentity!);

        Assert.Equal(
            expectedDatabaseIdentity,
            root.GetProperty("databaseIdentity").GetString());
        Assert.Equal(
            RootIdentity(factory.MediaRoot),
            root.GetProperty("managedMediaRootIdentitySha256").GetString());
        Assert.Equal(
            RootIdentity(factory.EvidenceRoot),
            root.GetProperty("acceptedEvidenceRootIdentitySha256").GetString());

        var json = root.GetRawText();
        Assert.DoesNotContain(factory.MediaRoot, json, StringComparison.Ordinal);
        Assert.DoesNotContain(factory.EvidenceRoot, json, StringComparison.Ordinal);
        Assert.DoesNotContain(factory.ConnectionString, json, StringComparison.Ordinal);
    }

    private static string RootIdentity(string path)
    {
        var canonical = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        if (OperatingSystem.IsWindows())
            canonical = canonical.ToLowerInvariant();

        var payload = Encoding.UTF8.GetBytes(
            $"mavi-storage-root-v1|{(OperatingSystem.IsWindows() ? "windows" : "posix")}|{canonical}");
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }
}
