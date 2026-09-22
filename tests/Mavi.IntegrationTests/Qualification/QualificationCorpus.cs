using System.Globalization;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>The shape of a generated corpus, recorded so a run is reproducible.</summary>
public sealed record CorpusManifest(
    int Seed,
    Guid CameraId,
    Guid RevisionId,
    int RevisionNumber,
    string AlgorithmVersion,
    IReadOnlyList<Guid> ZoneIds,
    IReadOnlyList<Guid> LineIds,
    IReadOnlyList<Guid> RunIds,
    DateTimeOffset WindowFromUtc,
    DateTimeOffset WindowToUtc,
    int VideoCount,
    int RunCount,
    int TrackCount,
    int ZoneVisitCount,
    int LineCrossingCount,
    int ZoneSummaryCount,
    int MotionSummaryCount,
    int OutcomeCount,
    string? EvidenceRoot = null,
    string? MediaRoot = null,
    bool UnitsCompleted = true)
{
    /// <summary>The fact total the parent plan's 10^5 requirement is measured against.</summary>
    public int RelevantFactCount =>
        ZoneVisitCount + LineCrossingCount + ZoneSummaryCount + MotionSummaryCount + OutcomeCount;
}

/// <summary>
/// The C3 heavy synthetic corpus, and the C2 representative one, built from a
/// deterministic seed.
/// </summary>
/// <remarks>
/// Every row goes through the real domain factory and the real DbContext, so
/// domain invariants and the database's own foreign keys, uniqueness and check
/// constraints all apply. Nothing here writes a benchmark-only row that the
/// product could not have produced: runs are completed and given a visibility
/// sequence exactly as the pipeline does, units are committed against a real
/// scene revision with a real algorithm version, and facts hang off those units.
/// A corpus that bypassed those rules would measure a query the product never
/// runs.
///
/// Determinism is a plain linear congruential sequence rather than
/// <see cref="Random"/>, whose implementation is explicitly not guaranteed to be
/// stable across runtimes; the same seed has to produce the same corpus on the
/// Development machine as it does here.
/// </remarks>
public sealed class QualificationCorpus(PostgresFixture fixture)
{
    public const string AlgorithmVersion = "scene-analytics-v1";

    public static readonly string ParametersSha256 = new('c', 64);

    private ulong _state;

    private int Next(int maxExclusive)
    {
        // Numerical Recipes LCG constants; stable everywhere, which is the point.
        _state = unchecked((_state * 1664525) + 1013904223);

        // Masked to 31 bits before the cast. Without it the cast wraps negative for
        // half of all states and the modulus follows it, which produced offsets the
        // domain correctly refused — a corpus bug the domain caught rather than a
        // domain bug, and exactly why the corpus is built through the real factories.
        return (int)((_state >> 16) & 0x7FFFFFFF) % maxExclusive;
    }

    private double NextUnit() => Next(1_000_000) / 1_000_000.0;

