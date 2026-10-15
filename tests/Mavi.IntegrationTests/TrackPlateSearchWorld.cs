using System.Security.Cryptography;
using Mavi.Application.Modules.Plates;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>One plate of a seeded Track: its source crop, detector score and ranked raw readings.</summary>
/// <remarks>No reading makes the plate <c>Unreadable</c>; otherwise readings are given in rank order.</remarks>
internal sealed record SeedPlate(Guid SourceObservationId, double DetectorConfidence, params (string Raw, double Confidence)[] Readings);

/// <summary>A Track's facts in one seeded analysis: an outcome and its plates.</summary>
internal sealed record SeedPlateTrack(Guid TrackId, IReadOnlyList<SeedPlate> Plates, string? UnavailableReason = null)
{
    public static SeedPlateTrack Analysed(Guid trackId, params SeedPlate[] plates) => new(trackId, plates);

    public static SeedPlateTrack Unavailable(Guid trackId, string reason) => new(trackId, [], reason);
}

/// <summary>
/// Publishes plate analyses straight into the database, with facts derived exactly as PR-3's completion
/// derives them (the platform's normalisation; Track texts are the distinct normalised rank-0 texts of Read
/// plates with their support, best confidence and best plate). Search tests need deterministic facts, not
/// the worker plane, which PR-3's own tests cover end to end.
/// </summary>
internal static class TrackPlateSearchWorld
{
    private static readonly PlateLeasePolicy Policy = new(TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 3, TimeSpan.FromHours(1));

    /// <summary>The identity A fields the configured test host prefers (vector <c>plate-identity-v1.json</c>).</summary>
    public static PlateIdentityFields IdentityA(IPlateRelease release) => release.Resolution.Definition!.IdentityFields;

    /// <summary>An obsolete identity: identity A with another OCR pack and fingerprint.</summary>
    public static PlateIdentityFields Obsolete(PlateIdentityFields preferred) => preferred with
    {
        Fingerprint = new string('b', 64),
        CapabilitiesCanonical = preferred.CapabilitiesCanonical.Replace(new string('3', 64), new string('5', 64), StringComparison.Ordinal),
    };

