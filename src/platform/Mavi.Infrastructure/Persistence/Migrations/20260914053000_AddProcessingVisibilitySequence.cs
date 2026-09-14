using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

[DbContext(typeof(MaviDbContext))]
[Migration("20260914053000_AddProcessingVisibilitySequence")]
public sealed class AddProcessingVisibilitySequence : Migration
{
    private static readonly string[] VideoVisibilityColumns =
        ["video_asset_id", "visibility_sequence"];

    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateSequence<long>(
            name: ProcessingVisibilityBarrier.SequenceName);

        migrationBuilder.AddColumn<long>(
            name: "visibility_sequence",
            table: "processing_runs",
            type: "bigint",
            nullable: true);

        // Existing completed rows predate the publication protocol. Preserve
        // their established CompletedAtUtc/Id ordering exactly while translating
        // it into the new monotonic publication order. Do not use nextval() from
        // an unordered UPDATE: PostgreSQL does not guarantee row visitation order.
        migrationBuilder.Sql($"""
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        ORDER BY completed_at_utc ASC, id ASC
                    )::bigint AS visibility_sequence
                FROM processing_runs
                WHERE status = 'Completed'
                  AND completed_at_utc IS NOT NULL
            )
            UPDATE processing_runs AS run
            SET visibility_sequence = ranked.visibility_sequence
            FROM ranked
            WHERE run.id = ranked.id;

            SELECT setval(
                '{ProcessingVisibilityBarrier.SequenceName}',
                COALESCE(
                    (SELECT MAX(visibility_sequence) FROM processing_runs),
                    1
                ),
                EXISTS (
                    SELECT 1
                    FROM processing_runs
                    WHERE visibility_sequence IS NOT NULL
                )
            );
            """);

        migrationBuilder.CreateIndex(
            name: "ux_processing_runs_visibility_sequence",
            table: "processing_runs",
            column: "visibility_sequence",
            unique: true,
            filter: "visibility_sequence IS NOT NULL");

        migrationBuilder.CreateIndex(
            name: "ix_processing_runs_video_visibility",
            table: "processing_runs",
            columns: VideoVisibilityColumns,
            filter: "status = 'Completed' AND visibility_sequence IS NOT NULL");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropIndex(
            name: "ix_processing_runs_video_visibility",
            table: "processing_runs");

        migrationBuilder.DropIndex(
            name: "ux_processing_runs_visibility_sequence",
            table: "processing_runs");

        migrationBuilder.DropColumn(
            name: "visibility_sequence",
            table: "processing_runs");

        migrationBuilder.DropSequence(
            name: ProcessingVisibilityBarrier.SequenceName);
    }
}
