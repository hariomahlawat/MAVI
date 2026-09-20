using System;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

/// <summary>
/// Adds per-camera scene configuration: the anchor, its immutable revisions and the
/// zones and trip lines each revision carries.
/// </summary>
/// <remarks>
/// Purely additive. No existing table, column or constraint is touched, so the
/// upgrade cannot disturb any data already in the database.
/// </remarks>
[DbContext(typeof(MaviDbContext))]
[Migration("20260920060000_AddSceneConfiguration")]
public sealed class AddSceneConfiguration : Migration
{
    private static readonly string[] ConfigurationAndNumberColumns =
        ["scene_configuration_id", "revision_number"];

    private static readonly string[] IdAndConfigurationColumns =
        ["id", "scene_configuration_id"];

    protected override void Up(MigrationBuilder migrationBuilder)
    {
        // Zone vertices live in jsonb, so the coordinate range that plain columns get
        // from a simple check needs a function to express. It is immutable and reads
        // only its argument, which is what lets a check constraint call it.
        migrationBuilder.Sql("""
            CREATE FUNCTION scene_vertices_in_range(vertices jsonb)
            RETURNS boolean
            LANGUAGE sql
            IMMUTABLE
            STRICT
            PARALLEL SAFE
            AS $$
                SELECT COALESCE(bool_and(
                    jsonb_typeof(vertex) = 'array'
                    AND jsonb_array_length(vertex) = 2
                    AND jsonb_typeof(vertex -> 0) = 'number'
                    AND jsonb_typeof(vertex -> 1) = 'number'
                    AND (vertex ->> 0)::numeric BETWEEN 0 AND 1
                    AND (vertex ->> 1)::numeric BETWEEN 0 AND 1), false)
                FROM jsonb_array_elements(vertices) AS vertex;
            $$;
            """);

        migrationBuilder.CreateTable(
            name: "scene_configurations",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                camera_id = table.Column<Guid>(type: "uuid", nullable: false),
                active_revision_id = table.Column<Guid>(type: "uuid", nullable: true),
                created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                updated_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_scene_configurations", x => x.id);
                table.ForeignKey(
                    name: "FK_scene_configurations_cameras_camera_id",
                    column: x => x.camera_id,
                    principalTable: "cameras",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "scene_configuration_revisions",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                scene_configuration_id = table.Column<Guid>(type: "uuid", nullable: false),
                revision_number = table.Column<int>(type: "integer", nullable: false),
                created_at_utc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                created_by = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                note = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                reference_frame_video_asset_id = table.Column<Guid>(type: "uuid", nullable: true),
                reference_frame_offset_ms = table.Column<long>(type: "bigint", nullable: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_scene_configuration_revisions", x => x.id);
                table.CheckConstraint("ck_scene_revisions_number", "revision_number >= 1");
                table.CheckConstraint("ck_scene_revisions_reference_frame", "(reference_frame_video_asset_id IS NULL AND reference_frame_offset_ms IS NULL) OR (reference_frame_video_asset_id IS NOT NULL AND reference_frame_offset_ms IS NOT NULL AND reference_frame_offset_ms >= 0)");
                table.ForeignKey(
                    name: "FK_scene_configuration_revisions_scene_configurations_scene_co~",
                    column: x => x.scene_configuration_id,
                    principalTable: "scene_configurations",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
                table.ForeignKey(
                    name: "FK_scene_configuration_revisions_video_assets_reference_frame_~",
                    column: x => x.reference_frame_video_asset_id,
                    principalTable: "video_assets",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "scene_zones",
            columns: table => new
            {
                revision_id = table.Column<Guid>(type: "uuid", nullable: false),
                zone_id = table.Column<Guid>(type: "uuid", nullable: false),
                name = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                kind = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                enabled = table.Column<bool>(type: "boolean", nullable: false),
                loitering_threshold_seconds = table.Column<int>(type: "integer", nullable: true),
                vertices = table.Column<string>(type: "jsonb", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_scene_zones", x => new { x.revision_id, x.zone_id });
                table.CheckConstraint("ck_scene_zones_loitering_threshold", "loitering_threshold_seconds IS NULL OR (loitering_threshold_seconds > 0 AND loitering_threshold_seconds <= 86400)");
                table.CheckConstraint("ck_scene_zones_vertex_count", "jsonb_array_length(vertices) BETWEEN 3 AND 64");
                table.ForeignKey(
                    name: "FK_scene_zones_scene_configuration_revisions_revision_id",
                    column: x => x.revision_id,
                    principalTable: "scene_configuration_revisions",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
            });

        migrationBuilder.CreateTable(
            name: "trip_lines",
            columns: table => new
            {
                revision_id = table.Column<Guid>(type: "uuid", nullable: false),
                line_id = table.Column<Guid>(type: "uuid", nullable: false),
                name = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                enabled = table.Column<bool>(type: "boolean", nullable: false),
                directed = table.Column<bool>(type: "boolean", nullable: false),
                a_to_b_label = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                b_to_a_label = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                ax = table.Column<double>(type: "double precision", nullable: false),
                ay = table.Column<double>(type: "double precision", nullable: false),
                bx = table.Column<double>(type: "double precision", nullable: false),
                by = table.Column<double>(type: "double precision", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_trip_lines", x => new { x.revision_id, x.line_id });
                table.CheckConstraint("ck_trip_lines_range", "ax BETWEEN 0 AND 1 AND ay BETWEEN 0 AND 1 AND bx BETWEEN 0 AND 1 AND by BETWEEN 0 AND 1");
                table.ForeignKey(
                    name: "FK_trip_lines_scene_configuration_revisions_revision_id",
                    column: x => x.revision_id,
                    principalTable: "scene_configuration_revisions",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
            });

        migrationBuilder.CreateIndex(
            name: "IX_scene_configuration_revisions_reference_frame_video_asset_id",
            table: "scene_configuration_revisions",
            column: "reference_frame_video_asset_id");

        migrationBuilder.CreateIndex(
            name: "ux_scene_revisions_configuration_number",
            table: "scene_configuration_revisions",
            columns: ConfigurationAndNumberColumns,
            unique: true);

        migrationBuilder.CreateIndex(
            name: "ux_scene_revisions_id_configuration",
            table: "scene_configuration_revisions",
            columns: IdAndConfigurationColumns,
            unique: true);

        migrationBuilder.CreateIndex(
            name: "ix_scene_configurations_active_revision",
            table: "scene_configurations",
            column: "active_revision_id");

        migrationBuilder.CreateIndex(
            name: "ux_scene_configurations_camera",
            table: "scene_configurations",
            column: "camera_id",
            unique: true);

        migrationBuilder.CreateIndex(
            name: "ix_scene_zones_zone",
            table: "scene_zones",
            column: "zone_id");

        migrationBuilder.CreateIndex(
            name: "ix_trip_lines_line",
            table: "trip_lines",
            column: "line_id");

        migrationBuilder.Sql("""
            ALTER TABLE scene_zones
            ADD CONSTRAINT ck_scene_zones_vertex_range
            CHECK (scene_vertices_in_range(vertices));
            """);

        // A configuration's active revision must be one of its own revisions. The
        // constraint is a cycle with the revision's own foreign key, so it is declared
        // deferrable and checked when the transaction commits rather than statement by
        // statement; that lets one transaction insert the configuration and the
        // revision it activates in either order, while still refusing a configuration
        // that points at a missing revision or at another camera's.
        migrationBuilder.Sql("""
            ALTER TABLE scene_configurations
            ADD CONSTRAINT fk_scene_configurations_active_revision
            FOREIGN KEY (active_revision_id, id)
            REFERENCES scene_configuration_revisions (id, scene_configuration_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            "ALTER TABLE scene_configurations DROP CONSTRAINT fk_scene_configurations_active_revision;");

        migrationBuilder.DropTable(
            name: "scene_zones");

        migrationBuilder.DropTable(
            name: "trip_lines");

        migrationBuilder.DropTable(
            name: "scene_configuration_revisions");

        migrationBuilder.DropTable(
            name: "scene_configurations");

        migrationBuilder.Sql("DROP FUNCTION IF EXISTS scene_vertices_in_range(jsonb);");
    }
}
