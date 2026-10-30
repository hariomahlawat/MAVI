using Mavi.Contracts.Api.Query;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Query;

/// <summary>One matching Track, as the repository projects it.</summary>
public sealed record QueryTrackRecord(
    Guid TrackId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    Guid VideoAssetId,
    Guid ProcessingRunId,
    ObjectClass ObjectClass,
    string? ObjectSubclass,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    long StartOffsetMs,
    long DurationMs,
    double MeanConfidence,
    Guid? ThumbnailArtifactId,
    double? SimilarityScore = null);

/// <summary>One matching analytic event, as the repository projects it.</summary>
public sealed record QueryEventRecord(
    Guid EventId,
    string RuleId,
    int RuleVersion,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    Guid VideoAssetId,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    string? ZoneName,
    Guid? LineId,
    string? LineName,
    string? Direction,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    long StartOffsetMs);

/// <summary>One in-scope member Track of an Entity, as the repository projects it.</summary>
public sealed record QueryEntityMember(Guid TrackId, Guid CameraId, string CameraCode, string CameraName, DateTimeOffset StartUtc, DateTimeOffset EndUtc);

/// <summary>One operator-confirmed Entity with its in-scope member Tracks (at least one).</summary>
public sealed record QueryEntityRecord(Guid EntityId, string DisplayCode, EntityType EntityType, IReadOnlyList<QueryEntityMember> Members);

/// <summary>
/// The pure evaluation of an operation over matching records (ADR-024 §4–§5): no I/O, no clock, total orderings
/// everywhere, so one record set gives one answer. The repository decides membership; this decides arithmetic.
/// </summary>
public static class StructuredQueryEvaluator
{
    /// <summary>
    /// Evaluates an operation over Track records. <paramref name="baseline"/> is the baseline window's records,
    /// for <c>compare</c> only.
    /// </summary>
    public static QueryResultResponse EvaluateTracks(
        QueryOperation operation,
        QueryWindow window,
        IReadOnlyList<QueryTrackRecord> records,
        IReadOnlyList<QueryTrackRecord>? baseline = null)
    {
        ArgumentNullException.ThrowIfNull(operation);
        ArgumentNullException.ThrowIfNull(records);
        var items = records.Select(record => new Item<QueryTrackRecord>(
            record.TrackId, Anchor(record.StartUtc, window), record)).ToList();
        return Evaluate(operation, window, items, TrackKey, rows => new QueryResultResponse(
            "rows", Tracks: [.. rows.Select(TrackRow)]), baseline?.Count);
    }

    public static QueryResultResponse EvaluateEvents(
        QueryOperation operation,
        QueryWindow window,
        IReadOnlyList<QueryEventRecord> records,
        IReadOnlyList<QueryEventRecord>? baseline = null)
    {
        ArgumentNullException.ThrowIfNull(operation);
        ArgumentNullException.ThrowIfNull(records);
        var items = records.Select(record => new Item<QueryEventRecord>(
            record.EventId, Anchor(record.StartUtc, window), record)).ToList();
        return Evaluate(operation, window, items, EventKey, rows => new QueryResultResponse(
            "rows", Events: [.. rows.Select(EventRow)]), baseline?.Count);
    }

    /// <summary>
    /// Evaluates an operation over confirmed Entities (ADR-023 §9). An Entity's anchor is the first instant of its
    /// earliest in-scope member inside the window, so buckets still partition the count. <c>groupBy</c>, <c>top</c>
    /// and <c>countDistinct</c> by camera count an Entity once per camera where it has an in-scope member.
    /// </summary>
    public static QueryResultResponse EvaluateEntities(
        QueryOperation operation,
        QueryWindow window,
        IReadOnlyList<QueryEntityRecord> records,
        IReadOnlyList<QueryEntityRecord>? baseline = null)
    {
        ArgumentNullException.ThrowIfNull(operation);
        ArgumentNullException.ThrowIfNull(records);
        if (operation.Kind is QueryOperationKind.GroupBy or QueryOperationKind.Top or QueryOperationKind.CountDistinct)
        {
            var perCamera = records
                .SelectMany(record => record.Members
                    .GroupBy(member => member.CameraId)
                    .Select(group => new Item<QueryEntityMember>(record.EntityId, Anchor(group.Min(member => member.StartUtc), window),
                        group.First())))
                .ToList();
            return Evaluate(operation, window, perCamera, EntityCameraKey, _ => throw new InvalidOperationException("No rows for a group."),
                baseline?.Count);
        }

        var items = records.Select(record => new Item<QueryEntityRecord>(
            record.EntityId, Anchor(record.Members.Min(member => member.StartUtc), window), record)).ToList();
        return Evaluate(operation, window, items, (_, dimension) => throw new ArgumentOutOfRangeException(nameof(dimension)),
            rows => new QueryResultResponse("rows", Entities: [.. rows.Select(EntityRow)]), baseline?.Count);
    }

