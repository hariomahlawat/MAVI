using Mavi.Domain.Plates;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using NpgsqlTypes;

namespace Mavi.Infrastructure.Plates;

/// <summary>
/// Writes one plate completion's Track outcomes, plate observations, kept readings and Track texts with
/// binary <c>COPY</c> on the publication transaction's own connection (the attribute plane's writer
/// discipline). The rows are built by the domain factories, so every aggregate invariant holds, and
/// PostgreSQL enforces every CHECK, unique and foreign-key constraint on each copied row as on an INSERT.
/// Nothing is visible before the transaction commits.
/// </summary>
internal static class PlateFactWriter
{
    public static async Task WriteAsync(
        MaviDbContext db,
        IReadOnlyList<PlateTrackOutcome> outcomes,
        IReadOnlyList<PlateObservation> observations,
        IReadOnlyList<PlateTrackText> texts,
        CancellationToken cancellationToken)
    {
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException("Plate facts are written only inside the publication transaction.");
        var connection = (NpgsqlConnection)db.Database.GetDbConnection();

        await using (var import = await connection.BeginBinaryImportAsync(
            "COPY plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) " +
            "FROM STDIN (FORMAT BINARY)", cancellationToken))
        {
            foreach (var outcome in outcomes)
            {
                await import.StartRowAsync(cancellationToken);
                await import.WriteAsync(outcome.AnalysisId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(outcome.TrackId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(outcome.Outcome.ToString(), NpgsqlDbType.Varchar, cancellationToken);
                await WriteNullableAsync(import, outcome.Reason, cancellationToken);
                await import.WriteAsync(outcome.PlateObservationCount, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(outcome.DistinctTextCount, NpgsqlDbType.Integer, cancellationToken);
            }

            await import.CompleteAsync(cancellationToken);
        }

        await using (var import = await connection.BeginBinaryImportAsync(
            "COPY plate_observations (id, analysis_id, track_id, source_observation_id, plate_index, box_x, box_y, box_width, box_height, " +
            "crop_width, crop_height, detector_confidence, outcome) FROM STDIN (FORMAT BINARY)", cancellationToken))
        {
            foreach (var observation in observations)
            {
                await import.StartRowAsync(cancellationToken);
                await import.WriteAsync(observation.Id, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(observation.AnalysisId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(observation.TrackId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(observation.SourceObservationId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(observation.PlateIndex, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.BoxX, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.BoxY, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.BoxWidth, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.BoxHeight, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.CropWidth, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.CropHeight, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(observation.DetectorConfidence, NpgsqlDbType.Double, cancellationToken);
                await import.WriteAsync(observation.Outcome.ToString(), NpgsqlDbType.Varchar, cancellationToken);
            }

            await import.CompleteAsync(cancellationToken);
        }

        await using (var import = await connection.BeginBinaryImportAsync(
            "COPY plate_readings (plate_observation_id, rank, raw_text, raw_line_count, confidence, normalised_text, normalisation_outcome, " +
            "normalisation_reason, format_class) FROM STDIN (FORMAT BINARY)", cancellationToken))
        {
            foreach (var reading in observations.SelectMany(observation => observation.Readings))
            {
                await import.StartRowAsync(cancellationToken);
                await import.WriteAsync(reading.PlateObservationId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(reading.Rank, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(reading.RawText, NpgsqlDbType.Varchar, cancellationToken);
                await import.WriteAsync(reading.RawLineCount, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(reading.Confidence, NpgsqlDbType.Double, cancellationToken);
                await WriteNullableAsync(import, reading.NormalisedText, cancellationToken);
                await import.WriteAsync(reading.NormalisationOutcome.ToString(), NpgsqlDbType.Varchar, cancellationToken);
                await WriteNullableAsync(import, reading.NormalisationReason, cancellationToken);
                await WriteNullableAsync(import, reading.FormatClass, cancellationToken);
            }

            await import.CompleteAsync(cancellationToken);
        }

        await using (var import = await connection.BeginBinaryImportAsync(
            "COPY plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) " +
            "FROM STDIN (FORMAT BINARY)", cancellationToken))
        {
            foreach (var text in texts)
            {
                await import.StartRowAsync(cancellationToken);
                await import.WriteAsync(text.AnalysisId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(text.TrackId, NpgsqlDbType.Uuid, cancellationToken);
                await import.WriteAsync(text.NormalisedText, NpgsqlDbType.Varchar, cancellationToken);
                await import.WriteAsync(text.SupportCount, NpgsqlDbType.Integer, cancellationToken);
                await import.WriteAsync(text.MaxConfidence, NpgsqlDbType.Double, cancellationToken);
                await import.WriteAsync(text.BestPlateObservationId, NpgsqlDbType.Uuid, cancellationToken);
            }

            await import.CompleteAsync(cancellationToken);
        }
    }

    private static Task WriteNullableAsync(NpgsqlBinaryImporter importer, string? value, CancellationToken cancellationToken) =>
        value is null ? importer.WriteNullAsync(cancellationToken) : importer.WriteAsync(value, NpgsqlDbType.Varchar, cancellationToken);
}
