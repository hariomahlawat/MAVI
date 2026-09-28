using Mavi.Domain.VisualAttributes;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using NpgsqlTypes;

namespace Mavi.Infrastructure.VisualAttributes;

/// <summary>
/// Writes one completion's Track outcomes and attribute facts with binary <c>COPY</c> on the
/// publication transaction's own connection (S2b plan §13; implementation record §5).
/// </summary>
/// <remarks>
/// The rows are built by the domain factories, so every invariant the aggregate states still
/// holds, and PostgreSQL enforces every CHECK, unique and foreign-key constraint on each copied
/// row exactly as on an INSERT. Nothing is visible before the transaction commits. Change-
/// tracked inserts cost ≈ 9 s for the 90,000 rows of the worst admitted shape at 10,000
/// Tracks — most of a 15 s request budget; COPY writes the same rows in well under a second.
/// </remarks>
internal static class VisualAttributeFactWriter
{
    public static async Task WriteAsync(
        MaviDbContext db,
        IReadOnlyList<VisualAttributeTrackOutcome> outcomes,
        IReadOnlyList<VisualAttribute> attributes,
        CancellationToken cancellationToken)
    {
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException("Visual attribute facts are written only inside the publication transaction.");
        var connection = (NpgsqlConnection)db.Database.GetDbConnection();

        await using (var outcomeImport = await connection.BeginBinaryImportAsync(
            "COPY visual_attribute_track_outcomes (analysis_id, track_id, outcome, reason) FROM STDIN (FORMAT BINARY)", cancellationToken))
        {
            foreach (var outcome in outcomes)
            {
                await outcomeImport.StartRowAsync(cancellationToken);
                await outcomeImport.WriteAsync(outcome.AnalysisId, NpgsqlDbType.Uuid, cancellationToken);
                await outcomeImport.WriteAsync(outcome.TrackId, NpgsqlDbType.Uuid, cancellationToken);
                await outcomeImport.WriteAsync(outcome.Outcome.ToString(), NpgsqlDbType.Varchar, cancellationToken);
                await WriteNullableAsync(outcomeImport, outcome.Reason, NpgsqlDbType.Varchar, cancellationToken);
            }

            await outcomeImport.CompleteAsync(cancellationToken);
        }

        await using var attributeImport = await connection.BeginBinaryImportAsync(
            "COPY visual_attributes (id, analysis_id, track_id, attribute_type, outcome, value, confidence, supporting_observation_id) " +
            "FROM STDIN (FORMAT BINARY)", cancellationToken);
        foreach (var attribute in attributes)
        {
            await attributeImport.StartRowAsync(cancellationToken);
            await attributeImport.WriteAsync(attribute.Id, NpgsqlDbType.Uuid, cancellationToken);
            await attributeImport.WriteAsync(attribute.AnalysisId, NpgsqlDbType.Uuid, cancellationToken);
            await attributeImport.WriteAsync(attribute.TrackId, NpgsqlDbType.Uuid, cancellationToken);
            await attributeImport.WriteAsync(attribute.AttributeType, NpgsqlDbType.Varchar, cancellationToken);
            await attributeImport.WriteAsync(attribute.Outcome.ToString(), NpgsqlDbType.Varchar, cancellationToken);
            await WriteNullableAsync(attributeImport, attribute.Value, NpgsqlDbType.Varchar, cancellationToken);
            if (attribute.Confidence is { } confidence)
                await attributeImport.WriteAsync(confidence, NpgsqlDbType.Double, cancellationToken);
            else
                await attributeImport.WriteNullAsync(cancellationToken);
            if (attribute.SupportingObservationId is { } supporting)
                await attributeImport.WriteAsync(supporting, NpgsqlDbType.Uuid, cancellationToken);
            else
                await attributeImport.WriteNullAsync(cancellationToken);
        }

        await attributeImport.CompleteAsync(cancellationToken);
    }

    private static Task WriteNullableAsync(NpgsqlBinaryImporter importer, string? value, NpgsqlDbType type, CancellationToken cancellationToken) =>
        value is null ? importer.WriteNullAsync(cancellationToken) : importer.WriteAsync(value, type, cancellationToken);
}
