using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Mavi.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class PreserveRecordingTimeProvenance : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "recording_time_zone_id",
                table: "video_assets",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "recording_utc_offset_minutes",
                table: "video_assets",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            // Pre-release repair exception: normalize values accepted by the legacy Windows runtime before PostgreSQL uses them.
            migrationBuilder.Sql("""
                UPDATE cameras AS c
                SET time_zone_id = mapping.iana_id
                FROM (VALUES
                    ('Afghanistan Standard Time', 'Asia/Kabul'),
                    ('Alaskan Standard Time', 'America/Anchorage'),
                    ('Aleutian Standard Time', 'America/Adak'),
                    ('Altai Standard Time', 'Asia/Barnaul'),
                    ('Arab Standard Time', 'Asia/Riyadh'),
                    ('Arabian Standard Time', 'Asia/Dubai'),
                    ('Arabic Standard Time', 'Asia/Baghdad'),
                    ('Argentina Standard Time', 'America/Buenos_Aires'),
                    ('Astrakhan Standard Time', 'Europe/Astrakhan'),
                    ('Atlantic Standard Time', 'America/Halifax'),
                    ('AUS Central Standard Time', 'Australia/Darwin'),
                    ('Aus Central W. Standard Time', 'Australia/Eucla'),
                    ('AUS Eastern Standard Time', 'Australia/Sydney'),
                    ('Azerbaijan Standard Time', 'Asia/Baku'),
                    ('Azores Standard Time', 'Atlantic/Azores'),
                    ('Bahia Standard Time', 'America/Bahia'),
                    ('Bangladesh Standard Time', 'Asia/Dhaka'),
                    ('Belarus Standard Time', 'Europe/Minsk'),
                    ('Bougainville Standard Time', 'Pacific/Bougainville'),
                    ('Canada Central Standard Time', 'America/Regina'),
                    ('Cape Verde Standard Time', 'Atlantic/Cape_Verde'),
                    ('Caucasus Standard Time', 'Asia/Yerevan'),
                    ('Cen. Australia Standard Time', 'Australia/Adelaide'),
                    ('Central America Standard Time', 'America/Guatemala'),
                    ('Central Asia Standard Time', 'Asia/Almaty'),
                    ('Central Brazilian Standard Time', 'America/Cuiaba'),
                    ('Central Europe Standard Time', 'Europe/Budapest'),
                    ('Central European Standard Time', 'Europe/Warsaw'),
                    ('Central Pacific Standard Time', 'Pacific/Guadalcanal'),
                    ('Central Standard Time', 'America/Chicago'),
                    ('Central Standard Time (Mexico)', 'America/Mexico_City'),
                    ('Chatham Islands Standard Time', 'Pacific/Chatham'),
                    ('China Standard Time', 'Asia/Shanghai'),
                    ('Cuba Standard Time', 'America/Havana'),
                    ('E. Africa Standard Time', 'Africa/Nairobi'),
                    ('E. Australia Standard Time', 'Australia/Brisbane'),
                    ('E. Europe Standard Time', 'Europe/Chisinau'),
                    ('E. South America Standard Time', 'America/Sao_Paulo'),
                    ('Easter Island Standard Time', 'Pacific/Easter'),
                    ('Eastern Standard Time', 'America/New_York'),
                    ('Eastern Standard Time (Mexico)', 'America/Cancun'),
                    ('Egypt Standard Time', 'Africa/Cairo'),
                    ('Ekaterinburg Standard Time', 'Asia/Yekaterinburg'),
                    ('Fiji Standard Time', 'Pacific/Fiji'),
                    ('FLE Standard Time', 'Europe/Kiev'),
                    ('Georgian Standard Time', 'Asia/Tbilisi'),
                    ('GMT Standard Time', 'Europe/London'),
                    ('Greenland Standard Time', 'America/Godthab'),
                    ('Greenwich Standard Time', 'Atlantic/Reykjavik'),
                    ('GTB Standard Time', 'Europe/Bucharest'),
                    ('Haiti Standard Time', 'America/Port-au-Prince'),
                    ('Hawaiian Standard Time', 'Pacific/Honolulu'),
                    ('India Standard Time', 'Asia/Kolkata'),
                    ('Iran Standard Time', 'Asia/Tehran'),
                    ('Israel Standard Time', 'Asia/Jerusalem'),
                    ('Jordan Standard Time', 'Asia/Amman'),
                    ('Kaliningrad Standard Time', 'Europe/Kaliningrad'),
                    ('Korea Standard Time', 'Asia/Seoul'),
                    ('Libya Standard Time', 'Africa/Tripoli'),
                    ('Line Islands Standard Time', 'Pacific/Kiritimati'),
                    ('Lord Howe Standard Time', 'Australia/Lord_Howe'),
                    ('Magadan Standard Time', 'Asia/Magadan'),
                    ('Magallanes Standard Time', 'America/Punta_Arenas'),
                    ('Marquesas Standard Time', 'Pacific/Marquesas'),
                    ('Mauritius Standard Time', 'Indian/Mauritius'),
                    ('Middle East Standard Time', 'Asia/Beirut'),
                    ('Montevideo Standard Time', 'America/Montevideo'),
                    ('Morocco Standard Time', 'Africa/Casablanca'),
                    ('Mountain Standard Time', 'America/Denver'),
                    ('Mountain Standard Time (Mexico)', 'America/Mazatlan'),
                    ('Myanmar Standard Time', 'Asia/Rangoon'),
                    ('N. Central Asia Standard Time', 'Asia/Novosibirsk'),
                    ('Namibia Standard Time', 'Africa/Windhoek'),
                    ('Nepal Standard Time', 'Asia/Katmandu'),
                    ('New Zealand Standard Time', 'Pacific/Auckland'),
                    ('Newfoundland Standard Time', 'America/St_Johns'),
                    ('Norfolk Standard Time', 'Pacific/Norfolk'),
                    ('North Asia East Standard Time', 'Asia/Irkutsk'),
                    ('North Asia Standard Time', 'Asia/Krasnoyarsk'),
                    ('North Korea Standard Time', 'Asia/Pyongyang'),
                    ('Omsk Standard Time', 'Asia/Omsk'),
                    ('Pacific SA Standard Time', 'America/Santiago'),
                    ('Pacific Standard Time', 'America/Los_Angeles'),
                    ('Pacific Standard Time (Mexico)', 'America/Tijuana'),
                    ('Pakistan Standard Time', 'Asia/Karachi'),
                    ('Paraguay Standard Time', 'America/Asuncion'),
                    ('Qyzylorda Standard Time', 'Asia/Qyzylorda'),
                    ('Romance Standard Time', 'Europe/Paris'),
                    ('Russia Time Zone 10', 'Asia/Srednekolymsk'),
                    ('Russia Time Zone 11', 'Asia/Kamchatka'),
                    ('Russia Time Zone 3', 'Europe/Samara'),
                    ('Russian Standard Time', 'Europe/Moscow'),
                    ('SA Eastern Standard Time', 'America/Cayenne'),
                    ('SA Pacific Standard Time', 'America/Bogota'),
                    ('SA Western Standard Time', 'America/La_Paz'),
                    ('Saint Pierre Standard Time', 'America/Miquelon'),
                    ('Sakhalin Standard Time', 'Asia/Sakhalin'),
                    ('Samoa Standard Time', 'Pacific/Apia'),
                    ('Sao Tome Standard Time', 'Africa/Sao_Tome'),
                    ('Saratov Standard Time', 'Europe/Saratov'),
                    ('SE Asia Standard Time', 'Asia/Bangkok'),
                    ('Singapore Standard Time', 'Asia/Singapore'),
                    ('South Africa Standard Time', 'Africa/Johannesburg'),
                    ('South Sudan Standard Time', 'Africa/Juba'),
                    ('Sri Lanka Standard Time', 'Asia/Colombo'),
                    ('Sudan Standard Time', 'Africa/Khartoum'),
                    ('Syria Standard Time', 'Asia/Damascus'),
                    ('Taipei Standard Time', 'Asia/Taipei'),
                    ('Tasmania Standard Time', 'Australia/Hobart'),
                    ('Tocantins Standard Time', 'America/Araguaina'),
                    ('Tokyo Standard Time', 'Asia/Tokyo'),
                    ('Tomsk Standard Time', 'Asia/Tomsk'),
                    ('Tonga Standard Time', 'Pacific/Tongatapu'),
                    ('Transbaikal Standard Time', 'Asia/Chita'),
                    ('Turkey Standard Time', 'Europe/Istanbul'),
                    ('Turks And Caicos Standard Time', 'America/Grand_Turk'),
                    ('Ulaanbaatar Standard Time', 'Asia/Ulaanbaatar'),
                    ('US Eastern Standard Time', 'America/Indianapolis'),
                    ('US Mountain Standard Time', 'America/Phoenix'),
                    ('UTC', 'UTC'),
                    ('UTC-02', 'Etc/GMT+2'),
                    ('UTC-08', 'Etc/GMT+8'),
                    ('UTC-09', 'Etc/GMT+9'),
                    ('UTC-11', 'Etc/GMT+11'),
                    ('UTC+12', 'Etc/GMT-12'),
                    ('UTC+13', 'Etc/GMT-13'),
                    ('Venezuela Standard Time', 'America/Caracas'),
                    ('Vladivostok Standard Time', 'Asia/Vladivostok'),
                    ('Volgograd Standard Time', 'Europe/Volgograd'),
                    ('W. Australia Standard Time', 'Australia/Perth'),
                    ('W. Central Africa Standard Time', 'Africa/Lagos'),
                    ('W. Europe Standard Time', 'Europe/Berlin'),
                    ('W. Mongolia Standard Time', 'Asia/Hovd'),
                    ('West Asia Standard Time', 'Asia/Tashkent'),
                    ('West Bank Standard Time', 'Asia/Hebron'),
                    ('West Pacific Standard Time', 'Pacific/Port_Moresby'),
                    ('Yakutsk Standard Time', 'Asia/Yakutsk'),
                    ('Yukon Standard Time', 'America/Whitehorse')
                ) AS mapping(windows_id, iana_id)
                WHERE c.time_zone_id = mapping.windows_id;

                DO $$
                DECLARE unknown_zone text;
                BEGIN
                    SELECT c.time_zone_id INTO unknown_zone
                    FROM cameras c
                    WHERE NOT EXISTS (SELECT 1 FROM pg_timezone_names tz WHERE tz.name = c.time_zone_id)
                    LIMIT 1;
                    IF unknown_zone IS NOT NULL THEN
                        RAISE EXCEPTION 'Legacy camera timezone canonicalization is required for: %', unknown_zone;
                    END IF;
                END $$;
                """);

            migrationBuilder.Sql("""
                UPDATE video_assets AS v
                SET recording_time_zone_id = c.time_zone_id,
                    recording_utc_offset_minutes = CAST(EXTRACT(EPOCH FROM
                        ((v.recording_start_utc AT TIME ZONE c.time_zone_id) -
                         (v.recording_start_utc AT TIME ZONE 'UTC'))) / 60 AS integer)
                FROM cameras AS c
                WHERE c.id = v.camera_id;
                """);

            migrationBuilder.AlterColumn<string>(
                name: "recording_time_zone_id",
                table: "video_assets",
                type: "character varying(64)",
                maxLength: 64,
                nullable: false,
                oldClrType: typeof(string),
                oldType: "character varying(64)",
                oldMaxLength: 64,
                oldNullable: true);

            migrationBuilder.AddCheckConstraint(
                name: "ck_video_assets_recording_utc_offset",
                table: "video_assets",
                sql: "recording_utc_offset_minutes BETWEEN -840 AND 840");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_video_assets_recording_utc_offset",
                table: "video_assets");

            migrationBuilder.DropColumn(
                name: "recording_time_zone_id",
                table: "video_assets");

            migrationBuilder.DropColumn(
                name: "recording_utc_offset_minutes",
                table: "video_assets");
        }
    }
}