    /// <summary>
    /// Builds a corpus with the requested shape and returns its manifest.
    /// </summary>
    /// <param name="seed">Deterministic seed; the same seed rebuilds the same corpus.</param>
    /// <param name="videoCount">Videos, each with one completed visible run.</param>
    /// <param name="tracksPerRun">Tracks per run.</param>
    /// <param name="zoneCount">Enabled zones in the revision.</param>
    /// <param name="lineCount">Enabled trip lines in the revision.</param>
    /// <param name="visitsPerTrack">Zone visits generated per Track.</param>
    /// <param name="crossingsPerTrack">Line crossings generated per Track.</param>
    /// <param name="sealTrajectories">
    /// Seals a real v1 trajectory artefact per Track, on disk and recorded, so the
    /// harnesses that read evidence — the executor and the heatmap — have something
    /// to read. Off by default because the query harnesses never open one.
    /// </param>
    /// <param name="completeUnits">
    /// False leaves each analytical unit Queued with no facts, which is the state the
    /// executor is measured from. True completes it and writes the generated facts,
    /// which is the state the read side is measured from.
    /// </param>
    public async Task<CorpusManifest> BuildAsync(
        int seed,
        int videoCount,
        int tracksPerRun,
        int zoneCount,
        int lineCount,
        int visitsPerTrack,
        int crossingsPerTrack,
        bool sealTrajectories = false,
        bool completeUnits = true,
        CancellationToken cancellationToken = default)
    {
        _state = (ulong)seed;

        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync(cancellationToken);

        var windowFrom = new DateTimeOffset(2026, 9, 1, 0, 0, 0, TimeSpan.Zero);

        var evidenceRoot = sealTrajectories ? CreateRoot("evidence") : null;
        var mediaRoot = sealTrajectories ? CreateRoot("media") : null;

        var camera = Camera.Create("CAM-QUAL-01", "Qualification Camera", "UTC");
        var configuration = SceneConfiguration.Create(camera.Id, windowFrom.AddDays(-1));
        var draft = QualificationScene.Draft(zoneCount, lineCount);
        var revision = configuration.SaveRevision(
            null, draft, null, SceneRules.UnattributedDevelopmentActor, windowFrom.AddDays(-1));

        db.Add(camera);
        db.Add(configuration);
        db.Add(revision);
        await db.SaveChangesAsync(cancellationToken);

        var zoneIds = revision.Zones.Select(zone => zone.ZoneId).ToList();
        var lineIds = revision.TripLines.Select(line => line.LineId).ToList();

        var runIds = new List<Guid>(videoCount);
        var trackCount = 0;
        var visitCount = 0;
        var crossingCount = 0;
        var summaryCount = 0;
        var motionCount = 0;
        var outcomeCount = 0;

        for (var videoIndex = 0; videoIndex < videoCount; videoIndex++)
        {
            // One transaction per video, holding the completion barrier across the
            // sequence allocations inside it — the shape the pipeline publishes under.
            await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);

            // One video per hour, so a window sweep selects a predictable number of runs.
            var recordingStart = windowFrom.AddHours(videoIndex);
            var completedAt = recordingStart.AddMinutes(30);

            // A distinct digest per source video: the schema enforces uniqueness on
            // it, exactly as it does for real imports, so a shared constant would
            // make the corpus unbuildable past the first video.
            var sourceDigest = videoIndex.ToString("x8", CultureInfo.InvariantCulture).PadLeft(64, 'a');
            var source = Artifact.Create(
                ArtifactType.SourceVideo,
                $"source/CAM-QUAL-01/{videoIndex:D5}.mp4",
                "video/mp4",
                1,
                sourceDigest);
            var video = VideoAsset.Create(
                camera.Id, source.Id, $"qual-{videoIndex:D5}.mp4", recordingStart,
                600_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1.0);
            var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", recordingStart);
            run.MarkRunning("qualification-worker", recordingStart.AddMinutes(1));
            run.MarkCompleted(tracksPerRun * 10, tracksPerRun, 600_000, completedAt);
            // From the database's own sequence, never a local counter. A reader takes
            // its snapshot from the same sequence and admits only rows at or below it,
            // so counter-issued values are not comparable with a snapshot: a corpus
            // numbered 1..n locally is almost entirely invisible to the first reader
            // that runs, and the harness measures an empty database very quickly.
            run.AssignCompletionVisibilitySequence(
                await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken));
            var job = VisionJob.Create(run.Id, "phase1-detection-tracking", recordingStart);

            db.AddRange(source, video, run, job);
            runIds.Add(run.Id);

