using System.Data;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Endpoints;

public static class StorageTopologyEndpoints
{
    public static IEndpointRouteBuilder MapStorageTopologyEndpoints(
        this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/system/storage-topology", GetAsync);
        return endpoints;
    }

    private static async Task<IResult> GetAsync(
        MaviDbContext db,
        IOptions<MediaStorageOptions> storageOptions,
        CancellationToken cancellationToken)
    {
        var connection = db.Database.GetDbConnection();
        var closeWhenDone = connection.State != ConnectionState.Open;
        if (closeWhenDone)
            await connection.OpenAsync(cancellationToken);

        string databaseIdentitySha256;
        try
        {
            await using var command = connection.CreateCommand();
            command.CommandText =
                "select current_database() || '|' || " +
                "coalesce(inet_server_addr()::text, 'local-socket') || '|' || " +
                "coalesce(inet_server_port()::text, 'local')";
            var value = await command.ExecuteScalarAsync(cancellationToken);
            var rawDatabaseTopology = Convert.ToString(
                value,
                System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
            databaseIdentitySha256 = DatabaseIdentitySha256(rawDatabaseTopology);
        }
        finally
        {
            if (closeWhenDone)
                await connection.CloseAsync();
        }

        var assembly = typeof(Program).Assembly;
        var metadata = assembly
            .GetCustomAttributes<AssemblyMetadataAttribute>()
            .ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);
        metadata.TryGetValue("MaviBuild", out var build);
        metadata.TryGetValue("MaviCommit", out var commit);

        var options = storageOptions.Value;
        var response = new
        {
            schemaVersion = "mavi-storage-topology-attestation-v1",
            maviBuild = string.IsNullOrWhiteSpace(build) ? "unknown-development" : build,
            maviCommit = string.IsNullOrWhiteSpace(commit) ? "unknown-development" : commit,
            operationalHostIdentitySha256 = HostIdentitySha256(),
            databaseIdentitySha256,
            managedMediaRootIdentitySha256 = RootIdentitySha256(options.RootPath),
            acceptedEvidenceRootIdentitySha256 = RootIdentitySha256(options.EvidenceRootPath)
        };
        return Results.Ok(response);
    }

    internal static string DatabaseIdentitySha256(string rawDatabaseTopology)
    {
        if (string.IsNullOrWhiteSpace(rawDatabaseTopology) ||
            rawDatabaseTopology.Count(character => character == '|') != 2)
        {
            throw new InvalidOperationException(
                "Database topology identity is unavailable.");
        }

        var payload = Encoding.UTF8.GetBytes(
            $"mavi-database-topology-v1|{rawDatabaseTopology}");
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    internal static string HostIdentitySha256()
    {
        var hostname = Environment.MachineName.Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(hostname))
            throw new InvalidOperationException("Operational host name is unavailable.");

        string family;
        string machineIdentity;
        if (OperatingSystem.IsWindows())
        {
            family = "windows";
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Cryptography");
            machineIdentity = Convert.ToString(
                key?.GetValue("MachineGuid"),
                System.Globalization.CultureInfo.InvariantCulture)?.Trim().ToLowerInvariant()
                ?? string.Empty;
        }
        else if (OperatingSystem.IsLinux())
        {
            family = "linux";
            machineIdentity = File.ReadAllText("/etc/machine-id").Trim().ToLowerInvariant();
        }
        else
        {
            throw new PlatformNotSupportedException(
                "Operational host identity is supported only on Windows and Linux.");
        }

        if (string.IsNullOrWhiteSpace(machineIdentity))
            throw new InvalidOperationException("Operational machine identity is unavailable.");

        var payload = Encoding.UTF8.GetBytes(
            $"{family}|{hostname}|{machineIdentity}");
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    internal static string RootIdentitySha256(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Storage root path is required.", nameof(path));

        var canonical = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        if (OperatingSystem.IsWindows())
            canonical = canonical.ToLowerInvariant();

        var payload = Encoding.UTF8.GetBytes(
            $"mavi-storage-root-v1|{(OperatingSystem.IsWindows() ? "windows" : "posix")}|{canonical}");
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }
}
