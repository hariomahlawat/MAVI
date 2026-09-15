using System.Data;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Mavi.Api.Startup;

public sealed class DatabaseMigrationOptions
{
    public const string SectionName = "DatabaseMigrations";

    public bool Enabled { get; init; } = true;
    public int LockTimeoutSeconds { get; init; } = 120;
    public int CommandTimeoutSeconds { get; init; } = 300;
}

public sealed class DatabasePrerequisiteOptions
{
    public const string SectionName = "DatabasePrerequisites";

    public int RequiredPostgreSqlMajorVersion { get; init; } = 18;
    public bool RequirePgVector { get; init; } = true;
}

public static class DatabaseMigrationStartup
{
    // Stable, application-owned PostgreSQL advisory-lock key pair.
    // The lock is session-scoped and prevents concurrent MAVI instances
    // from attempting EF Core schema migration at the same time.
    private const int AdvisoryLockNamespace = 1296127561; // "MAVI"
    private const int AdvisoryLockPurpose = 1397248845;

    private static readonly Action<ILogger, int, int, Exception?> LogMigrationStatus =
        LoggerMessage.Define<int, int>(
            LogLevel.Information,
            new EventId(1800, "DatabaseMigrationStatus"),
            "Database migration startup check: {AppliedCount} applied, {PendingCount} pending.");

    private static readonly Action<ILogger, Exception?> LogSchemaCurrent =
        LoggerMessage.Define(
            LogLevel.Information,
            new EventId(1801, "DatabaseSchemaCurrent"),
            "Database schema is current.");

    private static readonly Action<ILogger, string, Exception?> LogPendingMigration =
        LoggerMessage.Define<string>(
            LogLevel.Information,
            new EventId(1802, "PendingDatabaseMigration"),
            "Pending database migration: {Migration}");

    private static readonly Action<ILogger, int, Exception?> LogMigrationsApplied =
        LoggerMessage.Define<int>(
            LogLevel.Information,
            new EventId(1803, "DatabaseMigrationsApplied"),
            "Database migrations completed successfully. Applied {MigrationCount} migration(s).");

    private static readonly Action<ILogger, int, Exception?> LogMigrationLockTimeout =
        LoggerMessage.Define<int>(
            LogLevel.Critical,
            new EventId(1804, "DatabaseMigrationLockTimeout"),
            "Timed out after {TimeoutSeconds}s waiting for the MAVI database migration lock.");

    private static readonly Action<ILogger, Exception?> LogMigrationFailure =
        LoggerMessage.Define(
            LogLevel.Critical,
            new EventId(1805, "DatabaseMigrationFailure"),
            "Database startup migration failed. MAVI will not start with an unverified schema state.");

    private static readonly Action<ILogger, int, string, Exception?> LogDatabasePrerequisitesVerified =
        LoggerMessage.Define<int, string>(
            LogLevel.Information,
            new EventId(1806, "DatabasePrerequisitesVerified"),
            "Verified PostgreSQL {PostgreSqlMajorVersion} and pgvector {PgVectorVersion} prerequisites.");

    public static IServiceCollection AddDatabaseMigrationStartup(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        services.AddOptions<DatabaseMigrationOptions>()
            .Bind(configuration.GetSection(DatabaseMigrationOptions.SectionName))
            .Validate(
                options => options.LockTimeoutSeconds is >= 1 and <= 1800,
                "DatabaseMigrations:LockTimeoutSeconds must be between 1 and 1800.")
            .Validate(
                options => options.CommandTimeoutSeconds is >= 30 and <= 3600,
                "DatabaseMigrations:CommandTimeoutSeconds must be between 30 and 3600.")
            .ValidateOnStart();
        services.AddOptions<DatabasePrerequisiteOptions>()
            .Bind(configuration.GetSection(DatabasePrerequisiteOptions.SectionName))
            .Validate(
                options => options.RequiredPostgreSqlMajorVersion is >= 12 and <= 99,
                "DatabasePrerequisites:RequiredPostgreSqlMajorVersion is invalid.")
            .ValidateOnStart();

        return services;
    }

    public static async Task ApplyDatabaseMigrationsAsync(
        this WebApplication app,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(app);

        await using var scope = app.Services.CreateAsyncScope();
        var options = scope.ServiceProvider
            .GetRequiredService<IOptions<DatabaseMigrationOptions>>()
            .Value;
        if (!options.Enabled)
            return;

        var logger = scope.ServiceProvider
            .GetRequiredService<ILoggerFactory>()
            .CreateLogger("Mavi.DatabaseMigration");
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var prerequisites = scope.ServiceProvider
            .GetRequiredService<IOptions<DatabasePrerequisiteOptions>>()
            .Value;

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(options.LockTimeoutSeconds));

        var connection = (NpgsqlConnection)db.Database.GetDbConnection();
        var closeWhenDone = connection.State != ConnectionState.Open;

