using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The one place the integration tests learn which PostgreSQL database they may use and reset.
/// </summary>
/// <remarks>
/// <para>
/// <c>MAVI_TEST_DB_CONNECTION</c> names the server and the base database, which must be <c>mavi_test</c>.
/// Without <c>MAVI_TEST_DB_RUN_ID</c> the tests use exactly that database, as they always have (CI runs one
/// job per server). With it, they use an isolated database <c>mavi_test_&lt;id&gt;</c> on the same server,
/// created on first use, so concurrently active worktrees or agents never reset each other's schema:
/// </para>
/// <list type="bullet">
/// <item><c>MAVI_TEST_DB_RUN_ID=auto</c> derives the id from this checkout's repository root (12 hex of its
/// SHA-256), so each worktree gets its own stable database without any per-run configuration;</item>
/// <item>any other value is a caller-chosen run identifier, reduced to <c>[a-z0-9]</c> (a long one is
/// shortened with a hash so two different ids never collide).</item>
/// </list>
/// <para>
/// Cleanup is bounded: the tests only ever reset the schema of their own database, and
/// <see cref="DropIsolatedDatabaseAsync"/> drops only this run's derived database — never <c>mavi_test</c>
/// itself and never another run's.
/// </para>
/// </remarks>
public static partial class TestDatabase
{
    public const string BaseName = "mavi_test";
    public const string ConnectionVariable = "MAVI_TEST_DB_CONNECTION";
    public const string RunIdVariable = "MAVI_TEST_DB_RUN_ID";
    public const string AutoRunId = "auto";
    private const int MaximumSuffixLength = 40;

    private static readonly Lazy<string> Resolved = new(Resolve, LazyThreadSafetyMode.ExecutionAndPublication);

    /// <summary>The connection string of this run's database, created if it is a derived one.</summary>
    public static string ConnectionString => Resolved.Value;

    public static string DatabaseName => new NpgsqlConnectionStringBuilder(ConnectionString).Database!;

    /// <summary>Whether this run uses a derived database rather than the shared base one.</summary>
    public static bool IsIsolated => !string.Equals(DatabaseName, BaseName, StringComparison.Ordinal);

    /// <summary><c>mavi_test</c> or <c>mavi_test_&lt;suffix&gt;</c>: the only names a test may reset.</summary>
    public static bool IsTestDatabaseName(string? name) =>
        string.Equals(name, BaseName, StringComparison.Ordinal) || (name is not null && DerivedName().IsMatch(name));

    /// <summary>The derived database name for a run id (<c>auto</c> resolved by the caller).</summary>
    public static string DerivedDatabaseName(string runId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(runId);
        var reduced = new string(runId.ToLowerInvariant().Where(character => character is >= 'a' and <= 'z' or >= '0' and <= '9').ToArray());
        if (reduced.Length == 0 || reduced.Length > MaximumSuffixLength || !string.Equals(reduced, runId, StringComparison.Ordinal))
        {
            // Lossy or long: keep a readable prefix and make the name injective with a hash of the original.
            var hash = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(runId)))[..12];
            reduced = (reduced.Length > 24 ? reduced[..24] : reduced) + hash;
        }

        return BaseName + "_" + reduced;
    }

    /// <summary>The <c>auto</c> run id: a stable digest of this checkout's repository root.</summary>
    /// <remarks>
    /// Case is folded only on Windows, where one directory may be spelled in several cases. Elsewhere paths are
    /// case-sensitive, so <c>/work/MAVI</c> and <c>/work/mavi</c> are distinct checkouts and keep distinct
    /// databases: not folding can only separate runs, never make two runs share a database.
    /// </remarks>
    public static string WorktreeRunId(string repositoryRoot) => WorktreeRunId(repositoryRoot, OperatingSystem.IsWindows());

    internal static string WorktreeRunId(string repositoryRoot, bool foldCase)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryRoot);
        var normalised = Path.GetFullPath(repositoryRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (foldCase)
            normalised = normalised.ToLowerInvariant();
        return "wt" + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(normalised)))[..12];
    }

    /// <summary>Drops this run's derived database. Refuses the shared base database and any other name.</summary>
    public static async Task DropIsolatedDatabaseAsync()
    {
        var name = DatabaseName;
        if (!IsIsolated || !DerivedName().IsMatch(name))
            throw new InvalidOperationException("Only this run's derived test database may be dropped.");

        await using var connection = new NpgsqlConnection(MaintenanceConnectionString(ConnectionString));
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand($"DROP DATABASE IF EXISTS \"{name}\" WITH (FORCE)", connection);
        await command.ExecuteNonQueryAsync();
    }

    private static string Resolve()
    {
        var configured = Environment.GetEnvironmentVariable(ConnectionVariable)
            ?? throw new InvalidOperationException($"{ConnectionVariable} is required for PostgreSQL integration tests.");
        var builder = new NpgsqlConnectionStringBuilder(configured);
        if (!string.Equals(builder.Database, BaseName, StringComparison.Ordinal))
            throw new InvalidOperationException($"{ConnectionVariable} must name the {BaseName} database; isolation derives from it.");

        var runId = Environment.GetEnvironmentVariable(RunIdVariable);
        if (string.IsNullOrWhiteSpace(runId))
            return builder.ConnectionString;

        if (string.Equals(runId, AutoRunId, StringComparison.Ordinal))
            runId = WorktreeRunId(FindRepositoryRoot());
        builder.Database = DerivedDatabaseName(runId);
        EnsureCreated(builder);
        return builder.ConnectionString;
    }

    private static void EnsureCreated(NpgsqlConnectionStringBuilder target)
    {
        using var connection = new NpgsqlConnection(MaintenanceConnectionString(target.ConnectionString));
        connection.Open();
        using (var exists = new NpgsqlCommand("SELECT 1 FROM pg_database WHERE datname = $1", connection))
        {
            exists.Parameters.AddWithValue(target.Database!);
            if (exists.ExecuteScalar() is not null)
                return;
        }

        try
        {
            // The name is validated by DerivedName(), so quoting it is safe.
            using var create = new NpgsqlCommand($"CREATE DATABASE \"{target.Database}\"", connection);
            create.ExecuteNonQuery();
        }
        catch (PostgresException exception) when (exception.SqlState is PostgresErrorCodes.DuplicateDatabase or PostgresErrorCodes.UniqueViolation)
        {
            // Another process of the same run created it first.
        }
    }

    private static string MaintenanceConnectionString(string connectionString) =>
        new NpgsqlConnectionStringBuilder(connectionString) { Database = "postgres", Pooling = false }.ConnectionString;

    private static string FindRepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
                return directory.FullName;
        }

        throw new InvalidOperationException($"{RunIdVariable}=auto needs the repository root (MAVI.sln) above the test binaries.");
    }

    [GeneratedRegex("^mavi_test_[a-z0-9]{1,40}$", RegexOptions.CultureInvariant)]
    private static partial Regex DerivedName();
}
