using System;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

/// <summary>
/// Adds the scene analytics lifecycle unit and the derived facts a completed unit owns:
/// per-Track outcomes, zone visits, per-zone summaries, trip-line crossings and motion
/// summaries.
/// </summary>
/// <remarks>
/// <para>
/// Purely additive. No existing table, column, index or constraint is touched, so the
/// upgrade cannot disturb evidence already sealed by a processing run.
/// </para>
/// <para>
/// Facts cascade from their <c>scene_analyses</c> row, because a unit owns its own facts
/// and a same-unit rewrite replaces them wholesale. The foreign key to <c>tracks</c> is
/// <see cref="ReferentialAction.Restrict"/> instead: derived analytics must never become a
/// route by which detector evidence is deleted.
/// </para>
/// <para>
/// Nothing here encodes lease expiry as loss of ownership. <c>lease_expires_at_utc</c> and
/// <c>claim_token_hash</c> are plain columns with no trigger, no generated state and no
/// partial index that would make an expired lease mean "unowned" — ADR-011 Decision 4
/// reserves that transition for the reconciler's two fenced updates, taken under a row
/// lock. The pending index filters on <c>status</c> alone for the same reason.
/// </para>
/// </remarks>
[DbContext(typeof(MaviDbContext))]
[Migration("20260921004943_AddSceneAnalytics")]
public sealed class AddSceneAnalytics : Migration
{
    private static readonly string[] StatusAndQueuedAtColumns =
        ["status", "queued_at_utc"];

    private static readonly string[] AnalysisIdentityColumns =
        ["processing_run_id", "revision_id", "algorithm_version"];

    private static readonly string[] LineTimeDirectionColumns =
        ["line_id", "timestamp_utc", "direction"];

    private static readonly string[] LineCrossingIdentityColumns =
        ["analysis_id", "track_id", "line_id", "crossing_index"];

    private static readonly string[] ZoneDwellColumns =
        ["zone_id", "total_dwell_ms"];

    private static readonly string[] ZoneLoiteringColumns =
        ["zone_id", "loitering"];

    private static readonly string[] AnalysisAndTrackColumns =
        ["analysis_id", "track_id"];

    private static readonly string[] ZoneEntryColumns =
        ["zone_id", "entry_timestamp_utc"];

