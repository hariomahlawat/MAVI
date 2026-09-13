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

        // Existing completed rows predate the publication protocol. Giving each
        // one a sequence places all historical intelligence before the first
        // post-migration search/completion watermark. Exact relative order is
        // immaterial because future latest-run selection is sequence-based.
        migrationBuilder.Sql($$"""
            UPDATE processing_runs
            SET visibility_sequence = nextval('{{ProcessingVisibilityBarrier.SequenceName}}')
            WHERE status = 'Completed'
              AND completed_at_utc IS NOT NULL;
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
