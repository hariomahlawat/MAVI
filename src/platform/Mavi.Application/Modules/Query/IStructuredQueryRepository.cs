using Mavi.Contracts.Api.Query;

namespace Mavi.Application.Modules.Query;

/// <summary>A window to read, named as the envelope's coverage names it (<c>query</c> or <c>baseline</c>).</summary>
public sealed record QueryReadWindow(string Name, QueryWindow Window);

/// <summary>The identities a derived predicate is evaluated against, resolved by the service from the releases.</summary>
public sealed record QueryCapabilityIdentities(
    string? AttributeFingerprint,
    string? AttributeDisclosure,
    string? PlateFingerprint);

/// <summary>Records and coverage for one window.</summary>
public sealed record QueryWindowRead<T>(IReadOnlyList<T> Records, IReadOnlyList<QueryCoverageComponentResponse> Coverage);

/// <summary>
/// One read of one query, in one snapshot. <paramref name="Refusal"/> is set when a reference does not resolve inside
/// the snapshot (an unknown camera, geometry outside the resolved revision) or the matching scope is larger than the
/// contract evaluates; nothing else is then set.
/// </summary>
public sealed record QueryRead<T>(
    QueryRefusal? Refusal,
    long SnapshotVisibilitySequence,
    IReadOnlyList<QueryCameraIdentityResponse> Cameras,
    IReadOnlyList<QueryWindowRead<T>> Windows);

public static class QueryRead
{
    public static QueryRead<T> Refused<T>(QueryRefusal refusal) => new(refusal, 0, [], []);
}

/// <summary>
/// The structured-query read side (ADR-024 §5). Each call is one read transaction: the shared processing-visibility
/// barrier first, one snapshot sequence, then scope, identity, coverage and the matching records through the same
/// implementations Track search, the Stage 3 aggregates and the events timeline use. Every window of one call is read
/// in that one snapshot. At most <see cref="QueryContract.MaximumMatchedRecords"/> records per window are returned;
/// one more is a refusal, never a truncation.
/// </summary>
public interface IStructuredQueryRepository
{
    /// <summary>
    /// A refusal for the first camera id (in canonical order) that names no camera, or null when every one exists.
    /// </summary>
    Task<QueryRefusal?> CheckCamerasAsync(IReadOnlyList<Guid> cameraIds, CancellationToken cancellationToken);

    Task<QueryRead<QueryTrackRecord>> ReadTracksAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        QueryCapabilityIdentities identities,
        CancellationToken cancellationToken);

    Task<QueryRead<QueryEventRecord>> ReadEventsAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        CancellationToken cancellationToken);

    /// <summary>Whether any visible Track carries an operator-confirmed <c>EntityId</c> in this installation.</summary>
    Task<bool> AnyConfirmedEntityAsync(CancellationToken cancellationToken);

    /// <summary>
    /// Operator-confirmed Entities (ADR-023 §9) with their member Tracks visible in the snapshot, overlapping each
    /// window and on an included camera; never candidates. The result also says whether this installation has any
    /// confirmed Entity with a visible member.
    /// </summary>
    Task<QueryEntityRead> ReadEntitiesAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        CancellationToken cancellationToken);
}

/// <summary>The Entity read: whether any Entity with a member Track exists here, and the read itself.</summary>
public sealed record QueryEntityRead(bool AnyConfirmed, QueryRead<QueryEntityRecord> Read);
