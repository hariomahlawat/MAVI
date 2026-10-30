using System.Text.Json;
using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Api.Query;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Modules.Query;

/// <summary>An answer, or a typed refusal with the HTTP status it maps to.</summary>
public sealed record StructuredQueryOutcome(QueryEnvelopeResponse? Envelope, QueryRefusal? Refusal, int StatusCode)
{
    public static StructuredQueryOutcome Answer(QueryEnvelopeResponse envelope) => new(envelope, null, 200);

    public static StructuredQueryOutcome Refuse(QueryRefusal refusal) => new(null, refusal, refusal.Code switch
    {
        QueryRefusalCodes.CoverageIncomplete => 409,
        QueryRefusalCodes.QueryScopeTooLarge => 422,
        _ => 400,
    });
}

/// <summary>
/// Evaluates structured queries (ADR-024): resolves the capability identities, reads the matching records in one
/// snapshot, applies the operation with the pure evaluator and builds the envelope. Coverage gates the answer: an
/// operation about the whole scope is withheld when coverage is incomplete, and is refused outright when the caller
/// required complete coverage.
/// </summary>
public sealed class StructuredQueryService(
    IStructuredQueryRepository repository,
    TimeProvider timeProvider,
    IVisualAttributeRelease? attributeRelease = null,
    IPlateRelease? plateRelease = null,
    TrackSimilarityService? similarity = null)
{
    public const string EntityUnavailableReason = "entity_data_unavailable";

    public const string EntityUnavailableMessage =
        "No Entity exists until ReID candidates are confirmed (S7, ADR-023). The Entity unit is defined, and has no data yet.";

    /// <summary>The Entity unit counts operator-confirmed membership only, never candidates (ADR-023 §9).</summary>
    public const string EntityConfirmedOnlyReason = "operator_confirmed_membership_only";

    public const string CoverageIncompleteReason = "coverage_incomplete";

    public async Task<StructuredQueryOutcome> EvaluateAsync(StructuredQuery query, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        var canonical = StructuredQueryCanonical.Write(query);
        var fingerprint = StructuredQueryCanonical.Fingerprint(canonical);
        var evaluatedAtUtc = timeProvider.GetUtcNow().ToUniversalTime();

        // References are checked before anything is answered, for every unit: an unknown camera is refused as unknown,
        // never answered empty (ADR-024 §7).
        if (query.Where.CameraIds.Count > 0 &&
            await repository.CheckCamerasAsync(query.Where.CameraIds, cancellationToken) is { } unknownCamera)
            return StructuredQueryOutcome.Refuse(unknownCamera);

        return query.Unit switch
        {
            QueryUnit.Entity => await EvaluateEntitiesAsync(query, canonical, fingerprint, evaluatedAtUtc, cancellationToken),
            QueryUnit.Event => await EvaluateEventsAsync(query, canonical, fingerprint, evaluatedAtUtc, cancellationToken),
            _ when query.Where.SimilarTo is not null => await EvaluateSimilarAsync(query, canonical, fingerprint, evaluatedAtUtc, cancellationToken),
            _ => await EvaluateTracksAsync(query, canonical, fingerprint, evaluatedAtUtc, cancellationToken),
        };
    }

    private async Task<StructuredQueryOutcome> EvaluateTracksAsync(
        StructuredQuery query, string canonical, string fingerprint, DateTimeOffset evaluatedAtUtc, CancellationToken cancellationToken)
    {
        var where = query.Where;
        string? attributeFingerprint = null;
        string? attributeDisclosure = null;
        if (where.Attributes is { } attributes)
        {
            // The vocabulary is the bound schema's: a value it does not have is a refusal, never an empty answer. With
            // no attribute capability configured the query runs and coverage says NotConfigured, as Track search does.
            if (attributeRelease?.Resolution.Definition is { } definition)
            {
                if (!TrackAttributeQueryRules.TryResolveObjectClass(attributes, definition.Schema, out var objectClass))
                    return Refuse(QueryRefusalCodes.AttributeCombinationInvalid, "/where/attributes",
                        "Every attribute must be in the bound vocabulary and apply to one object class.");
                if (where.ObjectClass is { } stated && stated != objectClass)
                    return Refuse(QueryRefusalCodes.AttributeCombinationInvalid, "/where/objectClass",
                        "The attributes apply to a different object class.");
                where = where with { ObjectClass = objectClass };
                attributeFingerprint = definition.Identity.Fingerprint;
                attributeDisclosure = definition.Disclosure;

                // The class the attributes imply is stated, as a plate's is by the parser, so equivalent queries
                // share one resolved form and one fingerprint.
                query = query with { Where = where };
                canonical = StructuredQueryCanonical.Write(query);
                fingerprint = StructuredQueryCanonical.Fingerprint(canonical);
            }
        }

        var plateFingerprint = where.Plate is null ? null : plateRelease?.Resolution.Definition?.Identity.Fingerprint;
        var read = await repository.ReadTracksAsync(
            where, Windows(query), new QueryCapabilityIdentities(attributeFingerprint, attributeDisclosure, plateFingerprint), cancellationToken);
        if (read.Refusal is { } refusal)
            return StructuredQueryOutcome.Refuse(refusal);

        var coverage = read.Windows.SelectMany(window => window.Coverage).ToList();
        var identity = new QueryIdentityResponse(
            read.Cameras,
            AttributeIdentityFingerprint: attributeFingerprint,
            AttributeDisclosure: attributeDisclosure,
            PlateIdentityFingerprint: plateFingerprint);
        var result = StructuredQueryEvaluator.EvaluateTracks(
            query.Operation, where.Window, read.Windows[0].Records, read.Windows.Count > 1 ? read.Windows[1].Records : null);
        return Gate(query, canonical, fingerprint, new QuerySnapshotResponse(read.SnapshotVisibilitySequence, evaluatedAtUtc), identity, coverage, result);
    }

    private async Task<StructuredQueryOutcome> EvaluateEventsAsync(
        StructuredQuery query, string canonical, string fingerprint, DateTimeOffset evaluatedAtUtc, CancellationToken cancellationToken)
    {
        var read = await repository.ReadEventsAsync(query.Where, Windows(query), cancellationToken);
        if (read.Refusal is { } refusal)
            return StructuredQueryOutcome.Refuse(refusal);

        var coverage = read.Windows.SelectMany(window => window.Coverage).ToList();
        var identity = new QueryIdentityResponse(read.Cameras, EventCatalogueVersion: RuleCatalogue.Current.CatalogueVersion);
        var result = StructuredQueryEvaluator.EvaluateEvents(
            query.Operation, query.Where.Window, read.Windows[0].Records, read.Windows.Count > 1 ? read.Windows[1].Records : null);
        return Gate(query, canonical, fingerprint, new QuerySnapshotResponse(read.SnapshotVisibilitySequence, evaluatedAtUtc), identity, coverage, result);
    }

    /// <summary>
    /// Operator-confirmed Entities (ADR-023 §9). An installation where no Entity has a member Track answers
    /// <c>empty</c> with <c>entity_data_unavailable</c>, as before S7: no rows, no zero count, no error.
    /// </summary>
    private async Task<StructuredQueryOutcome> EvaluateEntitiesAsync(
        StructuredQuery query, string canonical, string fingerprint, DateTimeOffset evaluatedAtUtc, CancellationToken cancellationToken)
    {
        var entities = await repository.ReadEntitiesAsync(query.Where, Windows(query), cancellationToken);
        if (entities.Read.Refusal is { } refusal)
            return StructuredQueryOutcome.Refuse(refusal);
        if (!entities.AnyConfirmed)
            return StructuredQueryOutcome.Answer(Envelope(
                query, canonical, fingerprint,
                new QuerySnapshotResponse(null, evaluatedAtUtc),
                new QueryIdentityResponse([]),
                [new QueryCoverageComponentResponse("entities", "query", false, Reason: EntityUnavailableReason)],
                new QueryResultResponse("empty", Reason: EntityUnavailableReason, Message: EntityUnavailableMessage)));

        var read = entities.Read;
        var coverage = read.Windows.SelectMany(window => window.Coverage).ToList();
        var result = StructuredQueryEvaluator.EvaluateEntities(
            query.Operation, query.Where.Window, read.Windows[0].Records, read.Windows.Count > 1 ? read.Windows[1].Records : null);
        return Gate(query, canonical, fingerprint, new QuerySnapshotResponse(read.SnapshotVisibilitySequence, evaluatedAtUtc),
            new QueryIdentityResponse(read.Cameras), coverage, result);
    }

    /// <summary>
    /// Ranked similarity candidates through the S4 service, in its own signed snapshot. A state other than ready is
    /// incomplete coverage with the service's reason; the candidates are never re-ranked or filtered here.
    /// </summary>
    private async Task<StructuredQueryOutcome> EvaluateSimilarAsync(
        StructuredQuery query, string canonical, string fingerprint, DateTimeOffset evaluatedAtUtc, CancellationToken cancellationToken)
    {
        var where = query.Where;
        var similar = where.SimilarTo!;
        if (similarity is null)
            return Refuse(QueryRefusalCodes.CapabilityNotConfigured, "/where/similarTo", "Similarity is not available on this host.");

        var result = await similarity.FindSimilarAsync(
            similar.TrackId,
            new SimilarTracksQuery(
                similar.K,
                where.CameraIds.Count == 1 ? where.CameraIds[0] : null,
                where.ObjectClass,
                where.Window.FromUtc,
                where.Window.ToUtc,
                null),
            cancellationToken);
        if (!result.TrackFound)
            return Refuse(QueryRefusalCodes.UnknownReference, "/where/similarTo/trackId", "The Track was not found.");
        if (result.ErrorCode is not null)
            return Refuse(QueryRefusalCodes.InvalidValue, "/where/similarTo", "The similarity parameters are invalid.");

        var ready = string.Equals(result.State, TrackSimilarityContractRules.StateReady, StringComparison.Ordinal);
        var records = result.Candidates.Select(candidate => new QueryTrackRecord(
            candidate.Row.Id,
            candidate.Row.CameraId,
            candidate.Row.CameraCode,
            candidate.Row.CameraName,
            candidate.Row.VideoAssetId,
            candidate.Row.ProcessingRunId,
            candidate.Row.ObjectClass,
            candidate.Row.ExposedObjectSubclass,
            candidate.Row.StartTimestampUtc,
            candidate.Row.EndTimestampUtc,
            candidate.Row.StartOffsetMs,
            candidate.Row.DurationMs,
            candidate.Row.MeanConfidence,
            candidate.Row.ThumbnailArtifactId,
            candidate.Score)).ToList();
        var coverage = new List<QueryCoverageComponentResponse>
        {
            new("similarity", "query", ready, Reason: ready ? null : result.Reason ?? result.State),
        };

        return Gate(
            query, canonical, fingerprint,
            new QuerySnapshotResponse(null, evaluatedAtUtc, result.Snapshot),
            new QueryIdentityResponse([], EmbeddingIdentityFingerprint: result.Identity?.Fingerprint),
            coverage,
            StructuredQueryEvaluator.RankedTracks(records, query.Operation.Limit ?? QueryContract.DefaultFindLimit));
    }

    /// <summary>
    /// The coverage gate (ADR-024 §6). Incomplete coverage never reaches the caller as a figure: a whole-scope operation
    /// is withheld, or refused when complete coverage was required. A <c>find</c> keeps its rows, each a real match,
    /// and the coverage says the list is partial.
    /// </summary>
    private static StructuredQueryOutcome Gate(
        StructuredQuery query,
        string canonical,
        string fingerprint,
        QuerySnapshotResponse snapshot,
        QueryIdentityResponse identity,
        IReadOnlyList<QueryCoverageComponentResponse> coverage,
        QueryResultResponse result)
    {
        var complete = coverage.All(component => component.Complete);
        if (!complete && query.RequireCompleteCoverage)
            return Refuse(QueryRefusalCodes.CoverageIncomplete, "/requireCompleteCoverage",
                "Not every part of the scope has been analysed, and complete coverage was required.");
        if (!complete && result.Truncation is { } truncation)
        {
            // A list keeps its real rows, but its total covers only what was analysed: never the scope's count.
            result = result with { Truncation = truncation with { TotalIsLowerBound = true } };
        }

        if (!complete && QueryContract.IsWholeScope(query.Operation.Kind))
            result = new QueryResultResponse(
                "withheld",
                Reason: CoverageIncompleteReason,
                Message: "Not every part of the scope has been analysed, so no figure is given. The coverage says what is missing.");
        return StructuredQueryOutcome.Answer(Envelope(query, canonical, fingerprint, snapshot, identity, coverage, result));
    }

    private static QueryEnvelopeResponse Envelope(
        StructuredQuery query,
        string canonical,
        string fingerprint,
        QuerySnapshotResponse snapshot,
        QueryIdentityResponse identity,
        IReadOnlyList<QueryCoverageComponentResponse> coverage,
        QueryResultResponse result)
    {
        using var document = JsonDocument.Parse(canonical);
        return new QueryEnvelopeResponse(
            QueryContract.Version,
            document.RootElement.Clone(),
            fingerprint,
            QueryContract.ToWire(query.Unit),
            QueryContract.ToWire(query.Operation.Kind),
            snapshot,
            identity,
            new QueryCoverageResponse(coverage.All(component => component.Complete), coverage),
            result,
            QueryContract.Disclosure);
    }

    private static IReadOnlyList<QueryReadWindow> Windows(StructuredQuery query) =>
        query.Operation.Baseline is { } baseline
            ? [new QueryReadWindow("query", query.Where.Window), new QueryReadWindow("baseline", baseline)]
            : [new QueryReadWindow("query", query.Where.Window)];

    private static StructuredQueryOutcome Refuse(string code, string path, string message) =>
        StructuredQueryOutcome.Refuse(new QueryRefusal(code, path, message));
}
