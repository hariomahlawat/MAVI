using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

/// <summary>
/// Adds the detector-native vehicle subclass to <c>tracks</c> (Stage 3, ADR-016): the
/// subclass, its vocabulary and the source that resolved it.
/// </summary>
/// <remarks>
/// <para>
/// No row is rewritten. Every existing Track keeps all three columns null, which is
/// exactly the "processed before Stage 3" state; nothing is inferred for history.
/// </para>
/// <para>
/// <b>Binary rollback stays safe.</b> The columns are nullable with no default, so an
/// older binary inserting Tracks without them writes the pre-Stage-3 state, which both
/// check constraints accept. A rolled-back platform cannot replay a stored completion 3.3
/// payload, which is unsupported, as for 3.2.
/// </para>
/// </remarks>
[DbContext(typeof(MaviDbContext))]
[Migration("20261002120000_AddTrackObjectSubclass")]
public sealed class AddTrackObjectSubclass : Migration
{
    private static readonly string[] SubclassIndexColumns = ["object_subclass", "start_timestamp_utc"];

    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "object_subclass",
            table: "tracks",
            type: "character varying(32)",
            maxLength: 32,
            nullable: true);

        migrationBuilder.AddColumn<string>(
            name: "object_subclass_source",
            table: "tracks",
            type: "character varying(128)",
            maxLength: 128,
            nullable: true);

        migrationBuilder.AddColumn<string>(
            name: "object_subclass_vocabulary",
            table: "tracks",
            type: "character varying(64)",
            maxLength: 64,
            nullable: true);

        migrationBuilder.AddCheckConstraint(
            name: "ck_tracks_object_subclass_state",
            table: "tracks",
            sql: "(object_subclass IS NULL AND object_subclass_vocabulary IS NULL AND object_subclass_source IS NULL) OR (object_class = 'Vehicle' AND object_subclass_vocabulary IS NOT NULL AND object_subclass_source IS NOT NULL)");

        migrationBuilder.AddCheckConstraint(
            name: "ck_tracks_object_subclass_value",
            table: "tracks",
            sql: "object_subclass IS NULL OR (object_subclass_vocabulary = 'mavi-vehicle-subclass-v1' AND object_subclass IN ('car', 'truck', 'bus', 'motorcycle'))");

        migrationBuilder.CreateIndex(
            name: "IX_tracks_object_subclass_start_timestamp_utc",
            table: "tracks",
            columns: SubclassIndexColumns,
            filter: "object_subclass IS NOT NULL");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropIndex(
            name: "IX_tracks_object_subclass_start_timestamp_utc",
            table: "tracks");

        migrationBuilder.DropCheckConstraint(
            name: "ck_tracks_object_subclass_value",
            table: "tracks");

        migrationBuilder.DropCheckConstraint(
            name: "ck_tracks_object_subclass_state",
            table: "tracks");

        migrationBuilder.DropColumn(
            name: "object_subclass_vocabulary",
            table: "tracks");

        migrationBuilder.DropColumn(
            name: "object_subclass_source",
            table: "tracks");

        migrationBuilder.DropColumn(
            name: "object_subclass",
            table: "tracks");
    }
}