    private static readonly string[] ZoneVisitIdentityColumns =
        ["analysis_id", "track_id", "zone_id", "visit_index"];

    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateTable(
            name: "scene_analyses",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                revision_id = table.Column<Guid>(type: "uuid", nullable: false),
                algorithm_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                parameters_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                source_commit = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                attempt_count = table.Column<int>(type: "integer", nullable: false),
                claim_token_hash = table.Column<byte[]>(type: "bytea", nullable: true),
                lease_expires_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                queued_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                started_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                completed_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                visibility_sequence = table.Column<long>(type: "bigint", nullable: true),
                analysed_track_count = table.Column<int>(type: "integer", nullable: false),
                unavailable_track_count = table.Column<int>(type: "integer", nullable: false),
                failure_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                failure_details = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_scene_analyses", x => x.id);
                table.CheckConstraint("ck_scene_analyses_attempt_count", "attempt_count >= 0");
                table.CheckConstraint("ck_scene_analyses_claim_token_hash", "claim_token_hash IS NULL OR octet_length(claim_token_hash) = 32");
                table.CheckConstraint("ck_scene_analyses_parameters_sha256", "parameters_sha256 ~ '^[0-9a-f]{64}$'");
                table.CheckConstraint("ck_scene_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
                table.CheckConstraint("ck_scene_analyses_track_counts", "analysed_track_count >= 0 AND unavailable_track_count >= 0");
                table.CheckConstraint("ck_scene_analyses_visibility_sequence", "visibility_sequence IS NULL OR visibility_sequence > 0");
                table.ForeignKey(
                    name: "FK_scene_analyses_processing_runs_processing_run_id",
                    column: x => x.processing_run_id,
                    principalTable: "processing_runs",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
                table.ForeignKey(
                    name: "FK_scene_analyses_scene_configuration_revisions_revision_id",
                    column: x => x.revision_id,
                    principalTable: "scene_configuration_revisions",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "track_analysis_outcomes",
            columns: table => new
            {
                analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                track_id = table.Column<Guid>(type: "uuid", nullable: false),
                outcome = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                reason = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                reference_point = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                sample_count = table.Column<int>(type: "integer", nullable: false),
                gap_count = table.Column<int>(type: "integer", nullable: false),
                gap_total_ms = table.Column<long>(type: "bigint", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_track_analysis_outcomes", x => new { x.analysis_id, x.track_id });
                table.CheckConstraint("ck_track_analysis_outcomes_counts", "sample_count >= 0 AND gap_count >= 0 AND gap_total_ms >= 0");
                table.CheckConstraint("ck_track_analysis_outcomes_outcome", "outcome IN ('Analysed', 'Unavailable')");
                table.CheckConstraint("ck_track_analysis_outcomes_reason", "reason IS NULL OR reason IN ('trajectory_missing', 'trajectory_integrity_failed', 'trajectory_invalid', 'trajectory_too_short')");
                table.CheckConstraint("ck_track_analysis_outcomes_reference_point", "reference_point IS NULL OR reference_point IN ('bbox-centre')");
                table.CheckConstraint("ck_track_analysis_outcomes_shape", "(outcome = 'Analysed' AND reason IS NULL AND reference_point IS NOT NULL) OR (outcome = 'Unavailable' AND reason IS NOT NULL AND reference_point IS NULL AND sample_count = 0 AND gap_count = 0 AND gap_total_ms = 0)");
                table.ForeignKey(
                    name: "FK_track_analysis_outcomes_scene_analyses_analysis_id",
                    column: x => x.analysis_id,
                    principalTable: "scene_analyses",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
                table.ForeignKey(
                    name: "FK_track_analysis_outcomes_tracks_track_id",
                    column: x => x.track_id,
                    principalTable: "tracks",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "track_line_crossings",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                track_id = table.Column<Guid>(type: "uuid", nullable: false),
                line_id = table.Column<Guid>(type: "uuid", nullable: false),
                crossing_index = table.Column<int>(type: "integer", nullable: false),
                offset_ms = table.Column<long>(type: "bigint", nullable: false),
                timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                direction = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                point_x = table.Column<double>(type: "double precision", nullable: false),
                point_y = table.Column<double>(type: "double precision", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_track_line_crossings", x => x.id);
                table.CheckConstraint("ck_track_line_crossings_direction", "direction IN ('AToB', 'BToA')");
                table.CheckConstraint("ck_track_line_crossings_indexes", "crossing_index >= 0 AND offset_ms >= 0");
                table.CheckConstraint("ck_track_line_crossings_point", "point_x >= 0 AND point_x <= 1 AND point_y >= 0 AND point_y <= 1");
                table.ForeignKey(
                    name: "FK_track_line_crossings_scene_analyses_analysis_id",
                    column: x => x.analysis_id,
                    principalTable: "scene_analyses",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
                table.ForeignKey(
                    name: "FK_track_line_crossings_tracks_track_id",
                    column: x => x.track_id,
                    principalTable: "tracks",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "track_motion_summaries",
            columns: table => new
            {
                analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                track_id = table.Column<Guid>(type: "uuid", nullable: false),
                heading = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                path_length_normalised = table.Column<double>(type: "double precision", nullable: false),
                mean_displacement_rate = table.Column<double>(type: "double precision", nullable: false),
                longest_stationary_ms = table.Column<long>(type: "bigint", nullable: false),
                total_stationary_ms = table.Column<long>(type: "bigint", nullable: false),
                stationary_intervals = table.Column<string>(type: "jsonb", nullable: false),
                stationary_zone_ids = table.Column<string>(type: "jsonb", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_track_motion_summaries", x => new { x.analysis_id, x.track_id });
                table.CheckConstraint("ck_track_motion_summaries_durations", "longest_stationary_ms >= 0 AND total_stationary_ms >= 0 AND longest_stationary_ms <= total_stationary_ms");
                table.CheckConstraint("ck_track_motion_summaries_heading", "heading IN ('None', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')");
                table.CheckConstraint("ck_track_motion_summaries_json_shape", "jsonb_typeof(stationary_intervals) = 'array' AND jsonb_typeof(stationary_zone_ids) = 'array'");
                table.CheckConstraint("ck_track_motion_summaries_path", "path_length_normalised >= 0 AND mean_displacement_rate >= 0");
                table.ForeignKey(
                    name: "FK_track_motion_summaries_scene_analyses_analysis_id",
                    column: x => x.analysis_id,
                    principalTable: "scene_analyses",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
                table.ForeignKey(
                    name: "FK_track_motion_summaries_tracks_track_id",
                    column: x => x.track_id,
                    principalTable: "tracks",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "track_zone_summaries",
            columns: table => new
            {
                analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                track_id = table.Column<Guid>(type: "uuid", nullable: false),
                zone_id = table.Column<Guid>(type: "uuid", nullable: false),
                visit_count = table.Column<int>(type: "integer", nullable: false),
                total_dwell_ms = table.Column<long>(type: "bigint", nullable: false),
                first_entry_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                last_exit_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                loitering = table.Column<bool>(type: "boolean", nullable: false),
                loitering_threshold_seconds = table.Column<int>(type: "integer", nullable: false),
                loitering_dwell_ms = table.Column<long>(type: "bigint", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_track_zone_summaries", x => new { x.analysis_id, x.track_id, x.zone_id });
                table.CheckConstraint("ck_track_zone_summaries_counts", "visit_count >= 0 AND total_dwell_ms >= 0 AND loitering_dwell_ms >= 0");
                table.CheckConstraint("ck_track_zone_summaries_loitering_threshold", "loitering_threshold_seconds > 0");
                table.CheckConstraint("ck_track_zone_summaries_timestamps", "(first_entry_timestamp_utc IS NULL AND last_exit_timestamp_utc IS NULL) OR (first_entry_timestamp_utc IS NOT NULL AND last_exit_timestamp_utc IS NOT NULL AND last_exit_timestamp_utc >= first_entry_timestamp_utc)");
                table.CheckConstraint("ck_track_zone_summaries_visitless", "visit_count > 0 OR (first_entry_timestamp_utc IS NULL AND total_dwell_ms = 0)");
                table.ForeignKey(
                    name: "FK_track_zone_summaries_scene_analyses_analysis_id",
                    column: x => x.analysis_id,
                    principalTable: "scene_analyses",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
                table.ForeignKey(
                    name: "FK_track_zone_summaries_tracks_track_id",
                    column: x => x.track_id,
                    principalTable: "tracks",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "track_zone_visits",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                track_id = table.Column<Guid>(type: "uuid", nullable: false),
                zone_id = table.Column<Guid>(type: "uuid", nullable: false),
                visit_index = table.Column<int>(type: "integer", nullable: false),
                entry_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                exit_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                entry_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                exit_timestamp_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                dwell_ms = table.Column<long>(type: "bigint", nullable: false),
                began_inside = table.Column<bool>(type: "boolean", nullable: false),
                ended_inside = table.Column<bool>(type: "boolean", nullable: false),
                closed_by_gap = table.Column<bool>(type: "boolean", nullable: false),
                entry_heading = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                exit_heading = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_track_zone_visits", x => x.id);
                table.CheckConstraint("ck_track_zone_visits_dwell", "dwell_ms >= 0");
                table.CheckConstraint("ck_track_zone_visits_headings", "entry_heading IN ('None', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW') AND exit_heading IN ('None', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')");
                table.CheckConstraint("ck_track_zone_visits_offsets", "entry_offset_ms >= 0 AND exit_offset_ms >= entry_offset_ms");
                table.CheckConstraint("ck_track_zone_visits_timestamps", "exit_timestamp_utc >= entry_timestamp_utc");
                table.CheckConstraint("ck_track_zone_visits_visit_index", "visit_index >= 0");
                table.ForeignKey(
                    name: "FK_track_zone_visits_scene_analyses_analysis_id",
                    column: x => x.analysis_id,
                    principalTable: "scene_analyses",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
                table.ForeignKey(
                    name: "FK_track_zone_visits_tracks_track_id",
                    column: x => x.track_id,
                    principalTable: "tracks",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateIndex(
            name: "ix_scene_analyses_pending",
            table: "scene_analyses",
            columns: StatusAndQueuedAtColumns,
            filter: "status IN ('Queued', 'Running')");

        migrationBuilder.CreateIndex(
            name: "IX_scene_analyses_revision_id",
            table: "scene_analyses",
            column: "revision_id");

        migrationBuilder.CreateIndex(
            name: "ix_scene_analyses_run",
            table: "scene_analyses",
            column: "processing_run_id");

        migrationBuilder.CreateIndex(
            name: "ux_scene_analyses_identity",
            table: "scene_analyses",
            columns: AnalysisIdentityColumns,
            unique: true);

        migrationBuilder.CreateIndex(
            name: "ux_scene_analyses_visibility_sequence",
            table: "scene_analyses",
            column: "visibility_sequence",
            unique: true,
            filter: "visibility_sequence IS NOT NULL");

        migrationBuilder.CreateIndex(
            name: "IX_track_analysis_outcomes_track_id",
            table: "track_analysis_outcomes",
            column: "track_id");

        migrationBuilder.CreateIndex(
            name: "ix_track_line_crossings_line_time_direction",
            table: "track_line_crossings",
            columns: LineTimeDirectionColumns);

        migrationBuilder.CreateIndex(
            name: "IX_track_line_crossings_track_id",
            table: "track_line_crossings",
            column: "track_id");

        migrationBuilder.CreateIndex(
            name: "ux_track_line_crossings_identity",
            table: "track_line_crossings",
            columns: LineCrossingIdentityColumns,
            unique: true);

        migrationBuilder.CreateIndex(
            name: "ix_track_motion_summaries_longest_stationary",
            table: "track_motion_summaries",
            column: "longest_stationary_ms");

        migrationBuilder.CreateIndex(
            name: "IX_track_motion_summaries_track_id",
            table: "track_motion_summaries",
            column: "track_id");

        migrationBuilder.CreateIndex(
            name: "IX_track_zone_summaries_track_id",
            table: "track_zone_summaries",
            column: "track_id");

        migrationBuilder.CreateIndex(
            name: "ix_track_zone_summaries_zone_dwell",
            table: "track_zone_summaries",
            columns: ZoneDwellColumns);

        migrationBuilder.CreateIndex(
            name: "ix_track_zone_summaries_zone_loitering",
            table: "track_zone_summaries",
            columns: ZoneLoiteringColumns,
            filter: "loitering");

        migrationBuilder.CreateIndex(
            name: "ix_track_zone_visits_analysis_track",
            table: "track_zone_visits",
            columns: AnalysisAndTrackColumns);

        migrationBuilder.CreateIndex(
            name: "IX_track_zone_visits_track_id",
            table: "track_zone_visits",
            column: "track_id");

        migrationBuilder.CreateIndex(
            name: "ix_track_zone_visits_zone_entry",
            table: "track_zone_visits",
            columns: ZoneEntryColumns);

        migrationBuilder.CreateIndex(
            name: "ux_track_zone_visits_identity",
            table: "track_zone_visits",
            columns: ZoneVisitIdentityColumns,
            unique: true);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropTable(
            name: "track_analysis_outcomes");

        migrationBuilder.DropTable(
            name: "track_line_crossings");

        migrationBuilder.DropTable(
            name: "track_motion_summaries");

        migrationBuilder.DropTable(
            name: "track_zone_summaries");

        migrationBuilder.DropTable(
            name: "track_zone_visits");

        migrationBuilder.DropTable(
            name: "scene_analyses");
    }
}
