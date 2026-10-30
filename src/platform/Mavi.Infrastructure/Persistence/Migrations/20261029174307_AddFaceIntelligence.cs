using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Pgvector;

#nullable disable

#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// PoC Stage 5A faces (ADR-022 §3–§5): the camera opt-in switch <c>cameras.face_analysis_enabled</c> (default
    /// off), <c>face_analyses</c>, <c>face_track_outcomes</c>, <c>face_observations</c>, <c>face_embeddings</c>
    /// (pgvector, dimension-free, exact search), the transient <c>face_queries</c> and <c>face_query_embeddings</c>,
    /// and the gallery <c>enrolled_persons</c> and <c>enrolled_person_faces</c>. Additive: one new column with a
    /// default, no existing row or constraint changes. No table links a Track or a face to an enrolled person.
    /// </summary>
    /// <inheritdoc />
    public partial class AddFaceIntelligence : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "face_analysis_enabled",
                table: "cameras",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.CreateTable(
                name: "enrolled_persons",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    label = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    note = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    updated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_enrolled_persons", x => x.id);
                    table.CheckConstraint("ck_enrolled_persons_label", "char_length(label) BETWEEN 1 AND 100");
                    table.CheckConstraint("ck_enrolled_persons_note", "note IS NULL OR char_length(note) <= 500");
                });

            migrationBuilder.CreateTable(
                name: "face_analyses",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    camera_id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    model_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    model_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    manifest_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    dimension = table.Column<int>(type: "integer", nullable: false),
                    pipeline_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    pipeline_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    pipeline_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
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
                    failure_details = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    last_failed_worker_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    last_failed_attempt = table.Column<int>(type: "integer", nullable: true),
                    last_failed_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                    last_failed_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    last_failed_details = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    last_failed_outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                    completion_digest = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: true),
                    provenance_json = table.Column<string>(type: "jsonb", nullable: true),
                    tracks_observed = table.Column<int>(type: "integer", nullable: false),
                    tracks_unknown = table.Column<int>(type: "integer", nullable: false),
                    visibility_sequence = table.Column<long>(type: "bigint", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_analyses", x => x.id);
                    table.CheckConstraint("ck_face_analyses_attempt_count", "attempt_count >= 0");
                    table.CheckConstraint("ck_face_analyses_counts", "tracks_observed >= 0 AND tracks_unknown >= 0");
                    table.CheckConstraint("ck_face_analyses_dimension", "dimension BETWEEN 1 AND 4096");
                    table.CheckConstraint("ck_face_analyses_fact_bearing", "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND visibility_sequence IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_face_analyses_failed", "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_face_analyses_running_lease", "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
                    table.CheckConstraint("ck_face_analyses_sha256", "identity_fingerprint ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND pipeline_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
                    table.CheckConstraint("ck_face_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
                    table.CheckConstraint("ck_face_analyses_token_hashes", "(lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32) AND (last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32)");
                    table.CheckConstraint("ck_face_analyses_unpublished", "status IN ('Completed', 'Superseded') OR visibility_sequence IS NULL");
                    table.ForeignKey(
                        name: "FK_face_analyses_cameras_camera_id",
                        column: x => x.camera_id,
                        principalTable: "cameras",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_face_analyses_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "face_queries",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    image = table.Column<byte[]>(type: "bytea", nullable: true),
                    image_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    mime_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    size_bytes = table.Column<long>(type: "bigint", nullable: false),
                    status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    lease_owner = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    lease_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                    lease_expires_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    purge_after_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    faces = table.Column<string>(type: "jsonb", nullable: true),
                    completion_digest = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_queries", x => x.id);
                    table.CheckConstraint("ck_face_queries_completed", "(status = 'Completed') = (faces IS NOT NULL)");
                    table.CheckConstraint("ck_face_queries_finished_image_erased", "status IN ('Pending', 'Running') OR image IS NULL");
                    table.CheckConstraint("ck_face_queries_mime", "mime_type IN ('image/jpeg', 'image/png')");
                    table.CheckConstraint("ck_face_queries_size", "size_bytes BETWEEN 1 AND 2097152");
                    table.CheckConstraint("ck_face_queries_status", "status IN ('Pending', 'Running', 'Completed', 'Failed')");
                });

            migrationBuilder.CreateTable(
                name: "enrolled_person_faces",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    enrolled_person_id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    embedding = table.Column<Vector>(type: "vector", nullable: false),
                    source_kind = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    source_face_observation_id = table.Column<Guid>(type: "uuid", nullable: true),
                    thumbnail = table.Column<byte[]>(type: "bytea", nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_enrolled_person_faces", x => x.id);
                    table.CheckConstraint("ck_enrolled_person_faces_fingerprint", "identity_fingerprint ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("ck_enrolled_person_faces_source", "(source_kind = 'Evidence' AND source_face_observation_id IS NOT NULL AND thumbnail IS NULL) OR (source_kind = 'Query' AND source_face_observation_id IS NULL)");
                    table.ForeignKey(
                        name: "FK_enrolled_person_faces_enrolled_persons_enrolled_person_id",
                        column: x => x.enrolled_person_id,
                        principalTable: "enrolled_persons",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "face_observations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    observation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    box_x = table.Column<float>(type: "real", nullable: false),
                    box_y = table.Column<float>(type: "real", nullable: false),
                    box_w = table.Column<float>(type: "real", nullable: false),
                    box_h = table.Column<float>(type: "real", nullable: false),
                    landmarks = table.Column<float[]>(type: "real[]", nullable: false),
                    score = table.Column<float>(type: "real", nullable: false),
                    min_side = table.Column<float>(type: "real", nullable: false),
                    usable = table.Column<bool>(type: "boolean", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_observations", x => x.id);
                    table.CheckConstraint("ck_face_observations_box", "box_x >= 0 AND box_y >= 0 AND box_w > 0 AND box_h > 0");
                    table.CheckConstraint("ck_face_observations_landmarks", "cardinality(landmarks) = 10");
                    table.CheckConstraint("ck_face_observations_score", "score > 0 AND score <= 1");
                    table.ForeignKey(
                        name: "FK_face_observations_face_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "face_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_face_observations_observations_observation_id",
                        column: x => x.observation_id,
                        principalTable: "observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_face_observations_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "face_track_outcomes",
                columns: table => new
                {
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    reason = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_track_outcomes", x => new { x.analysis_id, x.track_id });
                    table.CheckConstraint("ck_face_track_outcomes_outcome", "(outcome = 'Observed' AND reason IS NULL) OR (outcome = 'Unknown' AND reason IN ('no_evidence', 'evidence_unavailable', 'no_face_detected', 'face_too_small'))");
                    table.ForeignKey(
                        name: "FK_face_track_outcomes_face_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "face_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_face_track_outcomes_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "face_query_embeddings",
                columns: table => new
                {
                    query_id = table.Column<Guid>(type: "uuid", nullable: false),
                    face_index = table.Column<int>(type: "integer", nullable: false),
                    embedding = table.Column<Vector>(type: "vector", nullable: false),
                    thumbnail = table.Column<byte[]>(type: "bytea", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_query_embeddings", x => new { x.query_id, x.face_index });
                    table.ForeignKey(
                        name: "FK_face_query_embeddings_face_queries_query_id",
                        column: x => x.query_id,
                        principalTable: "face_queries",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "face_embeddings",
                columns: table => new
                {
                    face_observation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    embedding = table.Column<Vector>(type: "vector", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_face_embeddings", x => x.face_observation_id);
                    table.ForeignKey(
                        name: "FK_face_embeddings_face_observations_face_observation_id",
                        column: x => x.face_observation_id,
                        principalTable: "face_observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "ix_enrolled_person_faces_person",
                table: "enrolled_person_faces",
                column: "enrolled_person_id");

            migrationBuilder.CreateIndex(
                name: "ix_face_analyses_camera",
                table: "face_analyses",
                column: "camera_id");

            migrationBuilder.CreateIndex(
                name: "ix_face_analyses_claim",
                table: "face_analyses",
                columns: new[] { "identity_fingerprint", "status", "queued_at_utc" },
                filter: "status IN ('Queued', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ux_face_analyses_identity",
                table: "face_analyses",
                columns: new[] { "processing_run_id", "identity_fingerprint" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ux_face_analyses_visibility_sequence",
                table: "face_analyses",
                column: "visibility_sequence",
                unique: true,
                filter: "visibility_sequence IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ix_face_observations_analysis_track",
                table: "face_observations",
                columns: new[] { "analysis_id", "track_id" });

            migrationBuilder.CreateIndex(
                name: "ix_face_observations_observation",
                table: "face_observations",
                column: "observation_id");

            migrationBuilder.CreateIndex(
                name: "ix_face_observations_track",
                table: "face_observations",
                column: "track_id");

            migrationBuilder.CreateIndex(
                name: "ix_face_queries_claim",
                table: "face_queries",
                columns: new[] { "identity_fingerprint", "status", "created_at_utc" },
                filter: "status IN ('Pending', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ix_face_queries_purge",
                table: "face_queries",
                column: "purge_after_utc");

            migrationBuilder.CreateIndex(
                name: "ix_face_track_outcomes_track",
                table: "face_track_outcomes",
                column: "track_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "enrolled_person_faces");

            migrationBuilder.DropTable(
                name: "face_embeddings");

            migrationBuilder.DropTable(
                name: "face_query_embeddings");

            migrationBuilder.DropTable(
                name: "face_track_outcomes");

            migrationBuilder.DropTable(
                name: "enrolled_persons");

            migrationBuilder.DropTable(
                name: "face_observations");

            migrationBuilder.DropTable(
                name: "face_queries");

            migrationBuilder.DropTable(
                name: "face_analyses");

            migrationBuilder.DropColumn(
                name: "face_analysis_enabled",
                table: "cameras");
        }
    }
}
