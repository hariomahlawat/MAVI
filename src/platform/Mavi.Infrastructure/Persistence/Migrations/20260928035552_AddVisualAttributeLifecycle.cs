using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddVisualAttributeLifecycle : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // The Stage-1 placeholder table is replaced, not altered (ADR-013 §14; S2b plan §7).
            // No code path ever wrote it; if a row exists anyway it is somebody's data, so the
            // migration refuses rather than discarding it.
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM visual_attributes) THEN
                        RAISE EXCEPTION 'visual_attributes holds placeholder rows; refusing to replace the table (S2b)';
                    END IF;
                END
                $$;
                """);

            migrationBuilder.DropTable(
                name: "visual_attributes");

            migrationBuilder.CreateTable(
                name: "visual_attribute_analyses",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    attribute_schema_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    attribute_schema_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    attribute_schema_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    pipeline_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    pipeline_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    aggregation_policy_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    aggregation_policy_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    aggregation_policy_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    capabilities_canonical = table.Column<string>(type: "character varying(1024)", maxLength: 1024, nullable: false),
                    parameters_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    lease_owner = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    lease_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                    lease_expires_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    last_heartbeat_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    queued_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    first_claimed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    failure_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true),
                    last_failed_worker_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    last_failed_attempt = table.Column<int>(type: "integer", nullable: true),
                    last_failed_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                    last_failed_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    last_failed_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true),
                    last_failed_outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                    completion_digest = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: true),
                    prediction_artifact_id = table.Column<Guid>(type: "uuid", nullable: true),
                    provenance_json = table.Column<string>(type: "jsonb", nullable: true),
                    tracks_analysed = table.Column<int>(type: "integer", nullable: false),
                    tracks_unavailable = table.Column<int>(type: "integer", nullable: false),
                    attributes_observed = table.Column<int>(type: "integer", nullable: false),
                    attributes_unknown = table.Column<int>(type: "integer", nullable: false),
                    visibility_sequence = table.Column<long>(type: "bigint", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attribute_analyses", x => x.id);
                    table.CheckConstraint("ck_visual_attribute_analyses_attempt_count", "attempt_count >= 0");
                    table.CheckConstraint("ck_visual_attribute_analyses_counts", "tracks_analysed >= 0 AND tracks_unavailable >= 0 AND attributes_observed >= 0 AND attributes_unknown >= 0");
                    table.CheckConstraint("ck_visual_attribute_analyses_fact_bearing", "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND visibility_sequence IS NOT NULL AND prediction_artifact_id IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_visual_attribute_analyses_failed", "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_visual_attribute_analyses_last_failed_token_hash", "last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32");
                    table.CheckConstraint("ck_visual_attribute_analyses_lease_token_hash", "lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32");
                    table.CheckConstraint("ck_visual_attribute_analyses_running_lease", "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
                    table.CheckConstraint("ck_visual_attribute_analyses_sha256", "identity_fingerprint ~ '^[0-9a-f]{64}$' AND attribute_schema_sha256 ~ '^[0-9a-f]{64}$' AND aggregation_policy_sha256 ~ '^[0-9a-f]{64}$' AND parameters_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
                    table.CheckConstraint("ck_visual_attribute_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
                    table.CheckConstraint("ck_visual_attribute_analyses_unpublished", "status IN ('Completed', 'Superseded') OR (visibility_sequence IS NULL AND prediction_artifact_id IS NULL)");
                    table.CheckConstraint("ck_visual_attribute_analyses_visibility_sequence", "visibility_sequence IS NULL OR visibility_sequence > 0");
                    table.ForeignKey(
                        name: "FK_visual_attribute_analyses_artifacts_prediction_artifact_id",
                        column: x => x.prediction_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_visual_attribute_analyses_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "visual_attribute_identity_activations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    canonical_identity = table.Column<string>(type: "character varying(4096)", maxLength: 4096, nullable: false),
                    attribute_schema_json = table.Column<string>(type: "character varying(65536)", maxLength: 65536, nullable: false),
                    activated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attribute_identity_activations", x => x.id);
                    table.CheckConstraint("ck_visual_attribute_identity_activations_fingerprint", "fingerprint ~ '^[0-9a-f]{64}$'");
                });

            migrationBuilder.CreateTable(
                name: "visual_attribute_attempt_failures",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    attempt_number = table.Column<int>(type: "integer", nullable: false),
                    failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    retryable = table.Column<bool>(type: "boolean", nullable: false),
                    failure_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true),
                    failed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attribute_attempt_failures", x => x.id);
                    table.CheckConstraint("ck_visual_attribute_attempt_failures_attempt", "attempt_number >= 1");
                    table.ForeignKey(
                        name: "FK_visual_attribute_attempt_failures_visual_attribute_analyses~",
                        column: x => x.analysis_id,
                        principalTable: "visual_attribute_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "visual_attribute_track_outcomes",
                columns: table => new
                {
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    reason = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attribute_track_outcomes", x => new { x.analysis_id, x.track_id });
                    table.CheckConstraint("ck_visual_attribute_track_outcomes_outcome", "outcome IN ('Analysed', 'Unavailable')");
                    table.CheckConstraint("ck_visual_attribute_track_outcomes_shape", "(outcome = 'Analysed' AND reason IS NULL) OR (outcome = 'Unavailable' AND reason IS NOT NULL AND reason IN ('evidence_decode_failed', 'evidence_integrity_failed', 'evidence_missing', 'no_accepted_evidence'))");
                    table.ForeignKey(
                        name: "FK_visual_attribute_track_outcomes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_visual_attribute_track_outcomes_visual_attribute_analyses_a~",
                        column: x => x.analysis_id,
                        principalTable: "visual_attribute_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "visual_attributes",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    attribute_type = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    value = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    confidence = table.Column<double>(type: "double precision", nullable: true),
                    supporting_observation_id = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attributes", x => x.id);
                    table.CheckConstraint("ck_visual_attributes_outcome", "outcome IN ('Observed', 'Unknown')");
                    table.CheckConstraint("ck_visual_attributes_shape", "(outcome = 'Observed' AND value IS NOT NULL AND confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1 AND supporting_observation_id IS NOT NULL) OR (outcome = 'Unknown' AND value IS NULL AND confidence IS NULL AND supporting_observation_id IS NULL)");
                    table.ForeignKey(
                        name: "FK_visual_attributes_observations_supporting_observation_id",
                        column: x => x.supporting_observation_id,
                        principalTable: "observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_visual_attributes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_visual_attributes_visual_attribute_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "visual_attribute_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_visual_attributes_visual_attribute_track_outcomes_analysis_~",
                        columns: x => new { x.analysis_id, x.track_id },
                        principalTable: "visual_attribute_track_outcomes",
                        principalColumns: new[] { "analysis_id", "track_id" },
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "ux_visual_attributes_analysis_track_type",
                table: "visual_attributes",
                columns: new[] { "analysis_id", "track_id", "attribute_type" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_visual_attributes_track",
                table: "visual_attributes",
                column: "track_id");

            migrationBuilder.CreateIndex(
                name: "ix_visual_attributes_supporting_observation",
                table: "visual_attributes",
                column: "supporting_observation_id");

            migrationBuilder.CreateIndex(
                name: "ix_visual_attribute_analyses_claim",
                table: "visual_attribute_analyses",
                columns: new[] { "identity_fingerprint", "status", "queued_at_utc" },
                filter: "status IN ('Queued', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ux_visual_attribute_analyses_identity",
                table: "visual_attribute_analyses",
                columns: new[] { "processing_run_id", "identity_fingerprint" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ux_visual_attribute_analyses_prediction_artifact",
                table: "visual_attribute_analyses",
                column: "prediction_artifact_id",
                unique: true,
                filter: "prediction_artifact_id IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ux_visual_attribute_analyses_visibility_sequence",
                table: "visual_attribute_analyses",
                column: "visibility_sequence",
                unique: true,
                filter: "visibility_sequence IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ux_visual_attribute_attempt_failures_attempt",
                table: "visual_attribute_attempt_failures",
                columns: new[] { "analysis_id", "attempt_number" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_visual_attribute_identity_activations_activated",
                table: "visual_attribute_identity_activations",
                column: "activated_at_utc");

            migrationBuilder.CreateIndex(
                name: "ix_visual_attribute_track_outcomes_track",
                table: "visual_attribute_track_outcomes",
                column: "track_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "visual_attributes");

            migrationBuilder.DropTable(
                name: "visual_attribute_attempt_failures");

            migrationBuilder.DropTable(
                name: "visual_attribute_identity_activations");

            migrationBuilder.DropTable(
                name: "visual_attribute_track_outcomes");

            migrationBuilder.DropTable(
                name: "visual_attribute_analyses");

            // The Stage-1 placeholder shape, exactly as InitialVisualMemory created it.
            migrationBuilder.CreateTable(
                name: "visual_attributes",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    observation_id = table.Column<Guid>(type: "uuid", nullable: true),
                    attribute_type = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    value = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    confidence = table.Column<double>(type: "double precision", nullable: false),
                    model_name = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    model_version = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_visual_attributes", x => x.id);
                    table.CheckConstraint("ck_visual_attributes_confidence", "confidence >= 0 AND confidence <= 1");
                    table.ForeignKey(
                        name: "FK_visual_attributes_observations_observation_id",
                        column: x => x.observation_id,
                        principalTable: "observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_visual_attributes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_visual_attributes_observation_id",
                table: "visual_attributes",
                column: "observation_id");

            migrationBuilder.CreateIndex(
                name: "IX_visual_attributes_track_id",
                table: "visual_attributes",
                column: "track_id");
        }
    }
}
#pragma warning restore CA1861