            // The analytical unit for this run, committed against the real revision.
            // Driven through the real lifecycle, claim token and all, so the unit
            // reaches Completed the way the executor takes it there rather than by
            // having its columns written directly.
            SceneAnalysis? analysis = null;
            if (completeUnits)
            {
                analysis = SceneAnalysis.Queue(
                    run.Id, revision.Id, AlgorithmVersion, ParametersSha256, null, completedAt);
                var claimToken = new byte[SceneAnalysis.ClaimTokenByteLength];
                for (var i = 0; i < claimToken.Length; i++) claimToken[i] = (byte)Next(256);
                analysis.Claim(
                    System.Security.Cryptography.SHA256.HashData(claimToken),
                    completedAt,
                    TimeSpan.FromMinutes(15),
                    maximumAttempts: 3,
                    reclaimGrace: TimeSpan.FromMinutes(1));
                var unitSequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
                analysis.Complete(
                    analysis.AttemptCount,
                    claimToken,
                    unitSequence,
                    analysedTrackCount: tracksPerRun,
                    unavailableTrackCount: 0,
                    completedAt.AddSeconds(30));
                db.Add(analysis);
            }

            var tracks = new List<Track>(tracksPerRun);
            for (var trackIndex = 0; trackIndex < tracksPerRun; trackIndex++)
            {
                var startOffset = Next(500_000);
                var track = Track.Create(
                    run.Id, video.Id, trackIndex + 1,
                    trackIndex % 3 == 0 ? ObjectClass.Vehicle : ObjectClass.Person,
                    startOffset, startOffset + 20_000,
                    recordingStart,
                    detectionCount: 12, meanConfidence: 0.7, maxConfidence: 0.9,
                    createdAtUtc: completedAt);
                tracks.Add(track);
            }

            db.AddRange(tracks);

            foreach (var track in tracks)
            {
                if (analysis is null)
                {
                    // No unit, so no facts: the executor is about to derive them, and a
                    // corpus that pre-wrote them would measure a run with nothing to do.
                    continue;
                }

                db.Add(TrackAnalysisOutcome.Analysed(analysis.Id, track.Id, "bbox-centre", 120, 1, 400));
                outcomeCount++;

                // The longest stationary run cannot exceed the total; drawing the two
                // independently produced summaries the domain rightly refused.
                var totalStationaryMs = (long)Next(30_000);
                var longestStationaryMs = totalStationaryMs == 0 ? 0L : Next((int)totalStationaryMs + 1);
                db.Add(TrackMotionSummary.Create(
                    analysis.Id, track.Id,
                    QualificationScene.Headings[Next(QualificationScene.Headings.Length)],
                    0.4, 0.01,
                    longestStationaryMs,
                    totalStationaryMs,
                    stationaryIntervals: [],
                    stationaryZoneIds: []));
                motionCount++;

                for (var visit = 0; visit < visitsPerTrack && zoneIds.Count > 0; visit++)
                {
                    var zoneId = zoneIds[Next(zoneIds.Count)];
                    var entryOffset = track.StartOffsetMs + (visit * 2_000L);
                    var exitOffset = entryOffset + 1_000 + Next(4_000);
                    db.Add(TrackZoneVisit.Create(
                        analysis.Id, track.Id, zoneId, visit,
                        entryOffset, exitOffset,
                        recordingStart.AddMilliseconds(entryOffset),
                        recordingStart.AddMilliseconds(exitOffset),
                        exitOffset - entryOffset,
                        beganInside: visit == 0 && Next(4) == 0,
                        endedInside: Next(5) == 0,
                        closedByGap: false,
                        entryHeading: "NE",
                        exitHeading: "SW"));
                    visitCount++;
                }

                foreach (var zoneId in zoneIds)
                {
                    var visits = 1 + Next(3);
                    var dwell = 1_000L + Next(60_000);
                    db.Add(TrackZoneSummary.Create(
                        analysis.Id, track.Id, zoneId, visits, dwell,
                        recordingStart.AddMilliseconds(track.StartOffsetMs),
                        recordingStart.AddMilliseconds(track.EndOffsetMs),
                        loitering: dwell > 30_000,
                        loiteringThresholdSeconds: 30,
                        loiteringDwellMs: dwell));
                    summaryCount++;
                }

                for (var crossing = 0; crossing < crossingsPerTrack && lineIds.Count > 0; crossing++)
                {
                    var lineId = lineIds[Next(lineIds.Count)];
                    var offset = track.StartOffsetMs + 500 + (crossing * 3_000L);
                    db.Add(TrackLineCrossing.Create(
                        analysis.Id, track.Id, lineId, crossing, offset,
                        recordingStart.AddMilliseconds(offset),
                        Next(2) == 0 ? "AToB" : "BToA",
                        NextUnit(), NextUnit()));
                    crossingCount++;
                }
            }

