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

public static class DatabaseMigrationStartup
{
    // Stable, application-owned PostgreSQL advisory-lock key pair.
    // The lock is session-scoped and prevents concurrent MAVI instances
    // from attempting EF Core schema migration at the same time.
    private const int AdvisoryLockNamespace = 1296127561; // "MAVI"
    private const int AdvisoryLockPurpose = 1397248845;

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
                var applied = (await db.Database
                    .GetAppliedMigrationsAsync(cancellationToken))
                    .ToHashSet(StringComparer.Ordinal);
                var pending = (await db.Database
                    .GetPendingMigrationsAsync(cancellationToken))
                    .ToArray();

                logger.LogInformation(
                    "Database migration startup check: {AppliedCount} applied, {PendingCount} pending.",
                    applied.Count,
                    pending.Length);

                if (pending.Length == 0)
                {
                    logger.LogInformation("Database schema is current.");
                    return;
                }

                foreach (var migration in pending)
                    logger.LogInformation("Pending database migration: {Migration}", migration);

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

                logger.LogInformation(
                    "Database migrations completed successfully. Applied {MigrationCount} migration(s).",
                    pending.Length);
            }
            finally
            {
                await ReleaseMigrationLockAsync(connection, cancellationToken);
            }
        }
        catch (OperationCanceledException) when (timeout.IsCancellationRequested)
        {
            logger.LogCritical(
                "Timed out after {TimeoutSeconds}s waiting for the MAVI database migration lock.",
                options.LockTimeoutSeconds);
            throw new InvalidOperationException(
                "Timed out waiting for the MAVI database migration lock.");
        }
        catch (Exception exception)
        {
            logger.LogCritical(
                exception,
                "Database startup migration failed. MAVI will not start with an unverified schema state.");
            throw;
        }
        finally
        {
            if (closeWhenDone && connection.State != ConnectionState.Closed)
                await connection.CloseAsync();
        }
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

        throw new OperationCanceledException(cancellationToken);
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
