using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Events;
using Mavi.Domain.Scene;
using Microsoft.Extensions.Logging;

namespace Mavi.Application.Modules.Events;

/// <summary>
/// The Events surface (ADR-025): the derivation sweep the host drives, and the
/// read-only catalogue, timeline and detail projections.
/// </summary>
public sealed class AnalyticEventService(
    IAnalyticEventRepository repository,
    TimeProvider timeProvider,
    ILogger<AnalyticEventService> logger)
{
    private static readonly Action<ILogger, Guid, string, Exception?> LogUnitFailed =
        LoggerMessage.Define<Guid, string>(
            LogLevel.Error,
            new EventId(1963, "AnalyticEventsUnitFailed"),
            "Analytic events could not be derived for analysis unit {SceneAnalysisId} ({CatalogueVersion}); the sweep continues with the next unit.");

    /// <summary>
    /// Derives up to <paramref name="batchSize"/> units that have no derivation at the
    /// current catalogue version, each in its own transaction. Returns how many were derived.
    /// </summary>
    /// <remarks>
    /// The budget counts derivations, not attempts, and the sweep pages past a unit that
    /// failed: units that fail every time are retried each cycle, but they never hold the
    /// units behind them back.
    /// </remarks>
    public async Task<int> DeriveDueAsync(int batchSize, CancellationToken cancellationToken)
    {
        var catalogue = RuleCatalogue.Current;
        var derived = 0;
        EventDerivationCandidate? after = null;
        while (derived < batchSize)
        {
            var page = await repository.ListUnitsAwaitingDerivationAsync(catalogue.CatalogueVersion, after, batchSize - derived, cancellationToken);
            if (page.Count == 0)
                break;

            foreach (var candidate in page)
            {
                after = candidate;
                if (await TryDeriveAsync(candidate.SceneAnalysisId, catalogue, cancellationToken))
                    derived++;
            }
        }

        return derived;
    }

    private async Task<bool> TryDeriveAsync(Guid unitId, RuleCatalogueDefinition catalogue, CancellationToken cancellationToken)
    {
        try
        {
            return await repository.DeriveAsync(unitId, catalogue, timeProvider.GetUtcNow(), cancellationToken)
                == EventDerivationOutcome.Derived;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
#pragma warning disable CA1031 // One unit that cannot be derived must not starve every unit behind it.
        catch (Exception exception)
#pragma warning restore CA1031
        {
            // Its runs stay "events not derived yet" in coverage, which is the operator-facing truth.
            LogUnitFailed(logger, unitId, catalogue.CatalogueVersion, exception);
            return false;
        }
    }

    public static RuleCatalogueResponse Catalogue(RuleCatalogueDefinition catalogue) => new(
        catalogue.CatalogueVersion,
        catalogue.Sha256,
        [.. catalogue.Rules.Select(rule => new RuleDefinitionResponse(
            rule.RuleId,
            rule.RuleVersion,
            rule.Title,
            rule.Description,
            rule.Enabled,
            rule.DisabledReason,
            [.. rule.Parameters.Select(parameter => new RuleParameterResponse(
                parameter.Name, parameter.Value, parameter.Unit, parameter.Source, parameter.Reference))]))]);

    public async Task<AnalyticEventTimelineResponse?> TimelineAsync(
        AnalyticEventTimelineQuery query,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        var catalogue = RuleCatalogue.Current;
        var result = await repository.ReadTimelineAsync(query, catalogue, cancellationToken);
        if (!result.Found)
            return null;

        var identity = result.Identity!;
        var buckets = AnalyticsBuckets.Build(query.FromUtc, query.ToUtc, query.BucketSeconds);
        var zoneNames = result.Zones.ToDictionary(zone => zone.ZoneId, zone => zone.Name);
        var lines = result.Lines.ToDictionary(line => line.LineId);

        // A count is only ever reported for a rule that ran over at least one derived run.
        // A rule filtered out, disabled, or not yet derived anywhere has no count rather
        // than a zero: a zero would claim an observed absence (ADR-025 §5).
        var counted = result.DerivedRuns == 0
            ? []
            : catalogue.Rules
                .Where(rule => rule.Enabled && (query.RuleIds is null || query.RuleIds.Contains(rule.RuleId)))
                .Select(rule => rule.RuleId)
                .ToList();
        var crossingCounts = !counted.Contains(EventRuleIds.LineCrossing)
            ? []
            : result.Lines
            .OrderBy(line => line.Name, StringComparer.Ordinal)
            .Select(line =>
            {
                var aToB = new int[buckets.Count];
                var bToA = new int[buckets.Count];
                foreach (var crossing in result.Crossings.Where(crossing => crossing.LineId == line.LineId))
                {
                    var index = AnalyticsBuckets.IndexOf(crossing.AtUtc, query.FromUtc, query.BucketSeconds, buckets.Count);
                    if (index < 0)
                        continue;
                    if (crossing.AToB) aToB[index]++;
                    else bToA[index]++;
                }

                return new AnalyticEventCrossingCountsResponse(line.LineId, line.Name, line.AToBLabel, line.BToALabel, aToB, bToA);
            })
            .ToList();

        return new AnalyticEventTimelineResponse(
            identity.CameraId,
            identity.SceneRevisionId,
            identity.SceneRevisionNumber,
            identity.AlgorithmVersion,
            result.CatalogueVersion,
            identity.SnapshotVisibilitySequence,
            query.FromUtc,
            query.ToUtc,
            query.BucketSeconds,
            new AnalyticEventCoverageResponse(ToCoverage(result.Coverage!), result.DerivedRuns, result.EventsPendingRuns),
            [.. buckets.Select(bucket => new AnalyticsBucketResponse(bucket.StartUtc, bucket.EndUtc))],
            [.. counted.Select(ruleId => new AnalyticEventRuleCountResponse(
                ruleId, result.RuleCounts.TryGetValue(ruleId, out var count) ? count : 0))],
            crossingCounts,
            [.. result.Events.Select(row => Summary(row, zoneNames, lines))],
            query.Limit,
            result.Truncated);
    }

    public async Task<AnalyticEventDetailResponse?> DetailAsync(Guid eventId, CancellationToken cancellationToken)
    {
        var view = await repository.GetEventAsync(eventId, cancellationToken);
        if (view is null)
            return null;

        var zoneNames = view.Event.ZoneId is { } zoneId && view.ZoneName is { } zoneName
            ? new Dictionary<Guid, string> { [zoneId] = zoneName }
            : [];
        var lines = view.Line is { } line
            ? new Dictionary<Guid, EventGeometryLine> { [line.LineId] = line }
            : [];
        var provenance = view.Provenance;
        return new AnalyticEventDetailResponse(
            Summary(view.Event, zoneNames, lines),
            view.CameraId,
            view.SceneAnalysisId,
            view.SceneRevisionId,
            view.SceneRevisionNumber,
            view.AnalyticsAlgorithmVersion,
            view.CatalogueVersion,
            view.CatalogueSha256,
            view.InputSha256,
            view.DerivedAtUtc,
            [.. view.Participants.Select(participant => new AnalyticEventParticipantResponse(
                participant.TrackId,
                participant.Role,
                participant.ObjectClass,
                participant.VideoAssetId,
                participant.StartOffsetMs,
                participant.EndOffsetMs,
                participant.ThumbnailArtifactId is { } thumbnail ? $"/api/artifacts/{thumbnail:D}/content" : null))],
            [.. provenance.Inputs.Select(input => new AnalyticEventInputResponse(input.Kind, input.Reference, input.StartOffsetMs, input.EndOffsetMs))],
            [.. provenance.Parameters.Select(parameter => new AnalyticEventParameterResponse(
                parameter.Name, parameter.Value, parameter.Unit, parameter.Source, parameter.Reference))],
            [.. provenance.Details.Select(detail => new AnalyticEventDetailValueResponse(detail.Name, detail.Value))]);
    }

    private static AnalyticEventSummaryResponse Summary(
        AnalyticEventRow row,
        Dictionary<Guid, string> zoneNames,
        Dictionary<Guid, EventGeometryLine> lines)
    {
        EventGeometryLine? line = null;
        if (row.LineId is { } lineId)
            lines.TryGetValue(lineId, out line);
        string? directionLabel = null;
        if (line is not null && row.Direction is { } direction)
            directionLabel = direction == TripLine.PermittedDirectionAToB ? line.AToBLabel : line.BToALabel;

        return new AnalyticEventSummaryResponse(
            row.EventId,
            row.RuleId,
            row.RuleVersion,
            row.StartUtc,
            row.EndUtc,
            row.StartOffsetMs,
            row.EndOffsetMs,
            row.VideoAssetId,
            row.ProcessingRunId,
            row.PrimaryTrackId,
            row.ObjectClass,
            row.ZoneId,
            row.ZoneId is { } zoneId && zoneNames.TryGetValue(zoneId, out var name) ? name : null,
            row.LineId,
            line?.Name,
            row.Direction,
            directionLabel,
            row.ParticipantCount);
    }

    private static AnalyticsCoverageResponse ToCoverage(TrackAnalyticsCoverage coverage) => new(
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
