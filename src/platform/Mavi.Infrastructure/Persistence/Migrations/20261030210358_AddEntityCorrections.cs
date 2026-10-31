using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// ADR-027 §4: Entity membership and candidate decisions become append-only histories, with <c>tracks.entity_id</c>, the
    /// candidate's status fields and the new <c>entities.state</c>/<c>merged_into_entity_id</c> as projections. The histories are
    /// back-filled from S7's decisions: one decision row per decided candidate, and one <c>Joined</c> row per member Track from
    /// the earliest confirmed candidate of its Entity that names it (the one that brought it in, since membership only grew
    /// before this migration), with that decision's operator, time and audit entry. A member with no such candidate stops the
    /// migration (the NOT NULL columns refuse it) rather than inventing an attribution. Both tables reuse the append-only guard
    /// of <c>AddReviewAndCases</c>.
    /// </summary>
    public partial class AddEntityCorrections : Migration
    {
        internal const string BackfillAndGuards =
            """
            INSERT INTO entity_candidate_decisions (id, candidate_id, decision, entity_id, note, operator_id, operator_display_name,
                identity_source, at_utc, audit_entry_id)
            SELECT gen_random_uuid(), c.id, c.status, c.entity_id, c.decision_note, c.decided_by_operator_id, c.decided_by_display_name,
                c.decided_by_identity_source, c.decided_at_utc, c.decision_audit_entry_id
            FROM entity_candidates c
            WHERE c.status <> 'Open'
            ORDER BY c.decided_at_utc, c.id;

            INSERT INTO entity_membership_changes (id, track_id, entity_id, change, cause, candidate_id, note, operator_id,
                operator_display_name, identity_source, at_utc, audit_entry_id)
            SELECT gen_random_uuid(), t.id, t.entity_id, 'Joined', 'CandidateConfirmed', first.id, first.decision_note,
                first.decided_by_operator_id, first.decided_by_display_name, first.decided_by_identity_source, first.decided_at_utc,
                first.decision_audit_entry_id
            FROM tracks t
            LEFT JOIN LATERAL (
                SELECT c.* FROM entity_candidates c
                WHERE c.status = 'Confirmed' AND c.entity_id = t.entity_id AND (c.lower_track_id = t.id OR c.higher_track_id = t.id)
                ORDER BY c.decided_at_utc, c.id
                LIMIT 1) first ON TRUE
            WHERE t.entity_id IS NOT NULL
            ORDER BY first.decided_at_utc, t.id;

            CREATE TRIGGER tr_entity_membership_changes_append_only BEFORE UPDATE OR DELETE ON entity_membership_changes
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_entity_membership_changes_no_truncate BEFORE TRUNCATE ON entity_membership_changes
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_entity_candidate_decisions_append_only BEFORE UPDATE OR DELETE ON entity_candidate_decisions
                FOR EACH ROW EXECUTE FUNCTION review_refuse_change();
            CREATE TRIGGER tr_entity_candidate_decisions_no_truncate BEFORE TRUNCATE ON entity_candidate_decisions
                FOR EACH STATEMENT EXECUTE FUNCTION review_refuse_change();
            """;

        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<Guid>(
                name: "merged_into_entity_id",
                table: "entities",
                type: "uuid",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "state",
                table: "entities",
                type: "character varying(16)",
                maxLength: 16,
                nullable: false,
                defaultValue: "Active");

            migrationBuilder.CreateTable(
                name: "entity_candidate_decisions",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    sequence = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityAlwaysColumn),
                    candidate_id = table.Column<Guid>(type: "uuid", nullable: false),
                    decision = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    entity_id = table.Column<Guid>(type: "uuid", nullable: true),
                    note = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    operator_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_entity_candidate_decisions", x => x.id);
                    table.CheckConstraint("ck_entity_candidate_decisions_entity", "(decision = 'Confirmed') = (entity_id IS NOT NULL)");
                    table.ForeignKey(
                        name: "FK_entity_candidate_decisions_entities_entity_id",
                        column: x => x.entity_id,
                        principalTable: "entities",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_entity_candidate_decisions_entity_candidates_candidate_id",
                        column: x => x.candidate_id,
                        principalTable: "entity_candidates",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "entity_membership_changes",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    sequence = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityAlwaysColumn),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    entity_id = table.Column<Guid>(type: "uuid", nullable: false),
                    change = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    cause = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    candidate_id = table.Column<Guid>(type: "uuid", nullable: true),
                    note = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    operator_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: false),
                    identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    audit_entry_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_entity_membership_changes", x => x.id);
                    table.CheckConstraint("ck_entity_membership_changes_cause", "(cause = 'CandidateConfirmed' AND change = 'Joined' AND candidate_id IS NOT NULL) OR (cause = 'Unlinked' AND change = 'Left' AND candidate_id IS NULL) OR (cause = 'Merged' AND candidate_id IS NULL)");
                    table.ForeignKey(
                        name: "FK_entity_membership_changes_entities_entity_id",
                        column: x => x.entity_id,
                        principalTable: "entities",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_entity_membership_changes_entity_candidates_candidate_id",
                        column: x => x.candidate_id,
                        principalTable: "entity_candidates",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_entity_membership_changes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_entities_merged_into_entity_id",
                table: "entities",
                column: "merged_into_entity_id");

            migrationBuilder.AddCheckConstraint(
                name: "ck_entities_merge",
                table: "entities",
                sql: "(state = 'Active' AND merged_into_entity_id IS NULL) OR (state = 'Merged' AND merged_into_entity_id IS NOT NULL AND merged_into_entity_id <> id)");

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidate_decisions_audit_entry_id",
                table: "entity_candidate_decisions",
                column: "audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "ix_entity_candidate_decisions_candidate_sequence",
                table: "entity_candidate_decisions",
                columns: new[] { "candidate_id", "sequence" });

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidate_decisions_entity_id",
                table: "entity_candidate_decisions",
                column: "entity_id");

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidate_decisions_sequence",
                table: "entity_candidate_decisions",
                column: "sequence",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_entity_membership_changes_audit_entry_id",
                table: "entity_membership_changes",
                column: "audit_entry_id");

            migrationBuilder.CreateIndex(
                name: "IX_entity_membership_changes_candidate_id",
                table: "entity_membership_changes",
                column: "candidate_id");

            migrationBuilder.CreateIndex(
                name: "ix_entity_membership_changes_entity_sequence",
                table: "entity_membership_changes",
                columns: new[] { "entity_id", "sequence" });

            migrationBuilder.CreateIndex(
                name: "IX_entity_membership_changes_sequence",
                table: "entity_membership_changes",
                column: "sequence",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_entity_membership_changes_track_sequence",
                table: "entity_membership_changes",
                columns: new[] { "track_id", "sequence" });

            migrationBuilder.AddForeignKey(
                name: "FK_entities_entities_merged_into_entity_id",
                table: "entities",
                column: "merged_into_entity_id",
                principalTable: "entities",
                principalColumn: "id",
                onDelete: ReferentialAction.Restrict);

            migrationBuilder.Sql(BackfillAndGuards);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // S7's schema can hold only what S7 could decide: joins by confirmation and one decision per candidate. An unlink,
            // merge or reopen has no representation there and would be lost (and a re-Up could not back-fill it). Refuse.
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM entity_membership_changes WHERE cause <> 'CandidateConfirmed')
                       OR EXISTS (SELECT 1 FROM entity_candidate_decisions WHERE decision = 'Reopened')
                       OR EXISTS (SELECT 1 FROM entities WHERE state <> 'Active') THEN
                        RAISE EXCEPTION 'entity_correction_history_present';
                    END IF;
                END $$;
                """);

            migrationBuilder.DropForeignKey(
                name: "FK_entities_entities_merged_into_entity_id",
                table: "entities");

            migrationBuilder.DropTable(
                name: "entity_candidate_decisions");

            migrationBuilder.DropTable(
                name: "entity_membership_changes");

            migrationBuilder.DropIndex(
                name: "IX_entities_merged_into_entity_id",
                table: "entities");

            migrationBuilder.DropCheckConstraint(
                name: "ck_entities_merge",
                table: "entities");

            migrationBuilder.DropColumn(
                name: "merged_into_entity_id",
                table: "entities");

            migrationBuilder.DropColumn(
                name: "state",
                table: "entities");
        }
    }
}
#pragma warning restore CA1861
