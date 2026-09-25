using System.Net;
using System.Text.Json;
using Mavi.Contracts.Api.Processing;
using Mavi.Domain.Processing;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// One premature-visibility probe (F4 plan §9.2 step 6, §15.2): the real read APIs first, then
/// one database snapshot of the job. The job's status is authoritative and monotonic after the
/// hand-off (Finalizing, then a terminal state, never back), so when the snapshot, taken
/// <i>after</i> the API reads, still says Finalizing, every API read happened while the job was
/// Finalizing and must show nothing of the run: the status phase exactly <c>finalizing</c>
/// with no published count, no search hit, no committed Track row, and no Track detail.
/// </summary>
/// <remarks>
/// Track detail is probed with the ids of the graph being published. Ids are assigned in memory
/// at graph build and noted at PublishAsync entry (<see cref="LifecycleCallLog.PendingTracks"/>),
/// so they are real, about to be committed, and unknowable earlier: before graph build no Track
/// id exists anywhere, so no detail read can expose one. <see cref="DetailStatuses"/> is empty
/// until then.
/// </remarks>
internal sealed record VisibilitySnapshot(
    string DbStatus, string ApiPhase, int ApiTracksCreated, int SearchHits, long TrackRows, IReadOnlyList<int> DetailStatuses)
{
    public bool DuringFinalizing => DbStatus == nameof(VisionJobStatus.Finalizing);

    /// <summary>The raw probe as retained, so the checker recomputes every verdict from it.</summary>
    public object ToOutput() => new
    {
        dbStatus = DbStatus,
        apiPhase = ApiPhase,
        apiTracksCreated = ApiTracksCreated,
        searchHits = SearchHits,
        trackRows = TrackRows,
        detailStatuses = DetailStatuses,
    };
}

internal static class VisibilityChecks
{
    public const string WrongPhase = "wrongPhase";
    public const string PublishedCount = "publishedCount";
    public const string Search = "search";
    public const string TrackRows = "trackRows";
    public const string Detail = "detail";
    public static readonly string[] Kinds = [WrongPhase, PublishedCount, Search, TrackRows, Detail];

    /// <summary>Each check a Finalizing snapshot fails; none for a snapshot after publication.</summary>
    public static IReadOnlyList<string> Violations(VisibilitySnapshot snapshot)
    {
        var violations = new List<string>();
        if (!snapshot.DuringFinalizing) return violations;
        if (snapshot.ApiPhase != ProcessingPhases.Finalizing) violations.Add(WrongPhase);
        if (snapshot.ApiTracksCreated != 0) violations.Add(PublishedCount);
        if (snapshot.SearchHits != 0) violations.Add(Search);
        if (snapshot.TrackRows != 0) violations.Add(TrackRows);
        if (snapshot.DetailStatuses.Any(status => status != (int)HttpStatusCode.NotFound)) violations.Add(Detail);
        return violations;
    }

    public static async Task<VisibilitySnapshot> ProbeAsync(
        string connectionString, HttpClient client, Guid videoId, Guid cameraId, Guid jobId, IReadOnlyList<Guid> detailTrackIds)
    {
        using var processing = JsonDocument.Parse(await client.GetStringAsync($"/api/videos/{videoId}/processing"));
        var run = processing.RootElement.GetProperty("latestRun");
        var phase = run.GetProperty("phase").GetString() ?? "";
        var tracksCreated = run.GetProperty("tracksCreated").GetInt32();
        using var search = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks?cameraId={cameraId}"));
        var searchHits = search.RootElement.GetProperty("items").GetArrayLength();
        var detail = new List<int>(detailTrackIds.Count);
        foreach (var trackId in detailTrackIds)
        {
            using var response = await client.GetAsync($"/api/tracks/{trackId}");
            detail.Add((int)response.StatusCode);
        }

        // Taken last: its status bounds every read above.
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT j.status, (SELECT count(*) FROM tracks t WHERE t.processing_run_id = j.processing_run_id) FROM vision_jobs j WHERE j.id = $1", connection);
        command.Parameters.AddWithValue(jobId);
        await using var reader = await command.ExecuteReaderAsync();
        await reader.ReadAsync();
        return new VisibilitySnapshot(reader.GetString(0), phase, tracksCreated, searchHits, reader.GetInt64(1), detail);
    }
}

/// <summary>
/// Which checks ran and what they found, for the retained output: the checker needs every
/// check to have run on every Finalizing snapshot, and Track detail on at least one, before
/// it accepts zero violations as a result.
/// </summary>
internal sealed class VisibilityTally
{
    private readonly Dictionary<string, int> _violations = VisibilityChecks.Kinds.ToDictionary(kind => kind, _ => 0, StringComparer.Ordinal);
    private readonly HashSet<Guid> _detailTrackIds = [];
    private readonly List<VisibilitySnapshot> _snapshots = [];

    public int Probes { get; private set; }
    public int DetailProbes { get; private set; }
    public int Total => _violations.Values.Sum();

