using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// ADR-010 §4: the append-only <c>audit_entries</c> table. Row triggers refuse UPDATE and DELETE and a
    /// statement trigger refuses TRUNCATE, whatever the client; the guard protects against application
    /// defects and casual edits, not against a database owner who drops the triggers.
    /// </summary>
    public partial class AddAuditEntries : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "audit_entries",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    operator_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    action = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    subject_type = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    subject_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    recorded_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    payload_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    correlation_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_audit_entries", x => x.id);
                    table.CheckConstraint("ck_audit_entries_payload_sha256", "payload_sha256 ~ '^[0-9a-f]{64}$'");
                });

            migrationBuilder.CreateIndex(
                name: "ix_audit_entries_recorded_at_utc",
                table: "audit_entries",
                column: "recorded_at_utc");

            migrationBuilder.CreateIndex(
                name: "ix_audit_entries_subject",
                table: "audit_entries",
                columns: new[] { "subject_type", "subject_id", "recorded_at_utc" });

            migrationBuilder.Sql(AppendOnlyGuard);
        }

        /// <summary>The append-only guard; SQLSTATE 55000 (object_not_in_prerequisite_state) names the table.</summary>
        internal const string AppendOnlyGuard =
            """
            CREATE FUNCTION audit_entries_refuse_change() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = 'object_not_in_prerequisite_state',
                    TABLE = 'audit_entries',
                    MESSAGE = format('audit_entries is append-only: %s is refused.', TG_OP);
            END $$;

            CREATE TRIGGER tr_audit_entries_append_only
                BEFORE UPDATE OR DELETE ON audit_entries
                FOR EACH ROW EXECUTE FUNCTION audit_entries_refuse_change();

            CREATE TRIGGER tr_audit_entries_no_truncate
                BEFORE TRUNCATE ON audit_entries
                FOR EACH STATEMENT EXECUTE FUNCTION audit_entries_refuse_change();
            """;

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "audit_entries");

            migrationBuilder.Sql("DROP FUNCTION audit_entries_refuse_change();");
        }
    }
}
#pragma warning restore CA1861
