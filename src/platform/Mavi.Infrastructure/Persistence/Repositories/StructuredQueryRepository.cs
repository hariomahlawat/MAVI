using Mavi.Application.Modules.Query;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The structured-query read side (ADR-024 §5): Tracks through Track search's repository, Events through the events
/// repository. No query logic lives here; it only routes each unit to the code that already owns its semantics.
/// </summary>
public sealed class StructuredQueryRepository(MaviDbContext db, TimeProvider timeProvider) : IStructuredQueryRepository
{
    /// <summary>The matched-record bound (ADR-024 §5); tests shrink it to reach the refusal over a small fixture.</summary>
    internal int MaximumMatchedRecords { get; init; } = QueryContract.MaximumMatchedRecords;

    public async Task<QueryRefusal?> CheckCamerasAsync(IReadOnlyList<Guid> cameraIds, CancellationToken cancellationToken) =>
        (await StructuredQueryScope.ResolveCamerasAsync(db, cameraIds, cancellationToken)).Refusal;

    public Task<QueryRead<QueryTrackRecord>> ReadTracksAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        QueryCapabilityIdentities identities,
        CancellationToken cancellationToken) =>
        new TrackSearchRepository(db, timeProvider).ReadQueryTracksAsync(where, windows, identities, MaximumMatchedRecords, cancellationToken);

    public Task<QueryRead<QueryEventRecord>> ReadEventsAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        CancellationToken cancellationToken) =>
        new AnalyticEventRepository(db).ReadQueryEventsAsync(where, windows, MaximumMatchedRecords, cancellationToken);
}

/// <summary>A camera named by a query, with what the envelope shows of it.</summary>
internal sealed record QueryCamera(Guid Id, string Code, string Name);

internal sealed record QueryCameras(IReadOnlyList<QueryCamera> Cameras, QueryRefusal? Refusal);

/// <summary>Scope resolution and refusals shared by the Track and Event reads.</summary>
internal static class StructuredQueryScope
{
    /// <summary>
    /// The cameras a query names, in id order, or every camera when it names none (ordered by code, then id). An
    /// unknown id is refused at its position in the canonical (sorted) list.
    /// </summary>
    public static async Task<QueryCameras> ResolveCamerasAsync(
        MaviDbContext db,
        IReadOnlyList<Guid> cameraIds,
        CancellationToken cancellationToken)
    {
        if (cameraIds.Count == 0)
        {
            var all = await db.Cameras.AsNoTracking()
                .OrderBy(camera => camera.Code)
                .ThenBy(camera => camera.Id)
                .Select(camera => new QueryCamera(camera.Id, camera.Code, camera.Name))
                .ToListAsync(cancellationToken);
            return new QueryCameras(all, null);
        }

        var ids = cameraIds.ToArray();
        var found = await db.Cameras.AsNoTracking()
            .Where(camera => ids.Contains(camera.Id))
            .Select(camera => new QueryCamera(camera.Id, camera.Code, camera.Name))
            .ToDictionaryAsync(camera => camera.Id, cancellationToken);
        for (var index = 0; index < ids.Length; index++)
        {
            if (!found.ContainsKey(ids[index]))
                return new QueryCameras([], new QueryRefusal(
                    QueryRefusalCodes.UnknownReference, $"/where/cameraIds/{index}", "The camera was not found."));
        }

        return new QueryCameras([.. ids.Select(id => found[id])], null);
    }

    public static QueryRefusal NotInRevision(string path, string kind) =>
        new(QueryRefusalCodes.UnknownReference, path, $"The {kind} is not part of the scene revision the query resolved to.");

    public static QueryRefusal TooLarge(string window, int bound) =>
        new(QueryRefusalCodes.QueryScopeTooLarge, window == "baseline" ? "/operation/baseline" : "/where",
            $"More than {bound} records match; narrow the window, cameras or predicates.");
}
