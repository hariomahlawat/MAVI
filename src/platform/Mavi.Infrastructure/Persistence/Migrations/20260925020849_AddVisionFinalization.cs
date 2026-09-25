using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// S1.4 B3 asynchronous finalization, slice F1: the schema for the durable hand-off
    /// (<c>docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md</c> §4, §7).
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>vision_jobs</c> gains the finalizer claim state (attempt count, claim token hash,
    /// claim expiry/extension, last error) and the hand-off time. Every new column is nullable
    /// or defaulted, so existing Queued / Leased / Completed / Failed rows are valid unchanged;
    /// no row is rewritten. <c>vision_finalization_payloads</c> holds the exact accepted
    /// completion body per <c>(job, attempt)</c>, bounded by the completion request-body limit,
    /// with its length, SHA-256 and completion digest checked by the database.
    /// </para>
    /// <para>
    /// The status value <c>Finalizing</c> is a string like the others and needs no enum
    /// migration, but a preceding binary cannot parse it. Rolling the binary back is supported
    /// only while no job is Finalizing (plan §15.3); <see cref="Down"/> refuses otherwise, and
    /// refuses to drop retained payloads whose jobs have not finished.
    /// </para>
    /// </remarks>
    public partial class AddVisionFinalization : Migration
    {
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<DateTimeOffset>(
                name: "finalization_accepted_at_utc",
                table: "vision_jobs",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "finalization_attempt_count",
                table: "vision_jobs",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<DateTimeOffset>(
                name: "finalization_claim_expires_at_utc",
                table: "vision_jobs",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<DateTimeOffset>(
                name: "finalization_claim_extended_at_utc",
                table: "vision_jobs",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<byte[]>(
                name: "finalization_claim_token_hash",
                table: "vision_jobs",
                type: "bytea",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "finalization_last_error_code",
                table: "vision_jobs",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.CreateTable(
                name: "vision_finalization_payloads",
                columns: table => new
                {
                    job_id = table.Column<Guid>(type: "uuid", nullable: false),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    payload = table.Column<byte[]>(type: "bytea", nullable: false),
                    payload_length = table.Column<long>(type: "bigint", nullable: false),
                    payload_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    completion_digest = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    accepted_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_vision_finalization_payloads", x => new { x.job_id, x.attempt_count });
                    table.CheckConstraint("ck_vision_finalization_payloads_attempt", "attempt_count >= 1");
                    table.CheckConstraint("ck_vision_finalization_payloads_digest", "completion_digest ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("ck_vision_finalization_payloads_length", "payload_length = octet_length(payload) AND payload_length >= 1 AND payload_length <= 50331648");
                    table.CheckConstraint("ck_vision_finalization_payloads_sha256", "payload_sha256 ~ '^[0-9a-f]{64}$'");
                    table.ForeignKey(
                        name: "FK_vision_finalization_payloads_vision_jobs_job_id",
                        column: x => x.job_id,
                        principalTable: "vision_jobs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            // The finalizer's claim query filters Finalizing rows by claim expiry (plan §7.2).
            migrationBuilder.CreateIndex(
                name: "ix_vision_jobs_finalizing_claim",
                table: "vision_jobs",
                column: "finalization_claim_expires_at_utc",
                filter: "status = 'Finalizing'");

            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_finalization_attempts",
                table: "vision_jobs",
                sql: "finalization_attempt_count >= 0");

            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_finalization_claim_token_hash",
                table: "vision_jobs",
                sql: "finalization_claim_token_hash IS NULL OR octet_length(finalization_claim_token_hash) = 32");

            // A Finalizing row keeps the replay-authentication facts and the digest (plan §6).
            migrationBuilder.AddCheckConstraint(
                name: "ck_vision_jobs_finalizing_facts",
                table: "vision_jobs",
                sql: "status <> 'Finalizing' OR (completion_digest IS NOT NULL AND finalization_accepted_at_utc IS NOT NULL AND lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND attempt_count >= 1)");
        }

        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // A preceding binary cannot represent a Finalizing job or finish its hand-off, and a
            // retained payload of an unfinished job is the only copy of that completion. Refuse.
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM vision_jobs WHERE status = 'Finalizing') THEN
                        RAISE EXCEPTION 'vision_jobs_finalizing_rows_present';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM vision_finalization_payloads p
                        JOIN vision_jobs j ON j.id = p.job_id
                        WHERE j.status NOT IN ('Completed', 'Failed', 'Cancelled')) THEN
                        RAISE EXCEPTION 'vision_finalization_payloads_unfinished_present';
                    END IF;
                END $$;
                """);

            migrationBuilder.DropTable(
                name: "vision_finalization_payloads");

            migrationBuilder.DropIndex(
                name: "ix_vision_jobs_finalizing_claim",
                table: "vision_jobs");

            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_finalization_attempts",
                table: "vision_jobs");

            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_finalization_claim_token_hash",
                table: "vision_jobs");

            migrationBuilder.DropCheckConstraint(
                name: "ck_vision_jobs_finalizing_facts",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_accepted_at_utc",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_attempt_count",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_claim_expires_at_utc",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_claim_extended_at_utc",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_claim_token_hash",
                table: "vision_jobs");

            migrationBuilder.DropColumn(
                name: "finalization_last_error_code",
                table: "vision_jobs");
        }
    }
}
