using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// The Stage-4 plate analysis lifecycle (plan §5.1; ADR-013 implementation amendment 2026-10-13,
    /// items 11–15): <c>plate_analyses</c>, <c>plate_identity_activations</c>, <c>plate_attempt_failures</c>,
    /// <c>plate_track_outcomes</c>, <c>plate_observations</c>, <c>plate_readings</c> and
    /// <c>plate_track_texts</c>.
    /// </summary>
    /// <remarks>
    /// Additive only: no existing table or column changes and no historical row is written, so a Track
    /// without a plate analysis reports readiness, never an empty fact. <c>ArtifactType.PlatePredictions</c>
    /// needs no schema change (<c>artifact_type</c> is unconstrained text). Binary rollback stays safe: an
    /// older platform ignores the new tables. Search indexes on plate text are PR-4's, from measured plans.
    /// </remarks>
    public partial class AddPlateAnalysisLifecycle : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "plate_analyses",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    pipeline_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    pipeline_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    predictions_schema_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    normalisation_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    normalisation_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    summary_policy_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    summary_policy_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    summary_policy_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
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
                    plate_observations_read = table.Column<int>(type: "integer", nullable: false),
                    plate_observations_unreadable = table.Column<int>(type: "integer", nullable: false),
                    visibility_sequence = table.Column<long>(type: "bigint", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_analyses", x => x.id);
                    table.CheckConstraint("ck_plate_analyses_attempt_count", "attempt_count >= 0");
                    table.CheckConstraint("ck_plate_analyses_counts", "tracks_analysed >= 0 AND tracks_unavailable >= 0 AND plate_observations_read >= 0 AND plate_observations_unreadable >= 0");
                    table.CheckConstraint("ck_plate_analyses_fact_bearing", "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND visibility_sequence IS NOT NULL AND prediction_artifact_id IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_plate_analyses_failed", "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_plate_analyses_last_failed_token_hash", "last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32");
                    table.CheckConstraint("ck_plate_analyses_lease_token_hash", "lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32");
                    table.CheckConstraint("ck_plate_analyses_running_lease", "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
                    table.CheckConstraint("ck_plate_analyses_sha256", "identity_fingerprint ~ '^[0-9a-f]{64}$' AND normalisation_sha256 ~ '^[0-9a-f]{64}$' AND summary_policy_sha256 ~ '^[0-9a-f]{64}$' AND parameters_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
                    table.CheckConstraint("ck_plate_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
                    table.CheckConstraint("ck_plate_analyses_unpublished", "status IN ('Completed', 'Superseded') OR (visibility_sequence IS NULL AND prediction_artifact_id IS NULL)");
                    table.CheckConstraint("ck_plate_analyses_visibility_sequence", "visibility_sequence IS NULL OR visibility_sequence > 0");
                    table.ForeignKey(
                        name: "FK_plate_analyses_artifacts_prediction_artifact_id",
                        column: x => x.prediction_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_analyses_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "plate_identity_activations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    canonical_identity = table.Column<string>(type: "character varying(4096)", maxLength: 4096, nullable: false),
                    parameters_json = table.Column<string>(type: "character varying(65536)", maxLength: 65536, nullable: false),
                    summary_policy_json = table.Column<string>(type: "character varying(65536)", maxLength: 65536, nullable: false),
                    activated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_identity_activations", x => x.id);
                    table.CheckConstraint("ck_plate_identity_activations_fingerprint", "fingerprint ~ '^[0-9a-f]{64}$'");
                });

            migrationBuilder.CreateTable(
                name: "plate_attempt_failures",
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
                    table.PrimaryKey("PK_plate_attempt_failures", x => x.id);
                    table.CheckConstraint("ck_plate_attempt_failures_attempt", "attempt_number >= 1");
                    table.ForeignKey(
                        name: "FK_plate_attempt_failures_plate_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "plate_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "plate_track_outcomes",
                columns: table => new
                {
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    reason = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    plate_observation_count = table.Column<int>(type: "integer", nullable: false),
                    distinct_text_count = table.Column<int>(type: "integer", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_track_outcomes", x => new { x.analysis_id, x.track_id });
                    table.CheckConstraint("ck_plate_track_outcomes_counts", "plate_observation_count BETWEEN 0 AND 32 AND distinct_text_count BETWEEN 0 AND plate_observation_count");
                    table.CheckConstraint("ck_plate_track_outcomes_outcome", "outcome IN ('Analysed', 'Unavailable')");
                    table.CheckConstraint("ck_plate_track_outcomes_shape", "(outcome = 'Analysed' AND reason IS NULL) OR (outcome = 'Unavailable' AND reason IS NOT NULL AND reason IN ('evidence_decode_failed', 'evidence_integrity_failed', 'evidence_missing', 'no_accepted_evidence', 'plate_inference_failed') AND plate_observation_count = 0 AND distinct_text_count = 0)");
                    table.ForeignKey(
                        name: "FK_plate_track_outcomes_plate_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "plate_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_track_outcomes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "plate_observations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_observation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    plate_index = table.Column<int>(type: "integer", nullable: false),
                    box_x = table.Column<int>(type: "integer", nullable: false),
                    box_y = table.Column<int>(type: "integer", nullable: false),
                    box_width = table.Column<int>(type: "integer", nullable: false),
                    box_height = table.Column<int>(type: "integer", nullable: false),
                    crop_width = table.Column<int>(type: "integer", nullable: false),
                    crop_height = table.Column<int>(type: "integer", nullable: false),
                    detector_confidence = table.Column<double>(type: "double precision", nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_observations", x => x.id);
                    table.CheckConstraint("ck_plate_observations_box_inside_crop", "crop_width BETWEEN 1 AND 4096 AND crop_height BETWEEN 1 AND 4096 AND box_x >= 0 AND box_y >= 0 AND box_width >= 1 AND box_height >= 1 AND box_x + box_width <= crop_width AND box_y + box_height <= crop_height");
                    table.CheckConstraint("ck_plate_observations_detector_confidence", "detector_confidence >= 0 AND detector_confidence <= 1");
                    table.CheckConstraint("ck_plate_observations_outcome", "outcome IN ('Read', 'Unreadable')");
                    table.CheckConstraint("ck_plate_observations_plate_index", "plate_index BETWEEN 0 AND 7");
                    table.ForeignKey(
                        name: "FK_plate_observations_observations_source_observation_id",
                        column: x => x.source_observation_id,
                        principalTable: "observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_observations_plate_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "plate_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_observations_plate_track_outcomes_analysis_id_track_id",
                        columns: x => new { x.analysis_id, x.track_id },
                        principalTable: "plate_track_outcomes",
                        principalColumns: new[] { "analysis_id", "track_id" },
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_observations_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "plate_readings",
                columns: table => new
                {
                    plate_observation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    rank = table.Column<int>(type: "integer", nullable: false),
                    raw_text = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    raw_line_count = table.Column<int>(type: "integer", nullable: false),
                    confidence = table.Column<double>(type: "double precision", nullable: false),
                    normalised_text = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    normalisation_outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    normalisation_reason = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                    format_class = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_readings", x => new { x.plate_observation_id, x.rank });
                    table.CheckConstraint("ck_plate_readings_confidence", "confidence >= 0 AND confidence <= 1");
                    table.CheckConstraint("ck_plate_readings_normalisation", "(normalisation_outcome = 'Ok' AND normalised_text IS NOT NULL AND normalised_text ~ '^[A-Z0-9]+$' AND normalisation_reason IS NULL AND format_class IN ('in-standard', 'in-bh', 'other')) OR (normalisation_outcome = 'Rejected' AND normalised_text IS NULL AND format_class IS NULL AND normalisation_reason IN ('empty', 'non-alphanumeric'))");
                    table.CheckConstraint("ck_plate_readings_rank", "rank BETWEEN 0 AND 4");
                    table.CheckConstraint("ck_plate_readings_raw_text", "char_length(raw_text) BETWEEN 1 AND 32 AND raw_line_count IN (1, 2)");
                    table.ForeignKey(
                        name: "FK_plate_readings_plate_observations_plate_observation_id",
                        column: x => x.plate_observation_id,
                        principalTable: "plate_observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "plate_track_texts",
                columns: table => new
                {
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    normalised_text = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    support_count = table.Column<int>(type: "integer", nullable: false),
                    max_confidence = table.Column<double>(type: "double precision", nullable: false),
                    best_plate_observation_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_plate_track_texts", x => new { x.analysis_id, x.track_id, x.normalised_text });
                    table.CheckConstraint("ck_plate_track_texts_confidence", "max_confidence >= 0 AND max_confidence <= 1");
                    table.CheckConstraint("ck_plate_track_texts_support", "support_count BETWEEN 1 AND 32");
                    table.CheckConstraint("ck_plate_track_texts_text", "normalised_text ~ '^[A-Z0-9]+$'");
                    table.ForeignKey(
                        name: "FK_plate_track_texts_plate_observations_best_plate_observation~",
                        column: x => x.best_plate_observation_id,
                        principalTable: "plate_observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_plate_track_texts_plate_track_outcomes_analysis_id_track_id",
                        columns: x => new { x.analysis_id, x.track_id },
                        principalTable: "plate_track_outcomes",
                        principalColumns: new[] { "analysis_id", "track_id" },
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "ix_plate_analyses_claim",
                table: "plate_analyses",
                columns: new[] { "identity_fingerprint", "status", "queued_at_utc" },
                filter: "status IN ('Queued', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ux_plate_analyses_identity",
                table: "plate_analyses",
                columns: new[] { "processing_run_id", "identity_fingerprint" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ux_plate_analyses_prediction_artifact",
                table: "plate_analyses",
                column: "prediction_artifact_id",
                unique: true,
                filter: "prediction_artifact_id IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ux_plate_analyses_visibility_sequence",
                table: "plate_analyses",
                column: "visibility_sequence",
                unique: true,
                filter: "visibility_sequence IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ux_plate_attempt_failures_attempt",
                table: "plate_attempt_failures",
                columns: new[] { "analysis_id", "attempt_number" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_plate_identity_activations_activated",
                table: "plate_identity_activations",
                column: "activated_at_utc");

            migrationBuilder.CreateIndex(
                name: "ix_plate_observations_analysis_track",
                table: "plate_observations",
                columns: new[] { "analysis_id", "track_id" });

            migrationBuilder.CreateIndex(
                name: "ix_plate_observations_source_observation",
                table: "plate_observations",
                column: "source_observation_id");

            migrationBuilder.CreateIndex(
                name: "ix_plate_observations_track",
                table: "plate_observations",
                column: "track_id");

            migrationBuilder.CreateIndex(
                name: "ux_plate_observations_analysis_source_plate",
                table: "plate_observations",
                columns: new[] { "analysis_id", "source_observation_id", "plate_index" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_plate_track_outcomes_track",
                table: "plate_track_outcomes",
                column: "track_id");

            migrationBuilder.CreateIndex(
                name: "ix_plate_track_texts_best_plate_observation",
                table: "plate_track_texts",
                column: "best_plate_observation_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "plate_attempt_failures");

            migrationBuilder.DropTable(
                name: "plate_identity_activations");

            migrationBuilder.DropTable(
                name: "plate_readings");

            migrationBuilder.DropTable(
                name: "plate_track_texts");

            migrationBuilder.DropTable(
                name: "plate_observations");

            migrationBuilder.DropTable(
                name: "plate_track_outcomes");

            migrationBuilder.DropTable(
                name: "plate_analyses");
        }
    }
}
#pragma warning restore CA1861
