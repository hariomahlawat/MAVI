using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// ADR-018 hardening (Stage 4 PR-4 cold review P3): the trigger deriving
    /// <c>plate_track_texts.track_start_timestamp_utc</c> reads its Track row <c>FOR SHARE</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>The race it closes.</b> Under READ COMMITTED, without a lock, a text insert could read a Track's start
    /// while a concurrent transaction had already updated that start but not committed. That transaction's carry
    /// trigger (<c>tr_tracks_plate_text_track_start</c>) cannot see the uncommitted text, and the insert does not
    /// see the new start, so both commit and the text keeps the old start: drift.
    /// </para>
    /// <para>
    /// <b>Why FOR SHARE.</b> A Track update that does not change a key takes FOR NO KEY UPDATE, which conflicts
    /// with FOR SHARE (FOR KEY SHARE would not conflict, so it would not close the race). Either order is then
    /// serialised on the Track row: an insert that comes second waits for the update to commit and reads the new
    /// start; an update that comes second waits for the insert to commit, and its carry trigger's own statement
    /// then sees the committed text and carries the new start to it. Under REPEATABLE READ or SERIALIZABLE the
    /// second writer fails with a serialization error rather than deriving a stale value. The column remains an
    /// accelerator only (ADR-018) and transactionally consistent with its Track.
    /// </para>
    /// <para>
    /// <b>Scope.</b> Replaces only the function body (<c>CREATE OR REPLACE</c>); the triggers, the column and its
    /// values are untouched, and nothing is rewritten. Down restores the previous body. The applied migration
    /// <c>20261015120000_AddPlateTextTrackStart</c> is not edited.
    /// </para>
    /// </remarks>
    public partial class LockTrackForPlateTextTrackStart : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder) =>
            migrationBuilder.Sql(DeriveFunction(lockTrack: true));

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder) =>
            migrationBuilder.Sql(DeriveFunction(lockTrack: false));

        /// <summary>The trigger function, with or without the Track row lock; otherwise identical to the 2026-10-15 body.</summary>
        internal static string DeriveFunction(bool lockTrack) =>
            $$"""
            CREATE OR REPLACE FUNCTION plate_track_texts_derive_track_start() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                track_run uuid;
                analysis_run uuid;
            BEGIN
                SELECT t.start_timestamp_utc, t.processing_run_id
                INTO NEW.track_start_timestamp_utc, track_run
                FROM tracks t WHERE t.id = NEW.track_id{{(lockTrack ? " FOR SHARE" : string.Empty)}};
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
            """;
    }
}
