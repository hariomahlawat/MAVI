using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable
#pragma warning disable CA1861 // Generated migration index column arrays are immutable inputs.

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAnalyticEvents : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "permitted_direction",
                table: "trip_lines",
                type: "character varying(8)",
                maxLength: 8,
                nullable: true);

            migrationBuilder.CreateTable(
                name: "analytic_event_derivations",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    scene_analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    camera_id = table.Column<Guid>(type: "uuid", nullable: false),
                    scene_revision_id = table.Column<Guid>(type: "uuid", nullable: false),
                    analytics_algorithm_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    catalogue_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    catalogue_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    inputs_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    event_count = table.Column<int>(type: "integer", nullable: false),
                    rule_states = table.Column<string>(type: "jsonb", nullable: false),
                    derived_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_analytic_event_derivations", x => x.id);
                    table.CheckConstraint("ck_analytic_event_derivations_count", "event_count >= 0");
                    table.CheckConstraint("ck_analytic_event_derivations_rule_states", "jsonb_typeof(rule_states) = 'array'");
                    table.ForeignKey(
                        name: "FK_analytic_event_derivations_scene_analyses_scene_analysis_id",
                        column: x => x.scene_analysis_id,
                        principalTable: "scene_analyses",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "analytic_events",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    derivation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    scene_analysis_id = table.Column<Guid>(type: "uuid", nullable: false),
                    processing_run_id = table.Column<Guid>(type: "uuid", nullable: false),
                    video_asset_id = table.Column<Guid>(type: "uuid", nullable: false),
                    camera_id = table.Column<Guid>(type: "uuid", nullable: false),
                    scene_revision_id = table.Column<Guid>(type: "uuid", nullable: false),
                    analytics_algorithm_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    catalogue_version = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    rule_id = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    rule_version = table.Column<int>(type: "integer", nullable: false),
                    primary_track_id = table.Column<Guid>(type: "uuid", nullable: true),
                    object_class = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                    zone_id = table.Column<Guid>(type: "uuid", nullable: true),
                    line_id = table.Column<Guid>(type: "uuid", nullable: true),
                    direction = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                    start_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                    end_offset_ms = table.Column<long>(type: "bigint", nullable: false),
                    start_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    end_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    participant_count = table.Column<int>(type: "integer", nullable: false),
                    provenance = table.Column<string>(type: "jsonb", nullable: false),
                    input_sha256 = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_analytic_events", x => x.id);
                    table.CheckConstraint("ck_analytic_events_direction", "direction IS NULL OR direction IN ('AToB', 'BToA')");
                    table.CheckConstraint("ck_analytic_events_participants", "participant_count >= 0");
                    table.CheckConstraint("ck_analytic_events_provenance", "jsonb_typeof(provenance) = 'object'");
                    table.CheckConstraint("ck_analytic_events_rule_version", "rule_version >= 1");
                    table.CheckConstraint("ck_analytic_events_span", "start_offset_ms >= 0 AND end_offset_ms >= start_offset_ms AND end_utc >= start_utc");
                    table.ForeignKey(
                        name: "FK_analytic_events_analytic_event_derivations_derivation_id",
                        column: x => x.derivation_id,
                        principalTable: "analytic_event_derivations",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_analytic_events_tracks_primary_track_id",
                        column: x => x.primary_track_id,
                        principalTable: "tracks",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.AddCheckConstraint(
                name: "ck_trip_lines_permitted_direction",
                table: "trip_lines",
                sql: "permitted_direction IS NULL OR (directed AND permitted_direction IN ('AToB', 'BToA'))");

            migrationBuilder.CreateIndex(
                name: "ux_analytic_event_derivations_unit_catalogue",
                table: "analytic_event_derivations",
                columns: new[] { "scene_analysis_id", "catalogue_version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_analytic_events_camera_catalogue_start",
                table: "analytic_events",
                columns: new[] { "camera_id", "catalogue_version", "start_utc" });

            migrationBuilder.CreateIndex(
                name: "ix_analytic_events_derivation",
                table: "analytic_events",
                column: "derivation_id");

            migrationBuilder.CreateIndex(
                name: "ix_analytic_events_primary_track",
                table: "analytic_events",
                column: "primary_track_id");

            migrationBuilder.CreateIndex(
                name: "ix_analytic_events_scene_analysis",
                table: "analytic_events",
                column: "scene_analysis_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "analytic_events");

            migrationBuilder.DropTable(
                name: "analytic_event_derivations");

            migrationBuilder.DropCheckConstraint(
                name: "ck_trip_lines_permitted_direction",
                table: "trip_lines");

            migrationBuilder.DropColumn(
                name: "permitted_direction",
                table: "trip_lines");
        }
    }
}