        try
        {
            if (closeWhenDone)
                await connection.OpenAsync(timeout.Token);

            await AcquireMigrationLockAsync(
                connection,
                TimeSpan.FromSeconds(options.LockTimeoutSeconds),
                timeout.Token);

            try
            {
                await EnsureDatabasePrerequisitesAsync(
                    connection,
                    prerequisites,
                    logger,
                    cancellationToken);

                var applied = (await db.Database
                    .GetAppliedMigrationsAsync(cancellationToken))
                    .ToHashSet(StringComparer.Ordinal);
                var pending = (await db.Database
                    .GetPendingMigrationsAsync(cancellationToken))
                    .ToArray();

                LogMigrationStatus(logger, applied.Count, pending.Length, null);

                if (pending.Length == 0)
                {
                    LogSchemaCurrent(logger, null);
                    return;
                }

                foreach (var migration in pending)
                    LogPendingMigration(logger, migration, null);

                var previousTimeout = db.Database.GetCommandTimeout();
                try
                {
                    db.Database.SetCommandTimeout(
                        TimeSpan.FromSeconds(options.CommandTimeoutSeconds));
                    await db.Database.MigrateAsync(cancellationToken);
                }
                finally
                {
                    db.Database.SetCommandTimeout(previousTimeout);
                }

                var remaining = (await db.Database
                    .GetPendingMigrationsAsync(cancellationToken))
                    .ToArray();
                if (remaining.Length != 0)
                {
                    throw new InvalidOperationException(
                        $"Database migration did not converge; {remaining.Length} migration(s) remain pending.");
                }

                LogMigrationsApplied(logger, pending.Length, null);
            }
            finally
            {
                await ReleaseMigrationLockAsync(connection, CancellationToken.None);
            }
        }
        catch (TimeoutException exception)
        {
            LogMigrationLockTimeout(
                logger,
                options.LockTimeoutSeconds,
                exception);
            throw new InvalidOperationException(
                "Timed out waiting for the MAVI database migration lock.",
                exception);
        }
        catch (OperationCanceledException) when (timeout.IsCancellationRequested)
        {
            LogMigrationLockTimeout(
                logger,
                options.LockTimeoutSeconds,
                null);
            throw new InvalidOperationException(
                "Timed out waiting for the MAVI database migration lock.");
        }
        catch (Exception exception)
        {
            LogMigrationFailure(logger, exception);
            throw;
        }
        finally
        {
            if (closeWhenDone && connection.State != ConnectionState.Closed)
                await connection.CloseAsync();
        }
    }

    private static async Task EnsureDatabasePrerequisitesAsync(
        NpgsqlConnection connection,
        DatabasePrerequisiteOptions options,
        ILogger logger,
        CancellationToken cancellationToken)
    {
        await using var versionCommand = connection.CreateCommand();
        versionCommand.CommandText =
            "select current_setting('server_version_num')::int;";
        var versionValue = await versionCommand.ExecuteScalarAsync(
            cancellationToken);
        var versionNumber = Convert.ToInt32(
            versionValue,
            System.Globalization.CultureInfo.InvariantCulture);
        var majorVersion = versionNumber / 10000;
        if (majorVersion != options.RequiredPostgreSqlMajorVersion)
        {
            throw new InvalidOperationException(
                $"MAVI requires PostgreSQL {options.RequiredPostgreSqlMajorVersion}; " +
                $"the connected server reports major version {majorVersion}.");
        }

        if (!options.RequirePgVector)
            return;

        await using var availabilityCommand = connection.CreateCommand();
        availabilityCommand.CommandText =
            "select default_version from pg_available_extensions " +
            "where name = 'vector';";
        var availableVersion = Convert.ToString(
            await availabilityCommand.ExecuteScalarAsync(cancellationToken),
            System.Globalization.CultureInfo.InvariantCulture);
        if (string.IsNullOrWhiteSpace(availableVersion))
        {
            throw new InvalidOperationException(
                "MAVI PostgreSQL prerequisite is missing: pgvector is not installed " +
                "for this PostgreSQL server. Install the approved offline pgvector " +
                "package before starting MAVI.");
        }

        try
        {
            await using var enableCommand = connection.CreateCommand();
            enableCommand.CommandText =
                "create extension if not exists vector;";
            await enableCommand.ExecuteNonQueryAsync(cancellationToken);
        }
        catch (PostgresException exception)
        {
            throw new InvalidOperationException(
                "pgvector is installed but MAVI could not enable the 'vector' extension. " +
                "The database principal must be permitted to create the approved extension.",
                exception);
        }

        await using var installedCommand = connection.CreateCommand();
        installedCommand.CommandText =
            "select extversion from pg_extension where extname = 'vector';";
        var installedVersion = Convert.ToString(
            await installedCommand.ExecuteScalarAsync(cancellationToken),
            System.Globalization.CultureInfo.InvariantCulture);
        if (string.IsNullOrWhiteSpace(installedVersion))
        {
            throw new InvalidOperationException(
                "MAVI could not verify the enabled pgvector extension.");
        }

        LogDatabasePrerequisitesVerified(
            logger,
            majorVersion,
            installedVersion,
            null);
    }

    private static async Task AcquireMigrationLockAsync(
        NpgsqlConnection connection,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var deadline = DateTime.UtcNow + timeout;

        while (DateTime.UtcNow < deadline)
        {
            await using var command = connection.CreateCommand();
            command.CommandText =
                "select pg_try_advisory_lock(@namespace, @purpose);";
            command.Parameters.AddWithValue("namespace", AdvisoryLockNamespace);
            command.Parameters.AddWithValue("purpose", AdvisoryLockPurpose);

            var acquired = await command.ExecuteScalarAsync(cancellationToken);
            if (acquired is true)
                return;

            await Task.Delay(TimeSpan.FromMilliseconds(250), cancellationToken);
        }

        throw new TimeoutException(
            "Timed out waiting for the MAVI database migration lock.");
    }

    private static async Task ReleaseMigrationLockAsync(
        NpgsqlConnection connection,
        CancellationToken cancellationToken)
    {
        if (connection.State != ConnectionState.Open)
            return;

        await using var command = connection.CreateCommand();
        command.CommandText =
            "select pg_advisory_unlock(@namespace, @purpose);";
        command.Parameters.AddWithValue("namespace", AdvisoryLockNamespace);
        command.Parameters.AddWithValue("purpose", AdvisoryLockPurpose);
        await command.ExecuteScalarAsync(cancellationToken);
    }
}
