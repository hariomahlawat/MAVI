using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddSourceVideoShaUniqueness : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateIndex(
                name: "ux_artifacts_source_video_sha256",
                table: "artifacts",
                column: "sha256",
                unique: true,
                filter: "artifact_type = 'SourceVideo'");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ux_artifacts_source_video_sha256",
                table: "artifacts");
        }
    }
}
