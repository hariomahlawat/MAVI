using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// Stage 4 PR-4 option (b), ADR-019: a b-tree on <c>tracks (object_class, end_timestamp_utc)</c>, in the form
    /// measured on the frozen skewed corpus. It serves the windowed plate coverage count (a time window's lower
    /// bound is <c>end_timestamp_utc &gt;= fromUtc</c>), which otherwise scans 10^6 Tracks sequentially (Q12).
    /// </summary>
    /// <remarks>
    /// Additive and reversible: one index, no row or column change; Down drops it. Binary rollback is safe, as an
    /// older platform ignores the index. It is built non-concurrently inside the migration transaction, so Track
    /// writes wait for the build (seconds at 10^6 Tracks); migrations run before the platform serves requests.
    /// </remarks>
    public partial class AddTrackVehicleEndTimestampIndex : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateIndex(
                name: "ix_tracks_object_class_end_timestamp_utc",
                table: "tracks",
                columns: new[] { "object_class", "end_timestamp_utc" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ix_tracks_object_class_end_timestamp_utc",
                table: "tracks");
        }
    }
}
