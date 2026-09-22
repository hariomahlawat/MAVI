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
    /// <summary>The one major version the platform accepts, and so the only one that qualifies.</summary>
    public const int RequiredPostgreSqlMajorVersion = 18;

    /// <summary>The parent plan's relevant-fact prerequisite for a qualification measurement.</summary>
    public const int MinimumRelevantFactCount = 100_000;

    public const string EnabledVariable = "MAVI_QUALIFICATION";
    public const string OutputVariable = "MAVI_QUALIFICATION_OUT";

    /// <summary>Whether the operator asked for the heavy qualification pass.</summary>
    /// <remarks>
    /// Unset means "not asked for", and the harness is a no-op. Set to anything other
    /// than <c>1</c> throws rather than skipping: an operator who typed
    /// <c>MAVI_QUALIFICATION=true</c> believes they are running the qualification, and
    /// silently returning green would be a run that passed without executing.
    /// </remarks>
    public static bool Enabled => IsEnabledValue(Environment.GetEnvironmentVariable(EnabledVariable));

    /// <summary>The rule above, as a function, so it can be pinned without touching the process environment.</summary>
    public static bool IsEnabledValue(string? value)
    {
        if (string.IsNullOrEmpty(value)) return false;
        if (string.Equals(value, "1", StringComparison.Ordinal)) return true;
        throw new InvalidOperationException(
            $"{EnabledVariable} is set to '{value}'. The qualification harness runs only when it is "
            + "exactly '1'; leave it unset to skip. Refusing to skip silently, because a run that is "
            + "believed to have happened and did not is worse than no run.");
    }

    /// <summary>Whether this environment's server is the one that can qualify.</summary>
    public static bool IsQualificationGrade(IReadOnlyDictionary<string, string> environment)
    {
        ArgumentNullException.ThrowIfNull(environment);
        return environment.TryGetValue(QualificationGradeKey, out var value)
            && string.Equals(value, "true", StringComparison.Ordinal);
    }

    public const string QualificationGradeKey = "isQualificationGradeDatabase";

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
    /// Claims an evidence filename at the start of a measurement, overwriting whatever
    /// was there with an explicitly incomplete record.
    /// </summary>
    /// <remarks>
    /// Without this, a run that throws part-way leaves the <em>previous</em> run's
    /// evidence on disk: complete, plausible, correctly named and quietly stale. An
    /// operator collecting results after a failed run would collect the old ones.
    /// Claiming the name first means a failed run leaves a file that says so.
    /// </remarks>
    public static string Begin(string name, string runId, IReadOnlyDictionary<string, string> environment)
    {
        return Write(name, new
        {
            status = "incomplete — the measurement did not finish; this file is not evidence",
            runId,
            startedAtUtc = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            environment,
        });
    }

    /// <summary>A fresh identifier stamped into both the placeholder and the result.</summary>
    public static string NewRunId() => Guid.NewGuid().ToString("N");

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

        // The committed SHA says what was checked out, not what was built and run. A
        // tree with uncommitted edits reports its parent commit quite happily, so the
        // built assembly identifies itself too: module id and build timestamp pin the
        // evidence to one binary even when the SHA does not.
        var assembly = typeof(QualificationGate).Assembly;
        environment["testAssembly"] = assembly.GetName().Name ?? "unknown";
        environment["testAssemblyModuleId"] = assembly.ManifestModule.ModuleVersionId.ToString("N");
        environment["testAssemblyBuiltUtc"] = SafeWriteTimeUtc(assembly.Location);

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
        //
        // Exactly 18, not "18 or later". The product's own prerequisite check is an
        // equality (`DatabaseMigrationStartup`: majorVersion != required is refused),
        // so a run against 19 is a run against a planner the platform does not accept
        // — and labelling it qualification-grade would let it be presented as
        // satisfying the PostgreSQL 18 exit gate.
        var major = environment["postgresVersion"].Split('.')[0];
        environment["isQualificationGradeDatabase"] =
            (int.TryParse(major, out var parsed) && parsed == RequiredPostgreSqlMajorVersion) ? "true" : "false";

        return environment;
    }

    private static string SafeWriteTimeUtc(string? path)
    {
        try
        {
            return string.IsNullOrEmpty(path) || !File.Exists(path)
                ? "unknown"
                : File.GetLastWriteTimeUtc(path).ToString("O", CultureInfo.InvariantCulture);
        }
        catch (IOException)
        {
            return "unknown";
        }
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