            trackCount += tracks.Count;

            if (evidenceRoot is not null)
            {
                await SealTrajectoriesAsync(db, evidenceRoot, run.Id, tracks, cancellationToken);
            }

            // Saved per video to keep the change tracker bounded; a single
            // SaveChanges over 10^5 rows is where this would otherwise fall over.
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
        }

        if (completeUnits)
        {
            // The corpus is only a measurement subject if a reader can see it. This is
            // the assertion the harness lacked when its visibility sequences came from
            // a local counter: everything built, nothing measurable.
            await using var check = await db.Database.BeginTransactionAsync(cancellationToken);
            await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
            var snapshot = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            var visibleRuns = await db.ProcessingRuns
                .CountAsync(run => run.VisibilitySequence != null && run.VisibilitySequence <= snapshot, cancellationToken);
            if (visibleRuns != videoCount)
            {
                throw new InvalidOperationException(
                    $"The corpus is not visible to a reader's snapshot: {visibleRuns} of {videoCount} runs are at or below it.");
            }
        }

        return new CorpusManifest(
            seed, camera.Id, revision.Id, revision.RevisionNumber, AlgorithmVersion,
            zoneIds, lineIds, runIds,
            windowFrom, windowFrom.AddHours(videoCount),
            videoCount, videoCount, trackCount,
            visitCount, crossingCount, summaryCount, motionCount, outcomeCount,
            evidenceRoot, mediaRoot, completeUnits);
    }

    /// <summary>
    /// Seals one real v1 trajectory artefact per Track: written to disk under the
    /// evidence root, recorded with its true digest, and attached to the Track.
    /// </summary>
    /// <remarks>
    /// The path and the digest are the product's, not the harness's, because the
    /// evidence reader verifies both. A fixture that recorded a digest it had not
    /// computed would measure the failure path instead of the read path.
    /// </remarks>
    private async Task SealTrajectoriesAsync(
        MaviDbContext db,
        string evidenceRoot,
        Guid runId,
        List<Track> tracks,
        CancellationToken cancellationToken)
    {
        var artifacts = new List<Artifact>(tracks.Count);
        var attachments = new List<(Guid TrackId, Guid ArtifactId)>(tracks.Count);

        foreach (var track in tracks)
        {
            // A short diagonal walk, varied by the seed so no two Tracks share bytes.
            var originX = 0.05 + (NextUnit() * 0.4);
            var originY = 0.05 + (NextUnit() * 0.4);
            var payload = TrajectoryPayload.Encode(Enumerable.Range(0, 24).Select(step => (
                (long)step * 200,
                Math.Round(Math.Min(originX + (step * 0.02), 0.99), 6),
                Math.Round(Math.Min(originY + (step * 0.015), 0.99), 6))));

            var storageKey =
                $"evidence/{runId:D}/attempt-0001/trajectories/track-{track.LocalTrackNumber:D6}.msgpack";
            var path = Path.Combine(
                evidenceRoot,
                storageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            await File.WriteAllBytesAsync(path, payload, cancellationToken);

            var artifact = Artifact.Create(
                ArtifactType.TrackTrajectory,
                storageKey,
                "application/x-msgpack",
                payload.Length,
                TrajectoryPayload.Sha256Hex(payload));
            artifacts.Add(artifact);
            attachments.Add((track.Id, artifact.Id));
        }

        db.AddRange(artifacts);
        await db.SaveChangesAsync(cancellationToken);

        foreach (var (trackId, artifactId) in attachments)
        {
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE tracks SET trajectory_artifact_id = {artifactId} WHERE id = {trackId}",
                cancellationToken);
        }
    }

    private static string CreateRoot(string kind)
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-qualification-{kind}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }
}
