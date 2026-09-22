using System.Globalization;
using System.Text.Json;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The switch and the output contract shared by every Slice-7 qualification
/// harness.
/// </summary>
/// <remarks>
/// These harnesses are deliberately not ordinary tests. They generate a heavy
/// corpus and measure it, which is minutes of work and megabytes of evidence, so
/// they stay out of the normal suite and run only when asked:
///
/// <code>
/// MAVI_QUALIFICATION=1 \
/// MAVI_TEST_DB_CONNECTION="Host=...;Database=mavi_qual;Username=postgres;Password=..." \
/// dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~Qualification"
/// </code>
///
/// Nothing here is specific to a PostgreSQL version. The same command produces
/// the qualification evidence once it is pointed at PostgreSQL 18; run against
/// 16 it produces engineering observations that are explicitly *not*
/// qualification evidence, which is why the captured environment records the
/// server version beside every measurement.
/// </remarks>
public static class QualificationGate
{
    public const string EnabledVariable = "MAVI_QUALIFICATION";
    public const string OutputVariable = "MAVI_QUALIFICATION_OUT";

    /// <summary>Whether the operator asked for the heavy qualification pass.</summary>
    public static bool Enabled =>
        string.Equals(Environment.GetEnvironmentVariable(EnabledVariable), "1", StringComparison.Ordinal);

    /// <summary>Where evidence is written. Created on demand.</summary>
    public static string OutputDirectory
    {
        get
        {
            var configured = Environment.GetEnvironmentVariable(OutputVariable);
            var path = string.IsNullOrWhiteSpace(configured)
                ? Path.Combine(Path.GetTempPath(), "mavi-qualification")
                : configured;
            Directory.CreateDirectory(path);
            return path;
        }
    }

    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    /// <summary>Writes one evidence document, and returns where it landed.</summary>
    public static string Write(string name, object evidence)
    {
        var path = Path.Combine(OutputDirectory, name);
        File.WriteAllText(path, JsonSerializer.Serialize(evidence, Json));
        return path;
    }

    /// <summary>
    /// The reference environment, captured from the machine actually running the
    /// measurement rather than described by hand.
    /// </summary>
    /// <remarks>
    /// The PostgreSQL server version is the field that decides whether the run is
    /// qualification evidence at all, so it is read from the live connection and
    /// recorded verbatim beside every result.
    /// </remarks>
    public static async Task<IReadOnlyDictionary<string, string>> CaptureEnvironmentAsync(
        string connectionString,
        CancellationToken cancellationToken = default)
    {
        var environment = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["capturedAtUtc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["gitSha"] = ReadGitSha(),
            ["os"] = System.Runtime.InteropServices.RuntimeInformation.OSDescription,
            ["osArchitecture"] = System.Runtime.InteropServices.RuntimeInformation.OSArchitecture.ToString(),
            ["processArchitecture"] = System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString(),
            ["dotnet"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            ["logicalCores"] = Environment.ProcessorCount.ToString(CultureInfo.InvariantCulture),
        };

        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);

        environment["postgresVersion"] = await ScalarAsync(connection, "show server_version", cancellationToken);
        environment["postgresVersionFull"] = await ScalarAsync(connection, "select version()", cancellationToken);
        environment["pgvector"] = await ScalarAsync(
            connection,
            "select coalesce((select extversion from pg_extension where extname = 'vector'), 'not installed')",
            cancellationToken);

        foreach (var setting in new[]
        {
            "shared_buffers", "work_mem", "effective_cache_size", "maintenance_work_mem",
            "max_parallel_workers_per_gather", "random_page_cost", "jit",
        })
        {
            environment["pg." + setting] = await ScalarAsync(connection, $"show {setting}", cancellationToken);
        }

        // The qualification rule in one field, so no reader has to infer it.
        var major = environment["postgresVersion"].Split('.')[0];
        environment["isQualificationGradeDatabase"] =
            (int.TryParse(major, out var parsed) && parsed >= 18) ? "true" : "false";

        return environment;
    }

    private static async Task<string> ScalarAsync(
        NpgsqlConnection connection,
        string sql,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        var value = await command.ExecuteScalarAsync(cancellationToken);
        return value?.ToString() ?? string.Empty;
    }

    private static string ReadGitSha()
    {
        try
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null && !Directory.Exists(Path.Combine(directory.FullName, ".git")))
            {
                directory = directory.Parent;
            }

            if (directory is null) return "unknown";
            var head = File.ReadAllText(Path.Combine(directory.FullName, ".git", "HEAD")).Trim();
            if (!head.StartsWith("ref:", StringComparison.Ordinal)) return head;

            var reference = head[4..].Trim();
            var refPath = Path.Combine(directory.FullName, ".git", reference.Replace('/', Path.DirectorySeparatorChar));
            return File.Exists(refPath) ? File.ReadAllText(refPath).Trim() : "unknown";
        }
        catch (IOException)
        {
            return "unknown";
        }
    }
}
