using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// ADR-027 §1, §2: Track review decisions and cases. Decisions, cases and notes are append-only (row triggers refuse
    /// UPDATE and DELETE, a statement trigger refuses TRUNCATE); a case item refuses DELETE and TRUNCATE and every UPDATE
    /// except recording its removal once. As for <c>audit_entries</c>, the guard protects against application defects and
    /// casual edits, not against a database owner who drops the triggers.
    /// </summary>
    public partial class AddReviewAndCases : Migration
    {
        internal const string Guards =
            """
            CREATE FUNCTION review_refuse_change() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = 'object_not_in_prerequisite_state',
                    TABLE = TG_TABLE_NAME,
                    MESSAGE = format('%s is append-only: %s is refused.', TG_TABLE_NAME, TG_OP);
            END $$;
            CREATE TRIGGER tr_track_review_decisions_append_only BEFORE UPDATE OR DELETE ON track_review_decisions
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_track_review_decisions_no_truncate BEFORE TRUNCATE ON track_review_decisions
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_cases_append_only BEFORE UPDATE OR DELETE ON cases
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_cases_no_truncate BEFORE TRUNCATE ON cases
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_case_notes_append_only BEFORE UPDATE OR DELETE ON case_notes
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_case_notes_no_truncate BEFORE TRUNCATE ON case_notes
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_case_items_no_delete BEFORE DELETE ON case_items
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_case_items_no_truncate BEFORE TRUNCATE ON case_items
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();

            -- The only change a case item accepts: its removal, recorded once; everything it was added with stays.
            CREATE FUNCTION case_items_removal_only() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF OLD.removed_at_utc IS NULL AND NEW.removed_at_utc IS NOT NULL
                   AND NEW.id = OLD.id AND NEW.case_id = OLD.case_id AND NEW.kind = OLD.kind AND NEW.subject_id = OLD.subject_id
                   AND NEW.note IS NOT DISTINCT FROM OLD.note
                   AND NEW.added_by_operator_id = OLD.added_by_operator_id AND NEW.added_by_display_name = OLD.added_by_display_name
                   AND NEW.added_by_identity_source = OLD.added_by_identity_source AND NEW.added_at_utc = OLD.added_at_utc
                   AND NEW.added_audit_entry_id = OLD.added_audit_entry_id THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION USING
                    ERRCODE = 'object_not_in_prerequisite_state',
                    TABLE = 'case_items',
                    MESSAGE = 'case_items accepts only the recording of a removal, once.';
            END $$;
            CREATE TRIGGER tr_case_items_removal_only BEFORE UPDATE ON case_items
                FOR EACH ROW EXECUTE FUNCTION case_items_removal_only();
            """;

        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "cases",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    title = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: false),
                    purpose = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    created_by_operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    created_by_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    created_by_identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_cases", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "track_review_decisions",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    sequence = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityAlwaysColumn),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    decision = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    previous_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    resulting_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    note = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true),
                    operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    operator_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    decided_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    request_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_track_review_decisions", x => x.id);
                    table.CheckConstraint("ck_track_review_decisions_request_sha256", "request_sha256 ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("ck_track_review_decisions_result", "(decision = 'Confirmed' AND resulting_status = 'Confirmed') OR (decision = 'Rejected' AND resulting_status = 'Rejected') OR (decision = 'Cleared' AND resulting_status = 'Unreviewed' AND previous_status <> 'Unreviewed')");
                    table.ForeignKey(
                        name: "FK_track_review_decisions_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "case_items",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    case_id = table.Column<Guid>(type: "uuid", nullable: false),
                    kind = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    subject_id = table.Column<Guid>(type: "uuid", nullable: false),
                    note = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true),
                    added_by_operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    added_by_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    added_by_identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    added_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    added_audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false),
                    removal_note = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true),
                    removed_by_operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    removed_by_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    removed_by_identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    removed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    removed_audit_entry_id = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_case_items", x => x.id);
                    table.CheckConstraint("ck_case_items_removal", "(removed_at_utc IS NULL AND removed_by_operator_id IS NULL AND removed_by_display_name IS NULL AND removed_by_identity_source IS NULL AND removed_audit_entry_id IS NULL AND removal_note IS NULL) OR (removed_at_utc IS NOT NULL AND removed_by_operator_id IS NOT NULL AND removed_by_display_name IS NOT NULL AND removed_by_identity_source IS NOT NULL AND removed_audit_entry_id IS NOT NULL)");
                    table.ForeignKey(
                        name: "FK_case_items_cases_case_id",
                        column: x => x.case_id,
                        principalTable: "cases",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "case_notes",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    case_id = table.Column<Guid>(type: "uuid", nullable: false),
                    body = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: false),
                    author_operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    author_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    author_identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_case_notes", x => x.id);
                    table.ForeignKey(
                        name: "FK_case_notes_cases_case_id",
                        column: x => x.case_id,
                        principalTable: "cases",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_case_items_added_audit_entry_id",
                table: "case_items",
                column: "added_audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "IX_case_items_case_id_added_at_utc",
                table: "case_items",
                columns: new[] { "case_id", "added_at_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_case_items_removed_audit_entry_id",
                table: "case_items",
                column: "removed_audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "ix_case_items_subject",
                table: "case_items",
                columns: new[] { "kind", "subject_id" });

            migrationBuilder.CreateIndex(
                name: "ux_case_items_active_subject",
                table: "case_items",
                columns: new[] { "case_id", "kind", "subject_id" },
                unique: true,
                filter: "removed_at_utc IS NULL");

            migrationBuilder.CreateIndex(
                name: "IX_case_notes_audit_entry_id",
                table: "case_notes",
                column: "audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "IX_case_notes_case_id_created_at_utc",
                table: "case_notes",
                columns: new[] { "case_id", "created_at_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_cases_audit_entry_id",
                table: "cases",
                column: "audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "IX_cases_created_at_utc",
                table: "cases",
                column: "created_at_utc");

            migrationBuilder.CreateIndex(
                name: "IX_track_review_decisions_audit_entry_id",
                table: "track_review_decisions",
                column: "audit_entry_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_track_review_decisions_sequence",
                table: "track_review_decisions",
                column: "sequence",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_track_review_decisions_track_sequence",
                table: "track_review_decisions",
                columns: new[] { "track_id", "sequence" });
            migrationBuilder.Sql(Guards);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Dropping these tables would lose recorded operator decisions and leave tracks.review_status without its
            // history; an earlier binary cannot rebuild either. Refuse while any exist (as AddVisionFinalization does).
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM track_review_decisions) OR EXISTS (SELECT 1 FROM cases) THEN
                        RAISE EXCEPTION 'review_or_case_history_present';
                    END IF;
                END $$;
                """);

            migrationBuilder.DropTable(
                name: "case_items");

            migrationBuilder.DropTable(
                name: "case_notes");

            migrationBuilder.DropTable(
                name: "track_review_decisions");

            migrationBuilder.DropTable(
                name: "cases");

            migrationBuilder.Sql("DROP FUNCTION case_items_removal_only(); DROP FUNCTION review_refuse_change();");
        }
    }
}
#pragma warning restore CA1861
