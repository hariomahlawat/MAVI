using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class HardenVisionJobLeases : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<byte[]>(
                name: "lease_token_hash",
                table: "vision_jobs",
                type: "bytea",
                nullable: true);

            migrationBuilder.Sql("""
                UPDATE vision_jobs
                SET lease_expires_at_utc = LEAST(lease_expires_at_utc, CURRENT_TIMESTAMP)
                WHERE status = 'Leased' AND lease_token_hash IS NULL;
                """);

            migrationBuilder.CreateIndex(
                name: "ix_vision_jobs_expired_lease",
                table: "vision_jobs",
                column: "lease_expires_at_utc",
                filter: "status = 'Leased'");

            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_lease_token_hash",
                table: "vision_jobs",
                sql: "lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ix_vision_jobs_expired_lease",
                table: "vision_jobs");

            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_lease_token_hash",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "lease_token_hash",
                table: "vision_jobs");
        }
    }
}
