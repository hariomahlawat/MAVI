using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddProcessingOrchestration : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_attempts",
                table: "vision_jobs");

            migrationBuilder.DropIndex(
                name: "IX_processing_runs_video_asset_id",
                table: "processing_runs");

            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_attempts",
                table: "vision_jobs",
                sql: "attempt_count >= 0");

            migrationBuilder.CreateIndex(
                name: "ux_processing_runs_active_video",
                table: "processing_runs",
                column: "video_asset_id",
                unique: true,
                filter: "status IN ('Queued', 'Running')");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_attempts",
                table: "vision_jobs");

            migrationBuilder.DropIndex(
                name: "ux_processing_runs_active_video",
                table: "processing_runs");

            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_attempts",
                table: "vision_jobs",
                sql: "attempt_count >= 0 AND attempt_count <= 3");

            migrationBuilder.CreateIndex(
                name: "IX_processing_runs_video_asset_id",
                table: "processing_runs",
                column: "video_asset_id");
        }
    }
}