    public void Add(VisibilitySnapshot snapshot, IReadOnlyList<Guid> detailTrackIds)
    {
        if (!snapshot.DuringFinalizing) return;
        _snapshots.Add(snapshot);
        Probes++;
        if (snapshot.DetailStatuses.Count > 0)
        {
            DetailProbes++;
            _detailTrackIds.UnionWith(detailTrackIds);
        }

        foreach (var violation in VisibilityChecks.Violations(snapshot)) _violations[violation]++;
    }

    public object ToOutput(IReadOnlyList<int> detailAfterPublication) => new
    {
        // Every Finalizing snapshot runs the phase, count, search and Track-row checks.
        probes = Probes,
        phaseProbes = Probes,
        publishedCountProbes = Probes,
        searchProbes = Probes,
        trackRowProbes = Probes,
        detailProbes = DetailProbes,
        violations = _violations,
        detailTrackIds = _detailTrackIds.Order().ToList(),
        // Every Finalizing probe, raw: the counts above are recomputed from these.
        snapshots = _snapshots.Select(snapshot => snapshot.ToOutput()).ToList(),
        // The same ids after publication: the detail API does expose them now, so the 404s
        // above were the ids of real Tracks withheld, not ids that never existed.
        detailAfterPublication,
    };
}

/// <summary>
/// One atomic snapshot of the two jobs of the §9.2 concurrency check. A single statement reads
/// one MVCC snapshot, so every fact below holds at one instant.
/// </summary>
internal sealed record OverlapSnapshot(
    DateTimeOffset AtUtc,
    string FirstStatus, bool FirstClaimLive, DateTimeOffset? FirstAcceptedAtUtc, long FirstPayloadRows,
    string SecondStatus, bool SecondClaimed, DateTimeOffset? SecondAcceptedAtUtc, long SecondPayloadRows,
    long LiveClaims)
{
    /// <summary>
    /// Real overlap: both hand-offs durable (accepted, payload retained), the first Finalizing
    /// and holding a live claim, the second Finalizing and never claimed.
    /// </summary>
    public bool IsOverlap =>
        FirstStatus == nameof(VisionJobStatus.Finalizing) && FirstClaimLive && FirstAcceptedAtUtc is not null && FirstPayloadRows > 0
        && SecondStatus == nameof(VisionJobStatus.Finalizing) && !SecondClaimed && SecondAcceptedAtUtc is not null && SecondPayloadRows > 0;

    public object ToOutput() => new
    {
        atUtc = AtUtc,
        first = new { status = FirstStatus, claimLive = FirstClaimLive, acceptedAtUtc = FirstAcceptedAtUtc, payloadRows = FirstPayloadRows },
        second = new { status = SecondStatus, claimed = SecondClaimed, acceptedAtUtc = SecondAcceptedAtUtc, payloadRows = SecondPayloadRows },
        liveClaims = LiveClaims,
    };

    /// <summary>
    /// A claim is live when it is canonical and unexpired at <paramref name="nowUtc"/> (the
    /// database clock when null); "claimed" is any claim, or any finalization attempt, ever.
    /// </summary>
    public static async Task<OverlapSnapshot> TakeAsync(string connectionString, Guid first, Guid second, DateTimeOffset? nowUtc = null)
    {
        const string Job = "(SELECT {0} FROM vision_jobs WHERE id = {1})";
        const string Live = "finalization_claim_token_hash IS NOT NULL AND finalization_claim_expires_at_utc > n.now";
        string Of(string expression, string job) => string.Format(System.Globalization.CultureInfo.InvariantCulture, Job, expression, job);
        var sql =
            "WITH n AS (SELECT COALESCE($3::timestamptz, now()) AS now) SELECT n.now, " +
            Of("status", "$1") + ", " + Of("(" + Live + ")", "$1") + ", " + Of("finalization_accepted_at_utc", "$1") + ", " +
            "(SELECT count(*) FROM vision_finalization_payloads WHERE job_id = $1), " +
            Of("status", "$2") + ", " + Of("(finalization_claim_token_hash IS NOT NULL OR finalization_attempt_count > 0)", "$2") + ", " +
            Of("finalization_accepted_at_utc", "$2") + ", " +
            "(SELECT count(*) FROM vision_finalization_payloads WHERE job_id = $2), " +
            "(SELECT count(*) FROM vision_jobs WHERE status = 'Finalizing' AND " + Live + ") FROM n";
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue(first);
        command.Parameters.AddWithValue(second);
        command.Parameters.Add(new NpgsqlParameter { Value = (object?)nowUtc ?? DBNull.Value, NpgsqlDbType = NpgsqlTypes.NpgsqlDbType.TimestampTz });
        await using var reader = await command.ExecuteReaderAsync();
        await reader.ReadAsync();
        DateTimeOffset? At(int ordinal) => reader.IsDBNull(ordinal) ? null : reader.GetFieldValue<DateTimeOffset>(ordinal);
        return new OverlapSnapshot(
            reader.GetFieldValue<DateTimeOffset>(0),
            reader.GetString(1), !reader.IsDBNull(2) && reader.GetBoolean(2), At(3), reader.GetInt64(4),
            reader.GetString(5), !reader.IsDBNull(6) && reader.GetBoolean(6), At(7), reader.GetInt64(8),
            reader.GetInt64(9));
    }
}
