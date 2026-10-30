using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddEntityCandidates : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "entity_candidate_derivations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    embedding_analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    catalogue_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    catalogue_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    outcome = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    candidate_count = table.Column<int>(type: "integer", nullable: false),
                    derived_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_entity_candidate_derivations", x => x.id);
                    table.CheckConstraint("ck_entity_candidate_derivations_count", "candidate_count >= 0");
                    table.CheckConstraint("ck_entity_candidate_derivations_outcome", "outcome IN ('derived', 'not_visible')");
                    table.ForeignKey(
                        name: "FK_entity_candidate_derivations_embedding_analyses_embedding_a~",
                        column: x => x.embedding_analysis_id,
                        principalTable: "embedding_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "entity_candidates",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    derivation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    catalogue_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    lower_track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    higher_track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    object_class = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    appearance_score = table.Column<double>(type: "double precision", nullable: false),
                    same_camera = table.Column<bool>(type: "boolean", nullable: false),
                    gap_ms = table.Column<long>(type: "bigint", nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    decided_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    decided_by_operator_id = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    decided_by_display_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    decided_by_identity_source = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    decision_note = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    decision_audit_entry_id = table.Column<Guid>(type: "uuid", nullable: true),
                    entity_id = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_entity_candidates", x => x.id);
                    table.CheckConstraint("ck_entity_candidates_class", "object_class IN ('Person', 'Vehicle')");
                    table.CheckConstraint("ck_entity_candidates_decision", "(status = 'Open' AND decided_at_utc IS NULL AND entity_id IS NULL AND decision_audit_entry_id IS NULL) OR (status = 'Dismissed' AND decided_at_utc IS NOT NULL AND entity_id IS NULL AND decision_audit_entry_id IS NOT NULL) OR (status = 'Confirmed' AND decided_at_utc IS NOT NULL AND entity_id IS NOT NULL AND decision_audit_entry_id IS NOT NULL)");
                    table.CheckConstraint("ck_entity_candidates_pair_order", "lower_track_id < higher_track_id");
                    table.CheckConstraint("ck_entity_candidates_score", "appearance_score >= -1 AND appearance_score <= 1");
                    table.ForeignKey(
                        name: "FK_entity_candidates_entities_entity_id",
                        column: x => x.entity_id,
                        principalTable: "entities",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_entity_candidates_entity_candidate_derivations_derivation_id",
                        column: x => x.derivation_id,
                        principalTable: "entity_candidate_derivations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_entity_candidates_tracks_higher_track_id",
                        column: x => x.higher_track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_entity_candidates_tracks_lower_track_id",
                        column: x => x.lower_track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "ux_entity_candidate_derivations_analysis_catalogue",
                table: "entity_candidate_derivations",
                columns: new[] { "embedding_analysis_id", "catalogue_version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidates_derivation_id",
                table: "entity_candidates",
                column: "derivation_id");

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidates_entity_id",
                table: "entity_candidates",
                column: "entity_id");

            migrationBuilder.CreateIndex(
                name: "ix_entity_candidates_higher_track",
                table: "entity_candidates",
                column: "higher_track_id");

            migrationBuilder.CreateIndex(
                name: "IX_entity_candidates_lower_track_id",
                table: "entity_candidates",
                column: "lower_track_id");

            migrationBuilder.CreateIndex(
                name: "ix_entity_candidates_status_score",
                table: "entity_candidates",
                columns: new[] { "status", "appearance_score" });

            migrationBuilder.CreateIndex(
                name: "ux_entity_candidates_pair",
                table: "entity_candidates",
                columns: new[] { "catalogue_version", "identity_fingerprint", "lower_track_id", "higher_track_id" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "entity_candidates");

            migrationBuilder.DropTable(
                name: "entity_candidate_derivations");
        }
    }
}
