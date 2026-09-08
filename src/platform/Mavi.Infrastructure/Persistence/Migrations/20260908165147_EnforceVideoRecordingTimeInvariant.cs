using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class EnforceVideoRecordingTimeInvariant : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddCheckConstraint(
                name: "ck_video_assets_recording_end",
                table: "video_assets",
                sql: "recording_end_utc = recording_start_utc + duration_ms * INTERVAL '1 millisecond'");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_video_assets_recording_end",
                table: "video_assets");
        }
    }
}
