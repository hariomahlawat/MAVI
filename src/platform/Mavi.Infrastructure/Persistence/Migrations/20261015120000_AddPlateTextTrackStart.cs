using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// The plate search's candidate sort key (Stage 4 PR-4, option (c2); ADR-018): <c>plate_track_texts</c> gains
    /// <c>track_start_timestamp_utc</c>, a database-maintained copy of its Track's <c>tracks.start_timestamp_utc</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>Atomic.</b> One migration transaction: the column is added (which holds an ACCESS EXCLUSIVE lock on
    /// <c>plate_track_texts</c> until commit, so no text can be written meanwhile), backfilled from <c>tracks</c>,
    /// verified, made NOT NULL, and only then are the two triggers created. Either all of it commits or none.
    /// </para>
    /// <para>
    /// <b>Maintenance.</b> A BEFORE INSERT OR UPDATE row trigger on <c>plate_track_texts</c> derives the value from
    /// <c>tracks</c> in the writing statement and replaces any value supplied, so PR-3's <c>COPY</c> publication,
    /// whose column list does not name it, is unchanged in code. The same trigger refuses a text whose Track is
    /// not of its analysis's run (PR-3's completion invariant, which the search's candidate read relies on;
    /// ADR-018). An AFTER UPDATE OF <c>start_timestamp_utc</c> row trigger on <c>tracks</c> carries a changed start
    /// time to the Track's texts, through <c>plate_track_outcomes</c>' Track index and the texts' primary key.
    /// </para>
    /// <para>
    /// <b>Reversible.</b> Down drops the triggers, their functions and the column. The column holds nothing
    /// authoritative (it is derived), so Down loses no fact and a later Up recomputes it.
    /// </para>
    /// <para>
    /// <b>Cost.</b> The backfill rewrites every text row (≈ 38 s at 10^6 rows in the prototype on the Development
    /// host) and leaves the previous row versions to autovacuum; <c>VACUUM (ANALYZE) plate_track_texts</c> after
    /// the upgrade reclaims them at once (ADR-018).
    /// </para>
    /// </remarks>
    public partial class AddPlateTextTrackStart : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<DateTimeOffset>(
                name: "track_start_timestamp_utc",
                table: "plate_track_texts",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.Sql(
                """
                UPDATE plate_track_texts x SET track_start_timestamp_utc = t.start_timestamp_utc
                FROM tracks t WHERE t.id = x.track_id;

                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM plate_track_texts WHERE track_start_timestamp_utc IS NULL) THEN
                        RAISE EXCEPTION 'AddPlateTextTrackStart: a plate Track text has no Track';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM plate_track_texts x
                        JOIN tracks t ON t.id = x.track_id
                        JOIN plate_analyses a ON a.id = x.analysis_id
                        WHERE t.processing_run_id <> a.processing_run_id) THEN
                        RAISE EXCEPTION 'AddPlateTextTrackStart: a plate Track text names a Track of another run than its analysis';
                    END IF;
                END $$;
                """);

            migrationBuilder.AlterColumn<DateTimeOffset>(
                name: "track_start_timestamp_utc",
                table: "plate_track_texts",
                type: "timestamp with time zone",
                nullable: false,
                oldClrType: typeof(DateTimeOffset),
                oldType: "timestamp with time zone",
                oldNullable: true);

            migrationBuilder.Sql(
                """
                CREATE FUNCTION plate_track_texts_derive_track_start() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    track_run uuid;
                    analysis_run uuid;
                BEGIN
                    SELECT t.start_timestamp_utc, t.processing_run_id
                    INTO NEW.track_start_timestamp_utc, track_run
                    FROM tracks t WHERE t.id = NEW.track_id;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION USING
                            ERRCODE = 'foreign_key_violation',
                            CONSTRAINT = 'tr_plate_track_texts_track_start',
                            MESSAGE = 'A plate Track text names a Track that does not exist.';
                    END IF;
                    SELECT a.processing_run_id INTO analysis_run FROM plate_analyses a WHERE a.id = NEW.analysis_id;
                    -- A missing analysis is left to the foreign keys; a Track of another run is refused.
                    IF FOUND AND analysis_run <> track_run THEN
                        RAISE EXCEPTION USING
                            ERRCODE = 'check_violation',
                            CONSTRAINT = 'tr_plate_track_texts_track_start',
                            MESSAGE = 'A plate Track text names a Track of another run than its analysis.';
                    END IF;
                    RETURN NEW;
                END $$;

                CREATE TRIGGER tr_plate_track_texts_track_start
                    BEFORE INSERT OR UPDATE ON plate_track_texts
                    FOR EACH ROW EXECUTE FUNCTION plate_track_texts_derive_track_start();

                CREATE FUNCTION tracks_carry_plate_text_track_start() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    UPDATE plate_track_texts x SET track_start_timestamp_utc = NEW.start_timestamp_utc
                    FROM plate_track_outcomes o
                    WHERE o.track_id = NEW.id AND x.analysis_id = o.analysis_id AND x.track_id = NEW.id;
                    RETURN NULL;
                END $$;

                CREATE TRIGGER tr_tracks_plate_text_track_start
                    AFTER UPDATE OF start_timestamp_utc ON tracks
                    FOR EACH ROW WHEN (OLD.start_timestamp_utc IS DISTINCT FROM NEW.start_timestamp_utc)
                    EXECUTE FUNCTION tracks_carry_plate_text_track_start();
                """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                """
                DROP TRIGGER tr_tracks_plate_text_track_start ON tracks;
                DROP FUNCTION tracks_carry_plate_text_track_start();
                DROP TRIGGER tr_plate_track_texts_track_start ON plate_track_texts;
                DROP FUNCTION plate_track_texts_derive_track_start();
                """);

            migrationBuilder.DropColumn(
                name: "track_start_timestamp_utc",
                table: "plate_track_texts");
        }
    }
}
