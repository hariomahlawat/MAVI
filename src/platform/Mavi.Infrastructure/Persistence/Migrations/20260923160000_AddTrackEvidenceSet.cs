using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations;

/// <summary>
/// Evolves <c>observations</c> into the Track Evidence Set (ADR-013 §7, S1.2 plan §10.2):
/// the four frozen evidence roles, a per-Track evidence rank and the selector score.
/// </summary>
/// <remarks>
/// <para>
/// No evidence byte and no artefact row is rewritten. Every historical observation is a
/// completion 2.0 Representative, so it becomes rank 0 with <c>selection_score =
/// quality_score</c>. The migration refuses to run if any row carries a retired legacy
/// type (<c>TrackStart</c>, <c>BestQuality</c>, <c>TrackEnd</c>): those values were never
/// written, and silently mapping one would invent evidence semantics.
/// </para>
/// <para>
/// <b>Binary rollback before any completion 3.0 row exists stays safe.</b> The platform
/// applies migrations at startup and a preceding binary starts against a database that
/// carries this extra migration, then inserts observations without the two new columns.
/// <c>evidence_rank</c> therefore keeps <c>DEFAULT 0</c> (every row an older binary can
/// write is a Representative) and a <c>BEFORE INSERT</c> trigger fills an omitted
/// <c>selection_score</c> from <c>quality_score</c> — the same rule as the backfill.
/// NOT NULL is checked after BEFORE triggers, so the column stays NOT NULL. The current
/// binary always writes both columns explicitly, so the trigger never overrides it.
/// Rollback after completion 3.0 rows exist is unsupported (an older binary cannot map
/// the new role values).
/// </para>
/// <para>
/// The crop foreign key moves from <c>SET NULL</c> to <c>RESTRICT</c>: accepted evidence
/// linkage must not be severed silently by deleting an artefact row.
/// </para>
/// </remarks>
[DbContext(typeof(MaviDbContext))]
[Migration("20260923160000_AddTrackEvidenceSet")]
public sealed class AddTrackEvidenceSet : Migration
{
    private static readonly string[] TrackRankColumns = ["track_id", "evidence_rank"];
    private static readonly string[] TrackRoleColumns = ["track_id", "observation_type"];
    private static readonly string[] TrackFrameColumns = ["track_id", "source_frame_number"];

    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM observations WHERE observation_type <> 'Representative') THEN
                    RAISE EXCEPTION 'observations_legacy_type_present';
                END IF;
            END $$;
            """);

        migrationBuilder.AddColumn<int>(
            name: "evidence_rank",
            table: "observations",
            type: "integer",
            nullable: false,
            defaultValue: 0);

        migrationBuilder.AddColumn<double>(
            name: "selection_score",
            table: "observations",
            type: "double precision",
            nullable: true);

        migrationBuilder.Sql("UPDATE observations SET selection_score = quality_score;");

        migrationBuilder.AlterColumn<double>(
            name: "selection_score",
            table: "observations",
            type: "double precision",
            nullable: false,
            oldClrType: typeof(double),
            oldType: "double precision",
            oldNullable: true);

        migrationBuilder.Sql("""
            CREATE FUNCTION observations_default_selection_score() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.selection_score IS NULL THEN
                    NEW.selection_score := NEW.quality_score;
                END IF;
                RETURN NEW;
            END $$;

            CREATE TRIGGER tr_observations_default_selection_score
                BEFORE INSERT ON observations
                FOR EACH ROW EXECUTE FUNCTION observations_default_selection_score();
            """);

        migrationBuilder.AddCheckConstraint(
            name: "ck_observations_type",
            table: "observations",
            sql: "observation_type IN ('Representative', 'NearView', 'EarlyDiverse', 'LateDiverse')");
        migrationBuilder.AddCheckConstraint(
            name: "ck_observations_rank",
            table: "observations",
            sql: "evidence_rank >= 0 AND evidence_rank <= 3");
        migrationBuilder.AddCheckConstraint(
            name: "ck_observations_role_rank",
            table: "observations",
            sql: "(observation_type = 'Representative') = (evidence_rank = 0)");
        migrationBuilder.AddCheckConstraint(
            name: "ck_observations_selection_score",
            table: "observations",
            sql: "selection_score >= 0 AND selection_score <= 1");

        migrationBuilder.CreateIndex(
            name: "ux_observations_track_rank",
            table: "observations",
            columns: TrackRankColumns,
            unique: true);
        migrationBuilder.CreateIndex(
            name: "ux_observations_track_role",
            table: "observations",
            columns: TrackRoleColumns,
            unique: true);
        migrationBuilder.CreateIndex(
            name: "ux_observations_track_frame",
            table: "observations",
            columns: TrackFrameColumns,
            unique: true);

        migrationBuilder.DropForeignKey(
            name: "FK_observations_artifacts_thumbnail_artifact_id",
            table: "observations");
        migrationBuilder.AddForeignKey(
            name: "FK_observations_artifacts_thumbnail_artifact_id",
            table: "observations",
            column: "thumbnail_artifact_id",
            principalTable: "artifacts",
            principalColumn: "id",
            onDelete: ReferentialAction.Restrict);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        // Never touches evidence bytes. Refuses when completion 3.0 rows exist: the
        // preceding schema cannot represent them.
        migrationBuilder.Sql("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM observations WHERE observation_type <> 'Representative') THEN
                    RAISE EXCEPTION 'observations_evidence_set_rows_present';
                END IF;
            END $$;
            """);

        migrationBuilder.DropForeignKey(
            name: "FK_observations_artifacts_thumbnail_artifact_id",
            table: "observations");
        migrationBuilder.AddForeignKey(
            name: "FK_observations_artifacts_thumbnail_artifact_id",
            table: "observations",
            column: "thumbnail_artifact_id",
            principalTable: "artifacts",
            principalColumn: "id",
            onDelete: ReferentialAction.SetNull);

        migrationBuilder.DropIndex(name: "ux_observations_track_frame", table: "observations");
        migrationBuilder.DropIndex(name: "ux_observations_track_role", table: "observations");
        migrationBuilder.DropIndex(name: "ux_observations_track_rank", table: "observations");

        migrationBuilder.DropCheckConstraint(name: "ck_observations_selection_score", table: "observations");
        migrationBuilder.DropCheckConstraint(name: "ck_observations_role_rank", table: "observations");
        migrationBuilder.DropCheckConstraint(name: "ck_observations_rank", table: "observations");
        migrationBuilder.DropCheckConstraint(name: "ck_observations_type", table: "observations");

        migrationBuilder.Sql("""
            DROP TRIGGER tr_observations_default_selection_score ON observations;
            DROP FUNCTION observations_default_selection_score();
            """);

        migrationBuilder.DropColumn(name: "selection_score", table: "observations");
        migrationBuilder.DropColumn(name: "evidence_rank", table: "observations");
    }
}
