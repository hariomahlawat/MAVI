using System.Text;
using Mavi.Api.Identity;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.Query;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Api.Query;
using Mavi.Contracts.Api.Tracks;
using Microsoft.AspNetCore.Authorization;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The structured query surface (ADR-024 §8): <c>POST /api/query</c> evaluates one query of contract
/// <c>mavi-query-v1</c>; <c>GET /api/query/contract</c> returns the vocabulary a builder or Ask MAVI composes from.
/// Both are read-only. A query outside the contract is refused with a typed reason and never executed.
/// </summary>
public static class StructuredQueryEndpoints
{
    public const string RefusedCode = "query_refused";

    /// <summary>A query is a small document; anything larger is not one.</summary>
    public const int MaximumBodyBytes = 64 * 1024;

    public static IEndpointRouteBuilder MapStructuredQueryEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapPost("/api/query", EvaluateAsync);
        endpoints.MapGet("/api/query/contract", ContractAsync);
        return endpoints;
    }

    /// <summary>
    /// The contract's reason for an Entity unit a caller may not read: confirmed Entities link a person's appearances,
    /// so only an operator reads them (ADR-023 §6, §8), as on every other Entity surface.
    /// </summary>
    public const string EntityOperatorRequiredReason = "operator_required";

    private static async Task<IResult> EvaluateAsync(
        HttpContext context,
        StructuredQueryService service,
        IAuthorizationService authorization,
        CancellationToken cancellationToken)
    {
        if (context.Request.Query.Count > 0)
            return Refused(new QueryRefusal(QueryRefusalCodes.UnknownMember, "", "This route takes no query parameters."));
        // The media type itself, not a prefix: "application/jsonx" is not JSON. A charset parameter is allowed.
        if (!Microsoft.Net.Http.Headers.MediaTypeHeaderValue.TryParse(context.Request.ContentType, out var mediaType) ||
            !string.Equals(mediaType.MediaType.Value, "application/json", StringComparison.OrdinalIgnoreCase))
            return Refused(new QueryRefusal(QueryRefusalCodes.MalformedJson, "", "The body must be application/json."));
        if (context.Request.ContentLength is > MaximumBodyBytes)
            return Refused(new QueryRefusal(QueryRefusalCodes.MalformedJson, "", $"A query is at most {MaximumBodyBytes} bytes."));

        var body = await ReadBoundedAsync(context.Request.Body, cancellationToken);
        if (body is null)
            return Refused(new QueryRefusal(QueryRefusalCodes.MalformedJson, "", $"A query is at most {MaximumBodyBytes} bytes."));

        var parsed = StructuredQueryParser.Parse(body);
        if (parsed.Refusal is { } refusal)
            return Refused(refusal);

        // The Entity unit is an Entity surface: refused without an operator (401 with the scheme's challenge, 403 for an
        // authenticated non-operator), so S9 never reads what /api/entities would refuse (ADR-023 §6, ADR-024 §8).
        if (parsed.Query!.Unit == QueryUnit.Entity && !await IsOperatorAsync(context, authorization))
            return context.User.Identity is { IsAuthenticated: true } ? Results.Forbid() : Results.Challenge();

        var outcome = await service.EvaluateAsync(parsed.Query!, cancellationToken);
        return outcome.Envelope is { } envelope
            ? Results.Ok(envelope)
            : Refused(outcome.Refusal!, outcome.StatusCode);
    }

    private static async Task<bool> IsOperatorAsync(HttpContext context, IAuthorizationService authorization) =>
        (await authorization.AuthorizeAsync(context.User, context, OperatorPolicy.Name)).Succeeded;

    private static async Task<IResult> ContractAsync(HttpContext context, IServiceProvider services, IStructuredQueryRepository repository,
        IAuthorizationService authorization, CancellationToken cancellationToken)
    {
        if (context.Request.Query.Count > 0)
            return Refused(new QueryRefusal(QueryRefusalCodes.UnknownMember, "", "This route takes no query parameters."));

        var definition = services.GetService<IVisualAttributeRelease>()?.Resolution.Definition;
        var attributes = definition is null
            ? []
            : definition.Schema.Attributes
                .OrderBy(item => item.AttributeType, StringComparer.Ordinal)
                .Select(item => new QueryAttributeVocabularyResponse(
                    item.AttributeType,
                    item.ObjectClass == "person" ? "Person" : "Vehicle",
                    [.. item.Values]))
                .ToList();

        // The Entity unit has data once an operator has confirmed an Entity here (ADR-023 §9).
        // Whether any exists is itself Entity data: told to an operator only.
        var isOperator = await IsOperatorAsync(context, authorization);
        var entitiesAvailable = isOperator && await repository.AnyConfirmedEntityAsync(cancellationToken);
        var entityReason = !isOperator ? EntityOperatorRequiredReason : entitiesAvailable ? null : StructuredQueryService.EntityUnavailableReason;
        var units = new[] { QueryUnit.Track, QueryUnit.Event, QueryUnit.Entity }
            .Select(unit => new QueryUnitVocabularyResponse(
                QueryContract.ToWire(unit),
                unit != QueryUnit.Entity || entitiesAvailable,
                unit == QueryUnit.Entity ? entityReason : null,
                QueryContract.Predicates[unit],
                QueryContract.GroupDimensions[unit],
                QueryContract.DistinctFields[unit]))
            .ToList();

        return Results.Ok(new QueryContractResponse(
            QueryContract.Version,
            units,
            QueryContract.Operations,
            QueryContract.ObjectClasses,
            Application.Modules.Intelligence.VehicleSubclassExposurePolicy.ExposedSubclasses,
            QueryContract.ZoneRelations,
            QueryContract.CrossingDirections,
            TrackSearchContractRules.MotionDirectionValues,
            QueryContract.PlateMatches,
            attributes,
            definition?.Disclosure,
            EventRuleIds.All,
            RuleCatalogue.Current.CatalogueVersion,
            new QueryBoundsResponse(
                QueryContract.MaximumCameraIds,
                QueryContract.DefaultFindLimit,
                QueryContract.MaximumFindLimit,
                QueryContract.MaximumTopK,
                QueryContract.MaximumSimilarK,
                QueryContract.MinimumBucketSeconds,
                QueryContract.MaximumBucketSeconds,
                QueryContract.MaximumBuckets,
                QueryContract.MaximumMatchedRecords),
            QueryRefusalCodes.All,
            QueryContract.Disclosure));
    }

    /// <summary>The body as UTF-8 text, or null when it is longer than a query may be (whatever Content-Length said).</summary>
    private static async Task<string?> ReadBoundedAsync(Stream body, CancellationToken cancellationToken)
    {
        using var buffer = new MemoryStream();
        var chunk = new byte[8192];
        int read;
        while ((read = await body.ReadAsync(chunk, cancellationToken)) > 0)
        {
            if (buffer.Length + read > MaximumBodyBytes)
                return null;
            buffer.Write(chunk, 0, read);
        }

        try
        {
            return new UTF8Encoding(false, true).GetString(buffer.GetBuffer(), 0, (int)buffer.Length);
        }
        catch (DecoderFallbackException)
        {
            return string.Empty;
        }
    }

    private static IResult Refused(QueryRefusal refusal, int statusCode = 400) =>
        Results.Problem(
            statusCode: statusCode,
            detail: refusal.Message,
            extensions: new Dictionary<string, object?>
            {
                ["code"] = RefusedCode,
                ["refusal"] = new QueryRefusalResponse(refusal.Code, refusal.Path, refusal.Message),
            });
}
