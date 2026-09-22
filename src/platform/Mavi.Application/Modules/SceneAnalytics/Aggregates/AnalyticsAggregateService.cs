using System.Security.Cryptography;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Contracts.Api.Analytics;
using Microsoft.Extensions.Logging;

namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

/// <summary>
/// The read-only Slice-6 analytics service: aggregates and heatmaps over persisted
/// facts and sealed evidence for one resolved analytical identity.
/// </summary>
/// <remarks>
/// The service owns the order of operations, not the counting. Identity, coverage and
/// the bounded dimensions come from the repository under one visibility snapshot; the
/// arithmetic is the pure aggregator; and the heatmap's two work bounds are enforced
/// here, between the cheap scope resolution and the first artefact open, so the guard
/// never depends on the I/O it bounds (plan §5.5).
/// </remarks>
public sealed class AnalyticsAggregateService(
    IAnalyticsAggregateRepository repository,
    IHeatmapEvidenceReader evidence,
    ILogger<AnalyticsAggregateService> logger)
{
    // Structured, pre-defined messages. Every parameter is a bounded dimension, an
    // identifier or a duration: nothing here can carry evidence content, because
    // nothing here takes any (plan §15).
    private static readonly Action<ILogger, Guid, int, int, int, int, int, Exception?> LogAggregateResolved =
        LoggerMessage.Define<Guid, int, int, int, int, int>(
            LogLevel.Information,
            new EventId(1930, "SceneAnalyticsAggregateResolved"),
            "Scene analytics aggregate for camera {CameraId}: {BucketCount} buckets, {ZoneCount} zones, {LineCount} lines, {EvaluatedRuns} evaluated runs, {DurationMs}ms.");

    private static readonly Action<ILogger, Guid, int, int, int, long, int, Exception?> LogHeatmapResolved =
        LoggerMessage.Define<Guid, int, int, int, long, int>(
            LogLevel.Information,
            new EventId(1931, "SceneAnalyticsHeatmapResolved"),
            "Scene analytics heatmap for camera {CameraId}: {CoveredRuns} covered runs, {CandidateTracks} candidate Tracks, {ContributingTracks} contributing, {SampleCount} samples, {DurationMs}ms.");

    private static readonly Action<ILogger, Guid, string, int, int, Exception?> LogHeatmapRefused =
        LoggerMessage.Define<Guid, string, int, int>(
            LogLevel.Information,
            new EventId(1932, "SceneAnalyticsHeatmapScopeTooLarge"),
            "Scene analytics heatmap for camera {CameraId} refused before evidence access: {Dimension} {Actual} exceeds {Limit}.");

    private static readonly Action<ILogger, Guid, Exception?> LogTrajectoryMissing =
        LoggerMessage.Define<Guid>(
            LogLevel.Error,
            new EventId(1933, "SceneAnalyticsHeatmapEvidenceMissing"),
            "Scene analytics heatmap: trajectory evidence is missing for analysed Track {TrackId}.");

    private static readonly Action<ILogger, Guid, string, Exception?> LogTrajectoryUnreadable =
        LoggerMessage.Define<Guid, string>(
            LogLevel.Error,
            new EventId(1934, "SceneAnalyticsHeatmapEvidenceUnreadable"),
            "Scene analytics heatmap: trajectory evidence for analysed Track {TrackId} is not readable ({Reason}).");

    public async Task<AnalyticsAggregateResponse?> AggregateAsync(
        AnalyticsAggregateQuery query,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);

        var started = TimeProvider.System.GetTimestamp();
        var result = await repository.AggregateAsync(query, cancellationToken);
        if (!result.IsSuccess)
        {
            return null;
        }

        var identity = result.Identity!;
        var series = AnalyticsAggregator.Compute(
            result.Facts ?? AnalyticsFactSet.Empty,
            query.FromUtc,
            query.ToUtc,
            query.BucketSeconds);

        // Bounded dimensions and duration only: Slice 7 measures from these, and no
        // evidence content is ever written to a log.
        LogAggregateResolved(
            logger,
            query.CameraId,
            series.Buckets.Count,
            series.Zones.Count,
            series.Lines.Count,
            result.Coverage?.EvaluatedRuns ?? 0,
            (int)TimeProvider.System.GetElapsedTime(started).TotalMilliseconds,
            null);

        return new AnalyticsAggregateResponse(
            identity.CameraId,
            identity.SceneRevisionId,
            identity.SceneRevisionNumber,
            identity.AlgorithmVersion,
            identity.SnapshotVisibilitySequence,
            query.FromUtc,
            query.ToUtc,
            query.BucketSeconds,
            query.ObjectClass?.ToString(),
            ToCoverage(result.Coverage!),
            series.Buckets.Select(bucket => new AnalyticsBucketResponse(bucket.StartUtc, bucket.EndUtc)).ToList(),
            series.Zones.Select(zone => new AnalyticsZoneSeriesResponse(
                zone.ZoneId,
                zone.Name,
                zone.EntryCounts,
                zone.ExitCounts,
                zone.UniqueTrackCounts,
                zone.OccupancyAtStart,
                zone.PeakOccupancy,
                zone.PeakOccupancyAtUtc,
                zone.WindowEntryCount,
                zone.WindowExitCount,
                zone.WindowUniqueTrackCount,
                zone.RepeatedVisitTrackCount)).ToList(),
            series.Lines.Select(line => new AnalyticsLineSeriesResponse(
                line.LineId,
                line.Name,
                line.AToBLabel,
                line.BToALabel,
                line.AToBCounts,
                line.BToACounts,
                line.WindowAToBCount,
                line.WindowBToACount)).ToList(),
            series.Classes.Select(series => new AnalyticsClassSeriesResponse(
                series.ObjectClass.ToString(),
                series.Counts,
                series.WindowDistinctTrackCount)).ToList());
    }

    public async Task<AnalyticsHeatmapResult> HeatmapAsync(
        AnalyticsHeatmapQuery query,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);

        var started = TimeProvider.System.GetTimestamp();

        // Step one: everything cheap. Identity, coverage and both bounded dimensions,
        // under one visibility snapshot, with no evidence touched.
        var scope = await repository.ResolveHeatmapScopeAsync(query, cancellationToken);
        if (!scope.IsSuccess)
        {
            return new AnalyticsHeatmapResult(scope.Failure);
        }

        // Step two: the guards. Both are refusals to start work, so they come before
        // the candidate listing and long before the first artefact open.
        if (scope.CoveredRunCount > AnalyticsQueryRules.MaximumHeatmapRuns)
        {
            return TooLarge(
                scope,
                AnalyticsQueryRules.RunsDimension,
                AnalyticsQueryRules.MaximumHeatmapRuns,
                scope.CoveredRunCount,
                query);
        }

        if (scope.CandidateTrackCount > AnalyticsQueryRules.MaximumHeatmapTracks)
        {
            return TooLarge(
                scope,
                AnalyticsQueryRules.TracksDimension,
                AnalyticsQueryRules.MaximumHeatmapTracks,
                scope.CandidateTrackCount,
                query);
        }

        var identity = scope.Identity!;
        var candidates = await repository.ListHeatmapCandidatesAsync(query, identity, cancellationToken);

        var grid = new HeatmapGrid(query.GridWidth, AnalyticsQueryRules.GridHeightFor(query.GridWidth));
        var contributing = 0;

        // Step three: one artefact at a time. Sequential by design — the whole point
        // of the bounds above is that this loop is finite and never holds more than
        // one payload at once.
        foreach (var candidate in candidates)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (candidate.StorageKey is not { } storageKey)
            {
                // The artefact row the Track pointed at is gone, and the foreign key
                // was nulled with it. The unit still says this Track was analysed, so
                // this is the same integrity failure as evidence that will not open.
                LogTrajectoryMissing(logger, candidate.TrackId, null);
                return new AnalyticsHeatmapResult(AnalyticsFailure.EvidenceUnreadable);
            }

            var payload = await evidence.ReadTrajectoryAsync(storageKey, cancellationToken);
            if (payload is null)
            {
                // The analytical unit said this Track was analysed, so its trajectory
                // existed when the facts were produced. Missing evidence now is an
                // integrity failure, not a reason to draw a sparser map and call it
                // the answer.
                LogTrajectoryMissing(logger, candidate.TrackId, null);
                return new AnalyticsHeatmapResult(AnalyticsFailure.EvidenceUnreadable);
            }

            // The artefact is sealed, so its recorded digest is the authority on its
            // bytes — the same rule the executor applies when it produces the facts.
            // Bytes that decode cleanly but hash differently are not this Track's
            // evidence, and a map drawn from them would carry a provenance it does
            // not have.
            if (candidate.Sha256 is { } expected
                && !string.Equals(
                    Convert.ToHexStringLower(SHA256.HashData(payload)),
                    expected,
                    StringComparison.Ordinal))
            {
                LogTrajectoryUnreadable(logger, candidate.TrackId, "trajectory_integrity_failed", null);
                return new AnalyticsHeatmapResult(AnalyticsFailure.EvidenceUnreadable);
            }

            IReadOnlyList<TrajectorySample> samples;
            try
            {
                samples = TrajectoryDecoder.Decode(payload);
            }
            catch (TrajectoryFormatException exception)
            {
                LogTrajectoryUnreadable(logger, candidate.TrackId, exception.Reason, null);
                return new AnalyticsHeatmapResult(AnalyticsFailure.EvidenceUnreadable);
            }

            var contributed = false;
            foreach (var sample in samples)
            {
                // The absolute instant, from the immutable source recording start. A
                // Track may overlap the window while these samples do not: only the
                // samples inside it contribute, which is why this is filtered per
                // sample rather than per Track.
                var at = candidate.RecordingStartUtc + TimeSpan.FromMilliseconds(sample.OffsetMs);
                if (at < query.FromUtc || at >= query.ToUtc)
                {
                    continue;
                }

                try
                {
                    grid.Add(sample.Position.X, sample.Position.Y);
                }
                catch (HeatmapEvidenceException exception)
                {
                    LogTrajectoryUnreadable(logger, candidate.TrackId, "sample_out_of_contract", null);
                    _ = exception;
                    return new AnalyticsHeatmapResult(AnalyticsFailure.EvidenceUnreadable);
                }

                contributed = true;
            }

            if (contributed)
            {
                contributing++;
            }
        }

        LogHeatmapResolved(
            logger,
            query.CameraId,
            scope.CoveredRunCount,
            scope.CandidateTrackCount,
            contributing,
            grid.SampleCount,
            (int)TimeProvider.System.GetElapsedTime(started).TotalMilliseconds,
            null);

        return new AnalyticsHeatmapResult(
            AnalyticsFailure.None,
            identity,
            scope.Coverage,
            grid,
            contributing);
    }

    /// <summary>Maps a successful heatmap result onto the wire contract.</summary>
    public static AnalyticsHeatmapResponse ToResponse(AnalyticsHeatmapQuery query, AnalyticsHeatmapResult result)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(result);

        var identity = result.Identity!;
        var grid = result.Grid!;
        return new AnalyticsHeatmapResponse(
            identity.CameraId,
            identity.SceneRevisionId,
            identity.SceneRevisionNumber,
            identity.AlgorithmVersion,
            identity.SnapshotVisibilitySequence,
            query.FromUtc,
            query.ToUtc,
            query.ObjectClass?.ToString(),
            query.ProcessingRunId,
            ToCoverage(result.Coverage!),
            grid.Width,
            grid.Height,
            grid.SampleCount,
            result.TrackCount,
            grid.MaxCellValue,
            grid.Values);
    }

    private AnalyticsHeatmapResult TooLarge(
        AnalyticsHeatmapScope scope,
        string dimension,
        int limit,
        int actual,
        AnalyticsHeatmapQuery query)
    {
        LogHeatmapRefused(logger, query.CameraId, dimension, actual, limit, null);
        return new AnalyticsHeatmapResult(
            AnalyticsFailure.ScopeTooLarge,
            scope.Identity,
            scope.Coverage,
            ExceededDimension: dimension,
            ExceededLimit: limit);
    }

    private static AnalyticsCoverageResponse ToCoverage(Modules.Intelligence.TrackAnalyticsCoverage coverage) =>
        new(
            coverage.SceneRevisionId,
            coverage.AlgorithmVersion,
            coverage.EvaluatedRuns,
            coverage.PendingRuns,
            coverage.FailedRuns,
            coverage.NotConfiguredRuns,
            coverage.DisabledRuns,
            coverage.StaleRuns,
            coverage.AnalysedTracks,
            coverage.UnavailableTracks);
}
