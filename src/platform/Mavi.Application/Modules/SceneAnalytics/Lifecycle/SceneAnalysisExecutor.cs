using System.Security.Cryptography;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Microsoft.Extensions.Logging;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>What one execution of one unit did.</summary>
public sealed record SceneAnalysisExecutionResult(
    Guid AnalysisId,
    bool IsSuccess,
    string? FailureCode,
    int AnalysedTrackCount,
    int UnavailableTrackCount);

/// <summary>
/// Executes one claimed analysis unit: reads its sealed evidence, runs the deterministic
/// engine over every Track, and commits the result.
/// </summary>
/// <remarks>
/// <para>
/// The shape of this class is dictated by one rule: <b>the engine runs outside every
/// transaction.</b> The claim has already committed before execution begins, and the
/// facts go back in a second transaction that revalidates ownership. Nothing here holds a
/// database lock while geometry is being computed.
/// </para>
/// <para>
/// The other rule worth stating is what counts as a failure. <b>A malformed Track never
/// fails a unit.</b> A trajectory that is absent, corrupt or too short is a permanent
/// property of that Track's evidence: retrying would read the same bytes and reach the
/// same conclusion, so the Track gets an <c>Unavailable</c> outcome and the unit carries
/// on. A unit fails only when the whole attempt cannot proceed — an I/O fault, a bug in
/// the engine, a missing revision, or the duration bound.
/// </para>
/// </remarks>
public sealed class SceneAnalysisExecutor(
    ISceneAnalysisLifecycle lifecycle,
    ISceneAnalysisEvidenceReader evidence,
    ISceneConfigurationRepository scenes,
    ILogger<SceneAnalysisExecutor> logger)
{
    // Structured, pre-defined log messages (§AF). The claim token is not among the
    // parameters of any of them, and cannot be: nothing here takes one.
    private static readonly Action<ILogger, Guid, int, int, int, Exception?> LogUnitCompleted =
        LoggerMessage.Define<Guid, int, int, int>(
            LogLevel.Information,
            new EventId(1900, "SceneAnalysisUnitCompleted"),
            "Scene analysis unit {AnalysisId} attempt {Attempt} completed: {AnalysedCount} analysed, {UnavailableCount} unavailable.");

    private static readonly Action<ILogger, Guid, int, string, Exception?> LogUnitFailed =
        LoggerMessage.Define<Guid, int, string>(
            LogLevel.Warning,
            new EventId(1901, "SceneAnalysisUnitFailed"),
            "Scene analysis unit {AnalysisId} attempt {Attempt} failed with {FailureCode}.");

    private static readonly Action<ILogger, Guid, int, Exception?> LogStaleAttempt =
        LoggerMessage.Define<Guid, int>(
            LogLevel.Warning,
            new EventId(1902, "SceneAnalysisAttemptStale"),
            "Scene analysis unit {AnalysisId} rejected a stale completion from attempt {Attempt}.");

    private static readonly Action<ILogger, Guid, Exception?> LogUnitThrew =
        LoggerMessage.Define<Guid>(
            LogLevel.Error,
            new EventId(1903, "SceneAnalysisUnitThrew"),
            "Scene analysis unit {AnalysisId} threw.");

    public async Task<SceneAnalysisExecutionResult> ExecuteAsync(
        SceneAnalysisClaim claim,
        SceneAnalyticsOptions options,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        ArgumentNullException.ThrowIfNull(options);

        // The attempt's own deadline, inside whatever the host is doing. It is deliberately
        // shorter than the lease, so an overrunning attempt is cancelled by its executor
        // rather than left to be reclaimed while still running.
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        bounded.CancelAfter(TimeSpan.FromSeconds(options.MaxUnitDurationSeconds));

        SceneAnalysisFacts facts;
        int analysed;
        int unavailable;
        try
        {
            (facts, analysed, unavailable) = await ComputeAsync(claim, bounded.Token);
        }
        catch (SceneAnalysisUnitFailure failure)
        {
            return await FailAsync(claim, options, failure.Code, failure.Message, cancellationToken);
        }
        catch (OperationCanceledException) when (bounded.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            return await FailAsync(
                claim,
                options,
                SceneAnalyticsErrorCodes.UnitTimeout,
                $"The unit exceeded {options.MaxUnitDurationSeconds} seconds.",
                cancellationToken);
        }
        catch (OperationCanceledException)
        {
            // The host is stopping. Nothing was written and nothing is claimed to have
            // been: the lease expires and the unit is reclaimed in the ordinary way.
            throw;
        }
#pragma warning disable CA1031 // A bug in the engine must fail one attempt, not the host.
        catch (Exception exception)
#pragma warning restore CA1031
        {
            LogUnitThrew(logger, claim.AnalysisId, exception);
            return await FailAsync(
                claim,
                options,
                SceneAnalyticsErrorCodes.EngineFailed,
                exception.GetType().Name,
                cancellationToken);
        }

        // Commit with the host's token, not the bounded one: cancelling a unit that has
        // already computed its facts is worse than letting the short commit finish.
        var commit = await lifecycle.CommitFactsAsync(claim, facts, cancellationToken);
        if (commit.IsSuccess)
        {
            LogUnitCompleted(logger, claim.AnalysisId, claim.AttemptCount, analysed, unavailable, null);
            return new SceneAnalysisExecutionResult(claim.AnalysisId, true, null, analysed, unavailable);
        }

        if (commit.ErrorCode == SceneAnalyticsErrorCodes.AttemptStale)
        {
            // Not an error to retry. This host lost the unit while it was computing, its
            // results are discarded, and whoever holds the unit now will produce them.
            LogStaleAttempt(logger, claim.AnalysisId, claim.AttemptCount, null);
            return new SceneAnalysisExecutionResult(
                claim.AnalysisId, false, SceneAnalyticsErrorCodes.AttemptStale, 0, 0);
        }

        // The lifecycle classified the refusal, so it is reported as it stands rather
        // than relabelled: a unit that vanished is not a persistence failure.
        return await FailAsync(
            claim,
            options,
            commit.ErrorCode ?? SceneAnalyticsErrorCodes.PersistenceFailed,
            null,
            cancellationToken);
    }

    // --- Computation (no transaction is open here) -------------------------

    private async Task<(SceneAnalysisFacts Facts, int Analysed, int Unavailable)> ComputeAsync(
        SceneAnalysisClaim claim,
        CancellationToken cancellationToken)
    {
        var revision = await scenes.GetRevisionAsync(claim.Identity.RevisionId, cancellationToken)
            ?? throw new SceneAnalysisUnitFailure(
                SceneAnalyticsErrorCodes.RevisionMissing,
                "The pinned scene revision no longer exists.");

        var tracks = await evidence.ListRunTracksAsync(claim.Identity.ProcessingRunId, cancellationToken);

        var outcomes = new List<TrackAnalysisOutcome>(tracks.Count);
        var visits = new List<TrackZoneVisit>();
        var summaries = new List<TrackZoneSummary>();
        var crossings = new List<TrackLineCrossing>();
        var motions = new List<TrackMotionSummary>();
        var analysed = 0;
        var unavailable = 0;

        foreach (var track in tracks)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var samples = await ReadSamplesAsync(track, cancellationToken);
            if (samples.Reason is { } reason)
            {
                // Every Track gets a row, including this one. A Track whose evidence could
                // not be used and a Track that simply did nothing are indistinguishable if
                // the unusable one is left out.
                outcomes.Add(TrackAnalysisOutcome.Unavailable(claim.AnalysisId, track.TrackId, reason));
                unavailable++;
                continue;
            }

            var result = SceneAnalysisEngine.Analyse(
                samples.Samples!,
                revision,
                track.ObjectClass,
                SceneAnalyticsParameters.Default);

            outcomes.Add(TrackAnalysisOutcome.Analysed(
                claim.AnalysisId,
                track.TrackId,
                result.ReferencePoint,
                result.SampleCount,
                result.GapCount,
                result.GapTotalMs));
            Project(claim.AnalysisId, track, result, visits, summaries, crossings, motions);
            analysed++;
        }

        return (new SceneAnalysisFacts(outcomes, visits, summaries, crossings, motions), analysed, unavailable);
    }

    /// <summary>
    /// Reads and validates one Track's trajectory, returning either its samples or the
    /// permanent reason it has none.
    /// </summary>
    private async Task<(IReadOnlyList<TrajectorySample>? Samples, string? Reason)> ReadSamplesAsync(
        SceneAnalysisTrackEvidence track,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrEmpty(track.TrajectoryStorageKey))
        {
            return (null, SceneAnalyticsErrorCodes.TrajectoryMissing);
        }

        byte[]? payload;
        try
        {
            payload = await evidence.ReadTrajectoryAsync(track.TrajectoryStorageKey, cancellationToken);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
#pragma warning disable CA1031 // An I/O fault says nothing about the evidence; retry the unit.
        catch (Exception exception)
#pragma warning restore CA1031
        {
            // Deliberately does not name the storage key: a failure code is operator-facing.
            throw new SceneAnalysisUnitFailure(
                SceneAnalyticsErrorCodes.TrajectoryReadFailed,
                exception.GetType().Name);
        }

        if (payload is null)
        {
            return (null, SceneAnalyticsErrorCodes.TrajectoryMissing);
        }

        // The artefact is sealed, so its recorded digest is the authority on its bytes.
        // A mismatch is permanent for this evidence: rereading it cannot change it.
        if (track.TrajectorySha256 is { } expected
            && !string.Equals(Convert.ToHexStringLower(SHA256.HashData(payload)), expected, StringComparison.Ordinal))
        {
            return (null, SceneAnalyticsErrorCodes.TrajectoryIntegrityFailed);
        }

        try
        {
            return (TrajectoryDecoder.Decode(payload), null);
        }
        catch (TrajectoryFormatException exception)
        {
            return (null, exception.Reason);
        }
    }

    // --- Engine output to persisted facts ----------------------------------

    private static void Project(
        Guid analysisId,
        SceneAnalysisTrackEvidence track,
        TrackAnalysisResult result,
        List<TrackZoneVisit> visits,
        List<TrackZoneSummary> summaries,
        List<TrackLineCrossing> crossings,
        List<TrackMotionSummary> motions)
    {
        // Offsets are media-relative; the absolute stamps a search predicate filters on
        // are derived from the video's recording start, never from the host's clock.
        DateTimeOffset At(long offsetMs) => track.RecordingStartUtc.AddMilliseconds(offsetMs);

        foreach (var visit in result.ZoneVisits)
        {
            visits.Add(TrackZoneVisit.Create(
                analysisId,
                track.TrackId,
                visit.ZoneId,
                visit.VisitIndex,
                visit.EntryOffsetMs,
                visit.ExitOffsetMs,
                At(visit.EntryOffsetMs),
                At(visit.ExitOffsetMs),
                visit.DwellMs,
                visit.BeganInside,
                visit.EndedInside,
                visit.ClosedByGap,
                visit.EntryHeading,
                visit.ExitHeading));
        }

        foreach (var summary in result.ZoneSummaries)
        {
            // A zone the Track never entered still gets a row, and must carry no stamps:
            // "never entered" is not the same as "entered at the start of the video".
            var visited = summary.VisitCount > 0;
            summaries.Add(TrackZoneSummary.Create(
                analysisId,
                track.TrackId,
                summary.ZoneId,
                summary.VisitCount,
                summary.TotalDwellMs,
                visited ? At(summary.FirstEntryOffsetMs) : null,
                visited ? At(summary.LastExitOffsetMs) : null,
                summary.Loitering,
                summary.LoiteringThresholdSeconds,
                summary.LoiteringDwellMs));
        }

        foreach (var crossing in result.LineCrossings)
        {
            crossings.Add(TrackLineCrossing.Create(
                analysisId,
                track.TrackId,
                crossing.LineId,
                crossing.CrossingIndex,
                crossing.OffsetMs,
                At(crossing.OffsetMs),
                crossing.Direction,
                crossing.Point.X,
                crossing.Point.Y));
        }

        var motion = result.Motion;
        motions.Add(TrackMotionSummary.Create(
            analysisId,
            track.TrackId,
            motion.Heading,
            motion.PathLengthNormalised,
            motion.MeanDisplacementRateNormalisedPerSecond,
            motion.LongestStationaryMs,
            motion.TotalStationaryMs,
            [.. motion.StationaryIntervals.Select(x => new StationaryInterval(x.StartOffsetMs, x.EndOffsetMs))],
            motion.StationaryZoneIds));
    }

    // --- Failure reporting -------------------------------------------------

    private async Task<SceneAnalysisExecutionResult> FailAsync(
        SceneAnalysisClaim claim,
        SceneAnalyticsOptions options,
        string failureCode,
        string? details,
        CancellationToken cancellationToken)
    {
        LogUnitFailed(logger, claim.AnalysisId, claim.AttemptCount, failureCode, null);

        // A missing revision is permanent, so it must not consume the remaining attempts
        // one at a time before settling where it was always going to settle.
        var attempts = failureCode == SceneAnalyticsErrorCodes.RevisionMissing
            ? claim.AttemptCount
            : options.MaximumAttempts;

        await lifecycle.ReportFailureAsync(claim, failureCode, details, attempts, cancellationToken);
        return new SceneAnalysisExecutionResult(claim.AnalysisId, false, failureCode, 0, 0);
    }

    /// <summary>A fault that fails the whole attempt rather than one Track.</summary>
    private sealed class SceneAnalysisUnitFailure(string code, string message) : Exception(message)
    {
        public string Code { get; } = code;
    }
}