    /// <summary>Publishes a fact-bearing analysis with the next visibility sequence; returns its id.</summary>
    public static async Task<Guid> PublishAsync(
        Func<MaviDbContext> createContext,
        DateTimeOffset nowUtc,
        Guid runId,
        PlateIdentityFields identity,
        IReadOnlyList<SeedPlateTrack> tracks,
        bool preferred = true)
    {
        await using var db = createContext();
        var artifact = Artifact.Create(ArtifactType.PlatePredictions,
            $"evidence/plates/{Guid.NewGuid():D}/predictions-{new string('f', 64)}.json", "application/json", 10, new string('f', 64));
        var unit = PlateAnalysis.Queue(runId, identity, nowUtc);
        unit.Claim("plates-01", SHA256.HashData(new byte[32]), nowUtc, Policy);

        var entities = new List<object>();
        var read = 0;
        var unreadable = 0;
        foreach (var track in tracks)
        {
            if (track.UnavailableReason is { } reason)
            {
                entities.Add(PlateTrackOutcome.Unavailable(unit.Id, track.TrackId, reason));
                continue;
            }

            var plates = new List<PlateObservation>();
            foreach (var (seed, index) in track.Plates.Select((plate, index) => (plate, index)))
            {
                var readings = seed.Readings
                    .Select((reading, rank) =>
                    {
                        var normalised = PlateNormalisation.Normalise(reading.Raw);
                        return new PlateReadingValues(
                            rank,
                            reading.Raw,
                            1 + reading.Raw.Count(character => character == '\n'),
                            reading.Confidence,
                            normalised.Normalised,
                            normalised.Outcome == PlateNormalisation.Ok ? PlateNormalisationOutcome.Ok : PlateNormalisationOutcome.Rejected,
                            normalised.Reason,
                            normalised.FormatClass);
                    })
                    .ToList();
                var outcome = readings.Count == 0 ? PlateObservationOutcome.Unreadable : PlateObservationOutcome.Read;
                if (outcome == PlateObservationOutcome.Read) read++;
                else unreadable++;
                // Several plates of one Track come from distinct crops; the index keeps a repeated crop unique.
                plates.Add(PlateObservation.Create(unit.Id, track.TrackId, seed.SourceObservationId, index % 8,
                    10 + index, 20, 100, 30, 412, 330, seed.DetectorConfidence, outcome, readings));
            }

            var texts = plates
                .Where(plate => plate.Outcome == PlateObservationOutcome.Read && plate.Readings[0].NormalisedText is not null)
                .GroupBy(plate => plate.Readings[0].NormalisedText!)
                .Select(group =>
                {
                    var best = group.OrderByDescending(plate => plate.Readings[0].Confidence).ThenBy(plate => plate.Id).First();
                    return PlateTrackText.Create(unit.Id, track.TrackId, group.Key, group.Count(), best.Readings[0].Confidence, best.Id);
                })
                .ToList();
            entities.Add(PlateTrackOutcome.Analysed(unit.Id, track.TrackId, plates.Count, texts.Count));
            entities.AddRange(plates);
            entities.AddRange(texts);
        }

        var sequence = await NextSequenceAsync(db);
        unit.Complete("plates-01", true, 1, nowUtc,
            new PlateCompletion(new string('e', 64), sequence, artifact.Id, "{}",
                tracks.Count(track => track.UnavailableReason is null), tracks.Count(track => track.UnavailableReason is not null), read, unreadable),
            isPreferred: preferred);
        db.AddRange(artifact, unit);
        await db.SaveChangesAsync();
        db.AddRange(entities.Where(entity => entity is PlateTrackOutcome));
        await db.SaveChangesAsync();
        db.AddRange(entities.Where(entity => entity is not PlateTrackOutcome));
        await db.SaveChangesAsync();
        return unit.Id;
    }

    /// <summary>A queued (or, with <paramref name="failed"/>, failed) analysis that has published nothing.</summary>
    public static async Task<Guid> QueueAsync(Func<MaviDbContext> createContext, DateTimeOffset nowUtc, Guid runId, PlateIdentityFields identity,
        bool failed = false)
    {
        await using var db = createContext();
        var unit = PlateAnalysis.Queue(runId, identity, nowUtc);
        db.Add(unit);
        await db.SaveChangesAsync();
        if (failed)
        {
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE plate_analyses SET status = 'Failed', failure_code = 'plate_attempts_exhausted', completed_at_utc = {nowUtc} WHERE id = {unit.Id}");
        }

        return unit.Id;
    }

    /// <summary>A newer preferred completion moved currency: the old analysis keeps its facts.</summary>
    public static async Task SupersedeAsync(Func<MaviDbContext> createContext, Guid analysisId)
    {
        await using var db = createContext();
        await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE plate_analyses SET status = 'Superseded' WHERE id = {analysisId}");
    }

    /// <summary>
    /// Points every seeded Track at its rank-0 Observation, as a real completion does, so the Track detail
    /// (whose Evidence Set read refuses a missing Representative pointer) can be read.
    /// </summary>
    public static async Task AttachRepresentativesAsync(Func<MaviDbContext> createContext, SeededRun run)
    {
        await using var db = createContext();
        foreach (var track in run.Tracks.Where(track => track.Observations.Count > 0))
        {
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE tracks SET representative_observation_id = {track.Observations[0].ObservationId} WHERE id = {track.TrackId}");
        }
    }

    public static async Task<long> NextSequenceAsync(MaviDbContext db)
    {
        var connection = db.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open) await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT nextval('processing_visibility_sequence')";
        return Convert.ToInt64(await command.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }
}