    /// <summary>
    /// Ranked similarity candidates (S4): already ordered by score with their own tie-break, so they are kept in the
    /// service's order and only bounded here.
    /// </summary>
    public static QueryResultResponse RankedTracks(IReadOnlyList<QueryTrackRecord> ranked, int limit)
    {
        ArgumentNullException.ThrowIfNull(ranked);
        var rows = ranked.Take(limit).Select(TrackRow).ToList();
        return new QueryResultResponse(
            "rows",
            Tracks: rows,
            Truncation: new QueryTruncationResponse(ranked.Count > limit, rows.Count, ranked.Count, limit));
    }

    /// <summary>The first instant of a record inside the window: what it is bucketed and ordered by.</summary>
    public static DateTimeOffset Anchor(DateTimeOffset startUtc, QueryWindow window) =>
        startUtc < window.FromUtc ? window.FromUtc : startUtc;

    private sealed record Item<T>(Guid Id, DateTimeOffset Anchor, T Record);

    private static QueryResultResponse Evaluate<T>(
        QueryOperation operation,
        QueryWindow window,
        List<Item<T>> items,
        Func<T, string, (string? Key, string Label)> key,
        Func<IEnumerable<T>, QueryResultResponse> rows,
        int? baselineCount)
    {
        switch (operation.Kind)
        {
            case QueryOperationKind.Find:
            {
                var limit = operation.Limit ?? QueryContract.DefaultFindLimit;
                var ordered = Order(items, operation.Order ?? QueryOrder.Newest).ToList();
                var result = rows(ordered.Take(limit).Select(item => item.Record));
                return result with
                {
                    Truncation = new QueryTruncationResponse(ordered.Count > limit, Math.Min(limit, ordered.Count), ordered.Count, limit),
                };
            }

            case QueryOperationKind.First:
            case QueryOperationKind.Last:
            {
                var order = operation.Kind == QueryOperationKind.First ? QueryOrder.Oldest : QueryOrder.Newest;
                var extreme = Order(items, order).Take(1).Select(item => item.Record);
                var result = rows(extreme);
                return result with { Truncation = new QueryTruncationResponse(items.Count > 1, Math.Min(1, items.Count), items.Count, 1) };
            }

            case QueryOperationKind.Count:
                return new QueryResultResponse("value", Value: items.Count);

            case QueryOperationKind.CountDistinct:
            {
                var field = operation.Field!;
                var distinct = items.Select(item => key(item.Record, field).Key).Where(value => value is not null).Distinct(StringComparer.Ordinal).Count();
                return new QueryResultResponse("value", Value: distinct, Dimension: field);
            }

            case QueryOperationKind.GroupBy:
            {
                var groups = Groups(items, key, operation.By!)
                    .OrderBy(group => group.Key is null)
                    .ThenBy(group => group.Key, StringComparer.Ordinal)
                    .ToList();
                return new QueryResultResponse("groups", Dimension: operation.By, Groups: groups);
            }

            case QueryOperationKind.Top:
            {
                var groups = Groups(items, key, operation.By!)
                    .OrderByDescending(group => group.Count)
                    .ThenBy(group => group.Key is null)
                    .ThenBy(group => group.Key, StringComparer.Ordinal)
                    .Take(operation.K ?? 5)
                    .ToList();
                return new QueryResultResponse("groups", Dimension: operation.By, Groups: groups);
            }

            case QueryOperationKind.TimeBucket:
                return Buckets(window, operation.BucketSeconds!.Value, items.Select(item => item.Anchor));

            case QueryOperationKind.Compare:
            {
                var baseline = baselineCount ?? throw new ArgumentException("compare needs the baseline records.", nameof(baselineCount));
                return new QueryResultResponse(
                    "comparison",
                    Comparison: new QueryComparisonResponse(items.Count, baseline, items.Count - (long)baseline));
            }

            default:
                throw new ArgumentOutOfRangeException(nameof(operation), operation.Kind, "Unknown operation.");
        }
    }

    private static IEnumerable<Item<T>> Order<T>(IEnumerable<Item<T>> items, QueryOrder order) =>
        order == QueryOrder.Newest
            ? items.OrderByDescending(item => item.Anchor).ThenByDescending(item => item.Id)
            : items.OrderBy(item => item.Anchor).ThenBy(item => item.Id);

    private static IEnumerable<QueryGroupResponse> Groups<T>(
        IEnumerable<Item<T>> items,
        Func<T, string, (string? Key, string Label)> key,
        string dimension) =>
        items
            .Select(item => key(item.Record, dimension))
            .GroupBy(pair => pair.Key ?? "\0none", StringComparer.Ordinal)
            .Select(group =>
            {
                var first = group.First();
                // One label per key: the ordinal-least, so two spellings of one camera cannot flip between runs.
                var label = group.Select(pair => pair.Label).Min(StringComparer.Ordinal)!;
                return new QueryGroupResponse(first.Key, label, group.LongCount());
            });

