using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

[DbContext(typeof(MaviDbContext))]
[Migration("20260913082000_AddVisionResultCompletion")]
public sealed class AddVisionResultCompletion : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "runtime_provenance_json",
            table: "processing_runs",
            type: "jsonb",
            nullable: true);

        migrationBuilder.AddColumn<string>(
            name: "completion_digest",
            table: "vision_jobs",
            type: "character varying(64)",
            maxLength: 64,
            nullable: true);

        migrationBuilder.AddCheckConstraint(
            name: "ck_vision_jobs_completion_digest",
            table: "vision_jobs",
            sql: "completion_digest IS NULL OR (octet_length(completion_digest) = 64 AND completion_digest ~ '^[0-9a-f]+')");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropCheckConstraint(
            name: "ck_vision_jobs_completion_digest",
            table: "vision_jobs");

        migrationBuilder.DropColumn(
            name: "runtime_provenance_json",
            table: "processing_runs");

        migrationBuilder.DropColumn(
            name: "completion_digest",
            table: "vision_jobs");
    }
}
