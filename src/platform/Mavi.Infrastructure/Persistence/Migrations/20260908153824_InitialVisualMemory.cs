using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class InitialVisualMemory : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterDatabase()
                .Annotation("Npgsql:PostgresExtension:vector", ",,");

            migrationBuilder.CreateTable(
                name: "artifacts",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    artifact_type = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    storage_key = table.Column<string>(type: "character varying(512)", maxLength: 512, nullable: false),
                    mime_type = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    size_bytes = table.Column<long>(type: "bigint", nullable: false),
                    sha256 = table.Column<string>(type: "character(64)", fixedLength: true, maxLength: 64, nullable: false),
                    metadata_json = table.Column<string>(type: "jsonb", nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_artifacts", x => x.id);
                    table.CheckConstraint("ck_artifacts_size", "size_bytes >= 0");
                });

            migrationBuilder.CreateTable(
                name: "cameras",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    code = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    name = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    description = table.Column<string>(type: "character varying(512)", maxLength: 512, nullable: true),
                    location_name = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    time_zone_id = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    is_active = table.Column<bool>(type: "boolean", nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    updated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_cameras", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "entities",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    entity_type = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    display_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    identity_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    review_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    representative_artifact_id = table.Column<Guid>(type: "uuid", nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    updated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_entities", x => x.id);
                    table.ForeignKey(
                        name: "FK_entities_artifacts_representative_artifact_id",
                        column: x => x.representative_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                });

            migrationBuilder.CreateTable(
                name: "video_assets",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    camera_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_artifact_id = table.Column<Guid>(type: "uuid", nullable: false),
                    original_file_name = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    source_type = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    source_reference = table.Column<string>(type: "character varying(512)", maxLength: 512, nullable: true),
                    recording_start_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    recording_end_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    duration_ms = table.Column<long>(type: "bigint", nullable: false),
                    frame_rate_numerator = table.Column<int>(type: "integer", nullable: false),
                    frame_rate_denominator = table.Column<int>(type: "integer", nullable: false),
                    width = table.Column<int>(type: "integer", nullable: false),
                    height = table.Column<int>(type: "integer", nullable: false),
                    codec = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    timestamp_source = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    timestamp_confidence = table.Column<double>(type: "double precision", nullable: false),
                    processing_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    imported_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_video_assets", x => x.id);
                    table.CheckConstraint("ck_video_assets_dimensions", "width > 0 AND height > 0");
                    table.CheckConstraint("ck_video_assets_duration", "duration_ms > 0");
                    table.CheckConstraint("ck_video_assets_frame_rate", "frame_rate_numerator > 0 AND frame_rate_denominator > 0");
                    table.CheckConstraint("ck_video_assets_timestamp_confidence", "timestamp_confidence >= 0 AND timestamp_confidence <= 1");
                    table.ForeignKey(
                        name: "FK_video_assets_artifacts_source_artifact_id",
                        column: x => x.source_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_video_assets_cameras_camera_id",
                        column: x => x.camera_id,
                        principalTable: "cameras",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "processing_runs",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    video_asset_id = table.Column<Guid>(type: "uuid", nullable: false),
                    status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    pipeline_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    detector_name = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    detector_version = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    tracker_name = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    tracker_version = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    configuration_json = table.Column<string>(type: "jsonb", nullable: false),
                    worker_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    queued_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    started_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    frames_processed = table.Column<long>(type: "bigint", nullable: false),
                    tracks_created = table.Column<int>(type: "integer", nullable: false),
                    processing_duration_ms = table.Column<long>(type: "bigint", nullable: true),
                    error_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    error_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_processing_runs", x => x.id);
                    table.CheckConstraint("ck_processing_runs_frames", "frames_processed >= 0");
                    table.CheckConstraint("ck_processing_runs_tracks", "tracks_created >= 0");
                    table.ForeignKey(
                        name: "FK_processing_runs_video_assets_video_asset_id",
                        column: x => x.video_asset_id,
                        principalTable: "video_assets",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "vision_jobs",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    pipeline = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    available_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    lease_owner = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    lease_expires_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    progress_percent = table.Column<double>(type: "double precision", nullable: false),
                    last_heartbeat_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    failure_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_vision_jobs", x => x.id);
                    table.CheckConstraint("ck_vision_jobs_attempts", "attempt_count >= 0 AND attempt_count <= 3");
                    table.CheckConstraint("ck_vision_jobs_progress", "progress_percent >= 0 AND progress_percent <= 100");
                    table.ForeignKey(
                        name: "FK_vision_jobs_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "observations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    track_id = table.Column<Guid>(type: "uuid", nullable: false),
                    observation_type = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    source_frame_number = table.Column<long>(type: "bigint", nullable: false),
                    video_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                    timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    bounding_box_x = table.Column<float>(type: "real", nullable: false),
                    bounding_box_y = table.Column<float>(type: "real", nullable: false),
                    bounding_box_width = table.Column<float>(type: "real", nullable: false),
                    bounding_box_height = table.Column<float>(type: "real", nullable: false),
                    confidence = table.Column<double>(type: "double precision", nullable: false),
                    quality_score = table.Column<double>(type: "double precision", nullable: false),
                    thumbnail_artifact_id = table.Column<Guid>(type: "uuid", nullable: true),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_observations", x => x.id);
                    table.CheckConstraint("ck_observations_box", "bounding_box_x >= 0 AND bounding_box_y >= 0 AND bounding_box_width >= 0 AND bounding_box_height >= 0 AND bounding_box_x + bounding_box_width <= 1 AND bounding_box_y + bounding_box_height <= 1");
                    table.CheckConstraint("ck_observations_scores", "confidence >= 0 AND confidence <= 1 AND quality_score >= 0 AND quality_score <= 1");
                    table.ForeignKey(
                        name: "FK_observations_artifacts_thumbnail_artifact_id",
                        column: x => x.thumbnail_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                });

            migrationBuilder.CreateTable(
                name: "tracks",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    video_asset_id = table.Column<Guid>(type: "uuid", nullable: false),
                    entity_id = table.Column<Guid>(type: "uuid", nullable: true),
                    local_track_number = table.Column<int>(type: "integer", nullable: false),
                    object_class = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    start_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                    end_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                    start_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    end_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    duration_ms = table.Column<long>(type: "bigint", nullable: false),
                    detection_count = table.Column<int>(type: "integer", nullable: false),
                    mean_confidence = table.Column<double>(type: "double precision", nullable: false),
                    max_confidence = table.Column<double>(type: "double precision", nullable: false),
                    representative_observation_id = table.Column<Guid>(type: "uuid", nullable: true),
                    trajectory_artifact_id = table.Column<Guid>(type: "uuid", nullable: true),
                    review_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_tracks", x => x.id);
                    table.CheckConstraint("ck_tracks_confidence", "mean_confidence >= 0 AND mean_confidence <= 1 AND max_confidence >= 0 AND max_confidence <= 1");
                    table.CheckConstraint("ck_tracks_detections", "detection_count > 0");
                    table.CheckConstraint("ck_tracks_duration", "duration_ms = end_offset_ms - start_offset_ms");
                    table.CheckConstraint("ck_tracks_offsets", "start_offset_ms >= 0 AND end_offset_ms >= start_offset_ms");
                    table.ForeignKey(
                        name: "FK_tracks_artifacts_trajectory_artifact_id",
                        column: x => x.trajectory_artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_tracks_entities_entity_id",
                        column: x => x.entity_id,
                        principalTable: "entities",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_tracks_observations_representative_observation_id",
                        column: x => x.representative_observation_id,
                        principalTable: "observations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_tracks_processing_runs_processing_run_id",
                        column: x => x.processing_run_id,
                        principalTable: "processing_runs",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_tracks_video_assets_video_asset_id",
                        column: x => x.video_asset_id,
                        principalTable: "video_assets",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

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
                name: "IX_artifacts_storage_key",
                table: "artifacts",
                column: "storage_key",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_cameras_code",
                table: "cameras",
                column: "code",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_cameras_is_active",
                table: "cameras",
                column: "is_active");

            migrationBuilder.CreateIndex(
                name: "IX_entities_display_code",
                table: "entities",
                column: "display_code",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_entities_representative_artifact_id",
                table: "entities",
                column: "representative_artifact_id");

            migrationBuilder.CreateIndex(
                name: "IX_observations_thumbnail_artifact_id",
                table: "observations",
                column: "thumbnail_artifact_id");

            migrationBuilder.CreateIndex(
                name: "IX_observations_track_id",
                table: "observations",
                column: "track_id");

            migrationBuilder.CreateIndex(
                name: "IX_processing_runs_status",
                table: "processing_runs",
                column: "status");

            migrationBuilder.CreateIndex(
                name: "IX_processing_runs_video_asset_id",
                table: "processing_runs",
                column: "video_asset_id");

            migrationBuilder.CreateIndex(
                name: "IX_tracks_entity_id",
                table: "tracks",
                column: "entity_id");

            migrationBuilder.CreateIndex(
                name: "IX_tracks_object_class_start_timestamp_utc",
                table: "tracks",
                columns: new[] { "object_class", "start_timestamp_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_tracks_processing_run_id",
                table: "tracks",
                column: "processing_run_id");

            migrationBuilder.CreateIndex(
                name: "IX_tracks_processing_run_id_local_track_number",
                table: "tracks",
                columns: new[] { "processing_run_id", "local_track_number" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_tracks_representative_observation_id",
                table: "tracks",
                column: "representative_observation_id");

            migrationBuilder.CreateIndex(
                name: "IX_tracks_trajectory_artifact_id",
                table: "tracks",
                column: "trajectory_artifact_id");

            migrationBuilder.CreateIndex(
                name: "IX_tracks_video_asset_id_start_timestamp_utc",
                table: "tracks",
                columns: new[] { "video_asset_id", "start_timestamp_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_video_assets_camera_id_recording_start_utc",
                table: "video_assets",
                columns: new[] { "camera_id", "recording_start_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_video_assets_imported_at_utc",
                table: "video_assets",
                column: "imported_at_utc");

            migrationBuilder.CreateIndex(
                name: "IX_video_assets_processing_status",
                table: "video_assets",
                column: "processing_status");

            migrationBuilder.CreateIndex(
                name: "IX_video_assets_source_artifact_id",
                table: "video_assets",
                column: "source_artifact_id");

            migrationBuilder.CreateIndex(
                name: "IX_vision_jobs_processing_run_id",
                table: "vision_jobs",
                column: "processing_run_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_vision_jobs_status_available_at_utc",
                table: "vision_jobs",
                columns: new[] { "status", "available_at_utc" });

            migrationBuilder.CreateIndex(
                name: "IX_visual_attributes_observation_id",
                table: "visual_attributes",
                column: "observation_id");

            migrationBuilder.CreateIndex(
                name: "IX_visual_attributes_track_id",
                table: "visual_attributes",
                column: "track_id");

            migrationBuilder.AddForeignKey(
                name: "FK_observations_tracks_track_id",
                table: "observations",
                column: "track_id",
                principalTable: "tracks",
                principalColumn: "id",
                onDelete: ReferentialAction.Cascade);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_entities_artifacts_representative_artifact_id",
                table: "entities");

            migrationBuilder.DropForeignKey(
                name: "FK_observations_artifacts_thumbnail_artifact_id",
                table: "observations");

            migrationBuilder.DropForeignKey(
                name: "FK_tracks_artifacts_trajectory_artifact_id",
                table: "tracks");

            migrationBuilder.DropForeignKey(
                name: "FK_video_assets_artifacts_source_artifact_id",
                table: "video_assets");

            migrationBuilder.DropForeignKey(
                name: "FK_observations_tracks_track_id",
                table: "observations");

            migrationBuilder.DropTable(
                name: "vision_jobs");

            migrationBuilder.DropTable(
                name: "visual_attributes");

            migrationBuilder.DropTable(
                name: "artifacts");

            migrationBuilder.DropTable(
                name: "tracks");

            migrationBuilder.DropTable(
                name: "entities");

            migrationBuilder.DropTable(
                name: "observations");

            migrationBuilder.DropTable(
                name: "processing_runs");

            migrationBuilder.DropTable(
                name: "video_assets");

            migrationBuilder.DropTable(
                name: "cameras");
        }
    }
}
#pragma warning restore CA1861
