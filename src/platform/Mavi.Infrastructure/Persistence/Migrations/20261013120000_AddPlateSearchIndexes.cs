using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

#pragma warning disable CA1861 // Generated migration index operator arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// The Stage-4 plate search access paths (plan §2.8; Stage 4 PR-4): the <c>pg_trgm</c> contrib
    /// extension, a GIN trigram index on <c>plate_track_texts.normalised_text</c> for <c>contains</c>, and a
    /// <c>text_pattern_ops</c> b-tree on the same column for <c>prefix</c> and <c>exact</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Additive only: two indexes on PR-3's table and one extension; no table, column or row changes, and
    /// the PR-3 migration is untouched. Binary rollback stays safe: an older platform ignores both indexes.
    /// </para>
    /// <para>
    /// <c>pg_trgm</c> ships with PostgreSQL itself (contrib) and is part of the MAVI PostgreSQL runtime pack,
    /// whose staging verifies it; MAVI Setup creates it as the administrator, so this
    /// <c>CREATE EXTENSION IF NOT EXISTS</c> is then a no-op. It is a trusted extension, so the database
    /// owner can also create it here on a database Setup did not prepare. Down drops the two indexes and
    /// leaves the extension: Setup owns it, and another database object may use it.
    /// </para>
    /// </remarks>
    public partial class AddPlateSearchIndexes : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterDatabase()
                .Annotation("Npgsql:PostgresExtension:pg_trgm", ",,")
                .Annotation("Npgsql:PostgresExtension:vector", ",,")
                .OldAnnotation("Npgsql:PostgresExtension:vector", ",,");

            migrationBuilder.CreateIndex(
                name: "ix_plate_track_texts_normalised_text_pattern",
                table: "plate_track_texts",
                column: "normalised_text")
                .Annotation("Npgsql:IndexOperators", new[] { "text_pattern_ops" });

            migrationBuilder.CreateIndex(
                name: "ix_plate_track_texts_normalised_text_trgm",
                table: "plate_track_texts",
                column: "normalised_text")
                .Annotation("Npgsql:IndexMethod", "gin")
                .Annotation("Npgsql:IndexOperators", new[] { "gin_trgm_ops" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ix_plate_track_texts_normalised_text_pattern",
                table: "plate_track_texts");

            migrationBuilder.DropIndex(
                name: "ix_plate_track_texts_normalised_text_trgm",
                table: "plate_track_texts");

            migrationBuilder.AlterDatabase()
                .Annotation("Npgsql:PostgresExtension:vector", ",,")
                .OldAnnotation("Npgsql:PostgresExtension:pg_trgm", ",,")
                .OldAnnotation("Npgsql:PostgresExtension:vector", ",,");
        }
    }
}
