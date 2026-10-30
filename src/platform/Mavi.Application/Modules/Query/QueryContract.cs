using Mavi.Contracts.Api.Analytics;

namespace Mavi.Application.Modules.Query;

/// <summary>
/// The vocabulary of contract <c>mavi-query-v1</c> (ADR-024): units, predicates, operations, dimensions and bounds.
/// The parser, the evaluator, <c>GET /api/query/contract</c> and the JSON Schema all state the same lists; the golden
/// corpus checks that the parser and the schema agree.
/// </summary>
public static class QueryContract
{
    public const string Version = "mavi-query-v1";

    /// <summary>The Development disclosure every envelope carries (ADR-020 §2).</summary>
    public const string Disclosure = "PoC profile, Development evidence, not Production-qualified.";

    public const int MaximumCameraIds = 64;

    /// <summary>
    /// The largest integer any member takes (2^53 - 1): exactly representable as a JSON number by every reader, the
    /// schema's <c>maximum</c> for the otherwise unbounded durations.
    /// </summary>
    public const long MaximumInteger = 9_007_199_254_740_991;
    public const int DefaultFindLimit = 50;
    public const int MaximumFindLimit = 200;
    public const int MaximumTopK = 50;
    public const int MaximumSimilarK = 50;
    public const int DefaultSimilarK = 20;

    /// <summary>
    /// The largest matching scope a query evaluates. Above it the query is refused, never answered from a truncated
    /// set (ADR-024 §5). A PoC bound, not a performance claim.
    /// </summary>
    public const int MaximumMatchedRecords = 50_000;

    public const int MinimumBucketSeconds = AnalyticsQueryRules.MinimumBucketSeconds;
    public const int MaximumBucketSeconds = AnalyticsQueryRules.MaximumBucketSeconds;
    public const int MaximumBuckets = AnalyticsQueryRules.MaximumBuckets;

    // --- Wire names ----------------------------------------------------------

    public static readonly IReadOnlyList<string> Units = ["track", "event", "entity"];

    public static readonly IReadOnlyList<string> Operations =
        ["find", "count", "countDistinct", "groupBy", "timeBucket", "first", "last", "top", "compare"];

    /// <summary>The predicates each unit allows, by wire name.</summary>
    public static readonly IReadOnlyDictionary<QueryUnit, IReadOnlyList<string>> Predicates =
        new Dictionary<QueryUnit, IReadOnlyList<string>>
        {
            [QueryUnit.Track] =
            [
                "timeWindow", "cameraIds", "objectClass", "objectSubclass", "minDurationMs", "minConfidence",
                "zone", "line", "motion", "attributes", "plateText", "similarTo",
            ],
            [QueryUnit.Event] = ["timeWindow", "cameraIds", "objectClass", "zone", "line", "ruleIds", "catalogueVersion"],
            [QueryUnit.Entity] = ["timeWindow", "cameraIds"],
        };

    /// <summary>The <c>groupBy</c> and <c>top</c> dimensions of each unit.</summary>
    public static readonly IReadOnlyDictionary<QueryUnit, IReadOnlyList<string>> GroupDimensions =
        new Dictionary<QueryUnit, IReadOnlyList<string>>
        {
            [QueryUnit.Track] = ["camera", "objectClass", "objectSubclass"],
            [QueryUnit.Event] = ["camera", "rule", "objectClass", "direction", "zone", "line"],
            [QueryUnit.Entity] = ["camera"],
        };

    /// <summary>The <c>countDistinct</c> fields of each unit.</summary>
    public static readonly IReadOnlyDictionary<QueryUnit, IReadOnlyList<string>> DistinctFields =
        new Dictionary<QueryUnit, IReadOnlyList<string>>
        {
            [QueryUnit.Track] = ["camera", "objectClass", "video"],
            [QueryUnit.Event] = ["camera", "track", "rule"],
            [QueryUnit.Entity] = ["camera"],
        };

    public static readonly IReadOnlyList<string> ObjectClasses = ["Person", "Vehicle"];
    public static readonly IReadOnlyList<string> ZoneRelations = ["entered", "exited", "dwelled"];
    public static readonly IReadOnlyList<string> CrossingDirections = ["aToB", "bToA"];
    public static readonly IReadOnlyList<string> PlateMatches = ["contains", "prefix", "exact"];
    public static readonly IReadOnlyList<string> Orders = ["newest", "oldest"];

    public static string ToWire(QueryUnit unit) => unit switch
    {
        QueryUnit.Track => "track",
        QueryUnit.Event => "event",
        QueryUnit.Entity => "entity",
        _ => throw new ArgumentOutOfRangeException(nameof(unit)),
    };

    public static string ToWire(QueryOperationKind kind) => kind switch
    {
        QueryOperationKind.Find => "find",
        QueryOperationKind.Count => "count",
        QueryOperationKind.CountDistinct => "countDistinct",
        QueryOperationKind.GroupBy => "groupBy",
        QueryOperationKind.TimeBucket => "timeBucket",
        QueryOperationKind.First => "first",
        QueryOperationKind.Last => "last",
        QueryOperationKind.Top => "top",
        QueryOperationKind.Compare => "compare",
        _ => throw new ArgumentOutOfRangeException(nameof(kind)),
    };

    public static string ToWire(QueryOrder order) => order == QueryOrder.Newest ? "newest" : "oldest";

    /// <summary>Whether an operation asserts something about the whole scope, and is withheld on incomplete coverage.</summary>
    public static bool IsWholeScope(QueryOperationKind kind) => kind != QueryOperationKind.Find;
}
