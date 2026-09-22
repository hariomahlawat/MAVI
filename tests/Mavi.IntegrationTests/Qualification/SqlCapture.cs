using System.Data.Common;
using System.Text;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Npgsql;
using NpgsqlTypes;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>One statement the product actually issued, with its parameters.</summary>
public sealed record CapturedStatement(string Sql, IReadOnlyList<CapturedParameter> Parameters);

public sealed record CapturedParameter(string Name, object? Value, NpgsqlDbType? DbType);

/// <summary>
/// Records the SQL a product code path really executed, so the plan evidence
/// measures the query the product runs rather than one written by hand for the
/// report.
/// </summary>
/// <remarks>
/// Hand-written EXPLAIN SQL is the classic way a performance report becomes
/// fiction: the measured statement drifts from the generated one and nobody
/// notices. Capturing from the live command means a change to the repository
/// changes the measurement automatically.
/// </remarks>
public sealed class SqlCapture : DbCommandInterceptor
{
    private readonly List<CapturedStatement> _statements = [];

    public IReadOnlyList<CapturedStatement> Statements => _statements;

    public void Clear() => _statements.Clear();

    public override InterceptionResult<DbDataReader> ReaderExecuting(
        DbCommand command,
        CommandEventData eventData,
        InterceptionResult<DbDataReader> result)
    {
        Record(command);
        return result;
    }

    public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
        DbCommand command,
        CommandEventData eventData,
        InterceptionResult<DbDataReader> result,
        CancellationToken cancellationToken = default)
    {
        Record(command);
        return ValueTask.FromResult(result);
    }

    private void Record(DbCommand command)
    {
        // Only SELECTs are planned; the advisory-lock and sequence calls that
        // bracket a snapshot are control statements, not analytical queries. They
        // also never arrive here, because only reader execution is intercepted and
        // those go out as scalar or non-query commands — this filter is the second
        // line rather than the first.
        var sql = command.CommandText.TrimStart();
        if (!sql.StartsWith("SELECT", StringComparison.OrdinalIgnoreCase)) return;

        var parameters = new List<CapturedParameter>(command.Parameters.Count);
        foreach (DbParameter parameter in command.Parameters)
        {
            parameters.Add(new CapturedParameter(
                parameter.ParameterName,
                parameter.Value,
                parameter is NpgsqlParameter npgsql ? npgsql.NpgsqlDbType : null));
        }

        _statements.Add(new CapturedStatement(command.CommandText, parameters));
    }

    /// <summary>
    /// Replays one captured statement under <c>EXPLAIN (ANALYZE, BUFFERS)</c> and
    /// returns the plan text.
    /// </summary>
    /// <remarks>
    /// Replayed on its own connection with the original parameter values and
    /// types, so the planner sees the same inputs. ANALYZE genuinely executes the
    /// statement, which is what makes actual-versus-estimated rows and buffer
    /// counts real rather than predicted.
    /// </remarks>
    public static async Task<string> ExplainAsync(
        string connectionString,
        CapturedStatement statement,
        CancellationToken cancellationToken = default)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);

        await using var command = new NpgsqlCommand(
            "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT) " + statement.Sql,
            connection);

        foreach (var parameter in statement.Parameters)
        {
            var npgsql = new NpgsqlParameter(parameter.Name, parameter.Value ?? DBNull.Value);
            if (parameter.DbType is { } type) npgsql.NpgsqlDbType = type;
            command.Parameters.Add(npgsql);
        }

        var plan = new StringBuilder();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            plan.AppendLine(reader.GetString(0));
        }

        return plan.ToString();
    }
}