    /// <summary>Buckets aligned to the window start, half-open, the last one short when the window is (Stage 3's rule).</summary>
    private static QueryResultResponse Buckets(QueryWindow window, int bucketSeconds, IEnumerable<DateTimeOffset> anchors)
    {
        var size = TimeSpan.FromSeconds(bucketSeconds);
        var count = (int)Contracts.Api.Analytics.AnalyticsQueryRules.BucketCount(window.FromUtc, window.ToUtc, bucketSeconds);
        var counts = new long[count];
        foreach (var anchor in anchors)
        {
            var index = (int)((anchor - window.FromUtc).Ticks / size.Ticks);
            if (index >= 0 && index < count)
                counts[index]++;
        }

        var buckets = new List<QueryBucketResponse>(count);
        for (var index = 0; index < count; index++)
        {
            var start = window.FromUtc + (size * index);
            var end = start + size > window.ToUtc ? window.ToUtc : start + size;
            buckets.Add(new QueryBucketResponse(start, end, counts[index]));
        }

        return new QueryResultResponse("buckets", BucketSeconds: bucketSeconds, Buckets: buckets);
    }

    // --- Dimensions ----------------------------------------------------------

    private static (string? Key, string Label) TrackKey(QueryTrackRecord record, string dimension) => dimension switch
    {
        "camera" => (record.CameraId.ToString("D"), $"{record.CameraCode} · {record.CameraName}"),
        "objectClass" => (record.ObjectClass.ToString(), record.ObjectClass.ToString()),
        "objectSubclass" => (record.ObjectSubclass, record.ObjectSubclass ?? "No exposed subclass"),
        "video" => (record.VideoAssetId.ToString("D"), record.VideoAssetId.ToString("D")),
        _ => throw new ArgumentOutOfRangeException(nameof(dimension), dimension, "Not a Track dimension."),
    };

    private static (string? Key, string Label) EventKey(QueryEventRecord record, string dimension) => dimension switch
    {
        "camera" => (record.CameraId.ToString("D"), $"{record.CameraCode} · {record.CameraName}"),
        "rule" => (record.RuleId, record.RuleId),
        "objectClass" => (record.ObjectClass, record.ObjectClass ?? "No single class"),
        "direction" => (record.Direction, record.Direction switch
        {
            "AToB" => "A → B",
            "BToA" => "B → A",
            null => "No direction",
            var other => other,
        }),
        "zone" => (record.ZoneId?.ToString("D"), record.ZoneName ?? (record.ZoneId is null ? "No zone" : record.ZoneId.Value.ToString("D"))),
        "line" => (record.LineId?.ToString("D"), record.LineName ?? (record.LineId is null ? "No line" : record.LineId.Value.ToString("D"))),
        "track" => (record.PrimaryTrackId?.ToString("D"), record.PrimaryTrackId?.ToString("D") ?? "No primary Track"),
        _ => throw new ArgumentOutOfRangeException(nameof(dimension), dimension, "Not an Event dimension."),
    };

    private static (string? Key, string Label) EntityCameraKey(QueryEntityMember member, string dimension) => dimension switch
    {
        "camera" => (member.CameraId.ToString("D"), $"{member.CameraCode} · {member.CameraName}"),
        _ => throw new ArgumentOutOfRangeException(nameof(dimension), dimension, "Not an Entity dimension."),
    };

    public static QueryEntityRowResponse EntityRow(QueryEntityRecord record) => new(
        record.EntityId,
        record.DisplayCode,
        record.EntityType.ToString(),
        record.Members.Min(member => member.StartUtc),
        record.Members.Max(member => member.EndUtc),
        [.. record.Members.Select(member => member.CameraId).Distinct().Order()],
        [.. record.Members.Select(member => member.TrackId).Order()]);

    public static QueryTrackRowResponse TrackRow(QueryTrackRecord record) => new(
        record.TrackId,
        record.CameraId,
        record.CameraCode,
        record.CameraName,
        record.VideoAssetId,
        record.ProcessingRunId,
        record.ObjectClass.ToString(),
        record.ObjectSubclass,
        record.StartUtc,
        record.EndUtc,
        record.StartOffsetMs,
        record.DurationMs,
        record.MeanConfidence,
        record.ThumbnailArtifactId,
        record.SimilarityScore);

    public static QueryEventRowResponse EventRow(QueryEventRecord record) => new(
        record.EventId,
        record.RuleId,
        record.RuleVersion,
        record.CameraId,
        record.CameraCode,
        record.CameraName,
        record.VideoAssetId,
        record.PrimaryTrackId,
        record.ObjectClass,
        record.ZoneId,
        record.ZoneName,
        record.LineId,
        record.LineName,
        record.Direction,
        record.StartUtc,
        record.EndUtc,
        record.StartOffsetMs);
}
