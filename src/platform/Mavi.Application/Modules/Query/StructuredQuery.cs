using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Query;

/// <summary>The unit a structured query counts (ADR-024 §3).</summary>
public enum QueryUnit
{
    Track,
    Event,
    Entity,
}

/// <summary>The closed set of operations (ADR-024 §4).</summary>
public enum QueryOperationKind
{
    Find,
    Count,
    CountDistinct,
    GroupBy,
    TimeBucket,
    First,
    Last,
    Top,
    Compare,
}

public enum QueryOrder
{
    Newest,
    Oldest,
}

/// <summary>A half-open UTC window, <c>[FromUtc, ToUtc)</c>.</summary>
public sealed record QueryWindow(DateTimeOffset FromUtc, DateTimeOffset ToUtc);

/// <summary>
/// A zone predicate. On the Track unit every member applies; on the Event unit only <see cref="ZoneId"/>
/// (the parser refuses the rest).
/// </summary>
public sealed record QueryZonePredicate(Guid ZoneId, TrackZoneRelation? Relation, long? MinDwellMs, bool Loitering);

/// <summary>A trip-line predicate, on either unit.</summary>
public sealed record QueryLinePredicate(Guid LineId, TrackCrossingDirection? Direction);

/// <summary>A motion predicate (Track unit only): heading and longest stationary interval.</summary>
public sealed record QueryMotionPredicate(string? Direction, long? MinStationaryMs);

/// <summary>Ranked similarity candidates of one Track (S4, ADR-021); <c>find</c> only, alone.</summary>
public sealed record QuerySimilarity(Guid TrackId, int K);

/// <summary>
/// Every predicate a query may carry, already checked against its unit. Members a unit does not allow are null
/// (or empty) by construction: the parser refuses them rather than ignoring them.
/// </summary>
public sealed record QueryPredicates(
    QueryWindow Window,
    IReadOnlyList<Guid> CameraIds,
    ObjectClass? ObjectClass,
    string? ObjectSubclass,
    long? MinDurationMs,
    double? MinConfidence,
    QueryZonePredicate? Zone,
    QueryLinePredicate? Line,
    QueryMotionPredicate? Motion,
    TrackAttributeQuery? Attributes,
    TrackPlateQuery? Plate,
    QuerySimilarity? SimilarTo,
    IReadOnlyList<string> RuleIds,
    string? CatalogueVersion)
{
    /// <summary>Whether a predicate needs a scene revision, and therefore exactly one camera (ADR-024 §2).</summary>
    public bool IsGeometric => Zone is not null || Line is not null || Motion is not null;
}

/// <summary>
/// The operation and its parameters. Only the members its <see cref="Kind"/> takes are set; the canonical form makes
/// every default explicit.
/// </summary>
public sealed record QueryOperation(
    QueryOperationKind Kind,
    int? Limit = null,
    QueryOrder? Order = null,
    string? Field = null,
    string? By = null,
    int? BucketSeconds = null,
    int? K = null,
    QueryWindow? Baseline = null);

/// <summary>One validated, canonical structured query (contract <see cref="QueryContract.Version"/>).</summary>
public sealed record StructuredQuery(
    QueryUnit Unit,
    QueryPredicates Where,
    QueryOperation Operation,
    bool RequireCompleteCoverage);

/// <summary>Why a query was refused: a closed code, a JSON pointer to the member, and a message.</summary>
public sealed record QueryRefusal(string Code, string Path, string Message);

/// <summary>The closed list of refusal codes (ADR-024 §7). S10 reads these; they never change meaning.</summary>
public static class QueryRefusalCodes
{
    public const string MalformedJson = "malformed_json";
    public const string UnknownMember = "unknown_member";
    public const string DuplicateMember = "duplicate_member";
    public const string MissingRequired = "missing_required";
    public const string InvalidValue = "invalid_value";
    public const string UnsupportedVersion = "unsupported_version";
    public const string UnsupportedUnit = "unsupported_unit";
    public const string UnsupportedOperation = "unsupported_operation";
    public const string PredicateNotAllowedForUnit = "predicate_not_allowed_for_unit";
    public const string OperationNotAllowed = "operation_not_allowed";
    public const string ParameterNotAllowed = "parameter_not_allowed";
    public const string DimensionNotAllowed = "dimension_not_allowed";
    public const string GeometryRequiresSingleCamera = "geometry_requires_single_camera";
    public const string SimilarityCombinationUnsupported = "similarity_combination_unsupported";
    public const string AttributeCombinationInvalid = "attribute_combination_invalid";
    public const string TooManyBuckets = "too_many_buckets";
    public const string UnknownReference = "unknown_reference";
    public const string CapabilityNotConfigured = "capability_not_configured";
    public const string QueryScopeTooLarge = "query_scope_too_large";
    public const string CoverageIncomplete = "coverage_incomplete";

    public static readonly IReadOnlyList<string> All =
    [
        MalformedJson, UnknownMember, DuplicateMember, MissingRequired, InvalidValue, UnsupportedVersion, UnsupportedUnit,
        UnsupportedOperation, PredicateNotAllowedForUnit, OperationNotAllowed, ParameterNotAllowed, DimensionNotAllowed,
        GeometryRequiresSingleCamera, SimilarityCombinationUnsupported, AttributeCombinationInvalid, TooManyBuckets,
        UnknownReference, CapabilityNotConfigured, QueryScopeTooLarge, CoverageIncomplete,
    ];
}
