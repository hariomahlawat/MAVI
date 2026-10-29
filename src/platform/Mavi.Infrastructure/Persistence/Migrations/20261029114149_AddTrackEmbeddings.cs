using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Pgvector;

#nullable disable

#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// PoC Stage 5 embeddings (ADR-021 §3–§4): <c>embedding_analyses</c>, <c>embedding_identity_activations</c>,
    /// <c>track_embeddings</c> (pgvector, dimension-free; searched exactly, no ANN index by decision) and
    /// <c>appearance_query_embeddings</c>. Purely additive: no existing table, row or constraint changes.
    /// </summary>
    /// <inheritdoc />
    public partial class AddTrackEmbeddings : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "appearance_query_embeddings",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    identity_fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    text = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: false),
                    text_sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    lease_owner = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    lease_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                    lease_expires_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    requested_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    embedding = table.Column<Vector>(type: "vector", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_appearance_query_embeddings", x => x.id);
                    table.CheckConstraint("ck_appearance_query_embeddings_completed", "(status = 'Completed') = (embedding IS NOT NULL)");
                    table.CheckConstraint("ck_appearance_query_embeddings_status", "status IN ('Pending', 'Running', 'Completed', 'Failed')");
                    table.CheckConstraint("ck_appearance_query_embeddings_text", "char_length(text) BETWEEN 1 AND 200");
                });

            migrationBuilder.CreateTable(
                name: "embedding_analyses",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
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
                    tracks_embedded = table.Column<int>(type: "integer", nullable: false),
                    tracks_unavailable = table.Column<int>(type: "integer", nullable: false),
                    visibility_sequence = table.Column<long>(type: "bigint", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_embedding_analyses", x => x.id);
                    table.CheckConstraint("ck_embedding_analyses_attempt_count", "attempt_count >= 0");
                    table.CheckConstraint("ck_embedding_analyses_counts", "tracks_embedded >= 0 AND tracks_unavailable >= 0");
                    table.CheckConstraint("ck_embedding_analyses_dimension", "dimension BETWEEN 1 AND 4096");
                    table.CheckConstraint("ck_embedding_analyses_fact_bearing", "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND visibility_sequence IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_embedding_analyses_failed", "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
                    table.CheckConstraint("ck_embedding_analyses_running_lease", "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
                    table.CheckConstraint("ck_embedding_analyses_sha256", "identity_fingerprint ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND pipeline_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
                    table.CheckConstraint("ck_embedding_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
                    table.CheckConstraint("ck_embedding_analyses_token_hashes", "(lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32) AND (last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32)");
                    table.CheckConstraint("ck_embedding_analyses_unpublished", "status IN ('Completed', 'Superseded') OR visibility_sequence IS NULL");
                    table.ForeignKey(
                        name: "FK_embedding_analyses_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "embedding_identity_activations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    fingerprint = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    canonical_identity = table.Column<string>(type: "character varying(2048)", maxLength: 2048, nullable: false),
                    activated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_embedding_identity_activations", x => x.id);
                    table.CheckConstraint("ck_embedding_identity_activations_fingerprint", "fingerprint ~ '^[0-9a-f]{64}$'");
                });

            migrationBuilder.CreateTable(
                name: "track_embeddings",
                columns: table => new
                {
                    analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    outcome = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    unavailable_reason = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                    embedding = table.Column<Vector>(type: "vector", nullable: true),
                    source_observation_ids = table.Column<Guid[]>(type: "uuid[]", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_track_embeddings", x => new { x.analysis_id, x.track_id });
                    table.CheckConstraint("ck_track_embeddings_outcome", "(outcome = 'Embedded' AND embedding IS NOT NULL AND unavailable_reason IS NULL AND cardinality(source_observation_ids) >= 1) OR (outcome = 'Unavailable' AND embedding IS NULL AND unavailable_reason IN ('no_evidence', 'evidence_too_small', 'evidence_unavailable') AND cardinality(source_observation_ids) = 0)");
                    table.ForeignKey(
                        name: "FK_track_embeddings_embedding_analyses_analysis_id",
                        column: x => x.analysis_id,
                        principalTable: "embedding_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_track_embeddings_tracks_track_id",
                        column: x => x.track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "ix_appearance_query_embeddings_claim",
                table: "appearance_query_embeddings",
                columns: new[] { "identity_fingerprint", "status", "requested_at_utc" },
                filter: "status IN ('Pending', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ux_appearance_query_embeddings_text",
                table: "appearance_query_embeddings",
                columns: new[] { "identity_fingerprint", "text_sha256" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_embedding_analyses_claim",
                table: "embedding_analyses",
                columns: new[] { "identity_fingerprint", "status", "queued_at_utc" },
                filter: "status IN ('Queued', 'Running')");

            migrationBuilder.CreateIndex(
                name: "ux_embedding_analyses_identity",
                table: "embedding_analyses",
                columns: new[] { "processing_run_id", "identity_fingerprint" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ux_embedding_analyses_visibility_sequence",
                table: "embedding_analyses",
                column: "visibility_sequence",
                unique: true,
                filter: "visibility_sequence IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "ix_embedding_identity_activations_activated",
                table: "embedding_identity_activations",
                column: "activated_at_utc");

            migrationBuilder.CreateIndex(
                name: "ix_track_embeddings_track",
                table: "track_embeddings",
                column: "track_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "appearance_query_embeddings");

            migrationBuilder.DropTable(
                name: "embedding_identity_activations");

            migrationBuilder.DropTable(
                name: "track_embeddings");

            migrationBuilder.DropTable(
                name: "embedding_analyses");
        }
    }
}
