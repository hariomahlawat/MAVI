using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class PreserveRecordingTimeProvenance : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "recording_time_zone_id",
                table: "video_assets",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "recording_utc_offset_minutes",
                table: "video_assets",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.Sql("""
                UPDATE video_assets AS v
                SET recording_time_zone_id = c.time_zone_id,
                    recording_utc_offset_minutes = CAST(EXTRACT(EPOCH FROM
                        ((v.recording_start_utc AT TIME ZONE c.time_zone_id) -
                         (v.recording_start_utc AT TIME ZONE 'UTC'))) / 60 AS integer)
                FROM cameras AS c
                WHERE c.id = v.camera_id;
                """);

            migrationBuilder.AlterColumn<string>(
                name: "recording_time_zone_id",
                table: "video_assets",
                type: "character varying(64)",
                maxLength: 64,
                nullable: false,
                oldClrType: typeof(string),
                oldType: "character varying(64)",
                oldMaxLength: 64,
                oldNullable: true);

            migrationBuilder.AddCheckConstraint(
                name: "ck_video_assets_recording_utc_offset",
                table: "video_assets",
                sql: "recording_utc_offset_minutes BETWEEN -840 AND 840");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_video_assets_recording_utc_offset",
                table: "video_assets");

            migrationBuilder.DropColumn(
                name: "recording_time_zone_id",
                table: "video_assets");

            migrationBuilder.DropColumn(
                name: "recording_utc_offset_minutes",
                table: "video_assets");
        }
    }
}
