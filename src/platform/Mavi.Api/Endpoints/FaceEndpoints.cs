using System.Text.Json;
using Mavi.Api.Faces;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Faces;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Faces;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Primitives;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The face worker control plane <c>mavi-face-control-v1</c> (PoC S6; ADR-022 §3–§5). The lease capability travels
/// only in <c>X-Mavi-Lease-Capability</c>; no body, URL, error or log carries it. Business rules live in
/// <see cref="IFaceLifecycle"/>. The operator surface is <see cref="FaceOperatorEndpoints"/>.
/// </summary>
public static class FaceEndpoints
{
    private static readonly JsonSerializerOptions BodyJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict,
    };

    private static readonly LeaseEvidencePlane EvidencePlane = new("face", () => new FaceLeaseLostException(),
        context => Refused(new FaceRefusal(FaceAnalysis.LeaseInvalidCode)).ExecuteAsync(context));

    public static IEndpointRouteBuilder MapFaceEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var analyses = endpoints.MapGroup(FaceContractRules.AnalysisRoutePrefix);
        analyses.MapPost("/lease", LeaseAsync);
        analyses.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        analyses.MapPost("/{id:guid}/fail", FailAsync);
        analyses.MapGet("/{id:guid}/evidence/{observationId:guid}", EvidenceAsync);
        analyses.MapPost("/{id:guid}/complete", CompleteAsync);
        var queries = endpoints.MapGroup(FaceContractRules.QueryWorkerRoutePrefix);
        queries.MapPost("/lease", QueryLeaseAsync);
        queries.MapGet("/{id:guid}/image", QueryImageAsync);
        queries.MapPost("/{id:guid}/complete", QueryCompleteAsync);
        queries.MapPost("/{id:guid}/fail", QueryFailAsync);
        return endpoints;
    }

    internal static FaceIdentityContract Identity(FaceIdentityFields identity) =>
        new(identity.Fingerprint, FaceContractRules.IdentitySchemaVersion,
            new FaceModelIdentityContract(identity.ModelId, identity.ModelVersion, identity.ManifestSha256, identity.Dimension),
            new FacePipelineIdentityContract(identity.PipelineId, identity.PipelineVersion, identity.PipelineSha256));

    // --- Analyses ----------------------------------------------------------------------------

    private static async Task<IResult> LeaseAsync(
        HttpContext context,
        FaceLeaseRequest request,
        IFaceLifecycle lifecycle,
        IFaceRelease release,
        IOptions<FaceOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!FaceContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "face_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(FaceContractRules.CapabilityHeader))
            return Problem(400, "face_capability_unexpected", "A lease request carries no capability.");
        if (release.Resolution.Definition is not { } definition ||
            !string.Equals(definition.Identity.Fingerprint, request.IdentityFingerprint, StringComparison.Ordinal))
            return Results.NoContent();

        var grant = await lifecycle.ClaimNextAsync(workerId, definition, options.Value.LeasePolicy, cancellationToken);
        if (grant is null) return Results.NoContent();

        context.Response.Headers[FaceContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new FaceLeaseContract(
            FaceContractRules.SchemaVersion,
            grant.AnalysisId,
            grant.ProcessingRunId,
            grant.WorkerId,
            grant.AttemptCount,
            grant.LeaseExpiresAtUtc,
            grant.DeadlineAtUtc,
            Identity(grant.Identity),
            grant.Tracks.Select(track => new FaceLeaseTrackContract(track.TrackId, "Person",
                track.Observations.Select(item => new FaceLeaseObservationContract(
                    item.ObservationId, item.Role, item.EvidenceRank, item.SizeBytes, item.Sha256)).ToList())).ToList()));
    }

    private static async Task<IResult> HeartbeatAsync(
        Guid id,
        HttpContext context,
        FaceHeartbeatRequest request,
        IFaceLifecycle lifecycle,
        IOptions<FaceOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1))
            return Problem(400, "face_heartbeat_invalid", "Heartbeat input is invalid.");
        if (Capability(context) is not { } capability) return CapabilityProblem();

        var outcome = await lifecycle.HeartbeatAsync(id, workerId, capability, attempt, options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new FaceHeartbeatResponse(FaceContractRules.SchemaVersion, outcome.LeaseExpiresAtUtc!.Value))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> FailAsync(
        Guid id,
        HttpContext context,
        FaceFailRequest request,
        IFaceLifecycle lifecycle,
        IOptions<FaceOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !FaceContractRules.FailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > FaceContractRules.MaximumFailureMessageLength ||
            (request.FailureMessage?.Contains(capability, StringComparison.Ordinal) ?? false))
            return Problem(400, "face_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailAsync(id, workerId, capability, attempt, code, retryable, request.FailureMessage,
            options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new FaceFailResponse(FaceContractRules.SchemaVersion, outcome.Outcome == FaceFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> EvidenceAsync(
        Guid id,
        Guid observationId,
        HttpContext context,
        IFaceLifecycle lifecycle,
        IAcceptedEvidenceReader evidenceReader,
        FaceAudit audit,
        TimeProvider clock,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, FaceContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt))
            return Problem(400, "face_evidence_request_invalid", "Evidence request headers are invalid.");

        var verifiedAtUtc = clock.GetUtcNow();
        var authorization = await lifecycle.AuthorizeEvidenceReadAsync(id, workerId, capability, attempt, observationId, cancellationToken);
        if (!authorization.IsAuthorised)
        {
            audit.EvidenceRefused(id, attempt, observationId, authorization.Refusal!.Code);
            return Refused(authorization.Refusal!);
        }

        var grant = authorization.Grant!;
        return await LeaseScopedEvidence.ServeAsync(id, attempt, observationId,
            new LeaseEvidenceGrant(grant.StorageKey, grant.MimeType, grant.SizeBytes, grant.LeaseExpiresAtUtc), verifiedAtUtc,
            token => lifecycle.RevalidateLeaseAsync(id, workerId, capability, attempt, token),
            evidenceReader, audit, clock, EvidencePlane, Problem, cancellationToken);
    }

    /// <summary>
    /// The completion reads the raw body once: its SHA-256 is the completion digest (an identical replay is
    /// idempotent), and the same bytes are deserialised.
    /// </summary>
    private static async Task<IResult> CompleteAsync(
        Guid id,
        HttpContext context,
        IFaceLifecycle lifecycle,
        IFaceRelease release,
        FaceAudit audit,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (await ReadJsonAsync<FaceCompleteRequest>(context, cancellationToken) is not { } parsed)
            return Problem(400, "face_completion_invalid", "A JSON completion is required.");
        var (body, request) = parsed;
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();

        var result = await lifecycle.CompleteAsync(id, capability, body, request, release.Resolution.Definition, cancellationToken);
        if (!result.IsSuccess)
            return Problem(result.HttpStatus, result.Code!, "The face completion was rejected.");

        audit.Completed(id, request.AttemptCount ?? 0, result.Status!, result.TracksObserved, result.TracksUnknown, result.FacesUsable);
        return Results.Ok(new FaceCompleteResponse(FaceContractRules.SchemaVersion, id, result.ProcessingRunId!.Value,
            result.Status!, result.CompletedAtUtc!.Value, result.TracksObserved, result.TracksUnknown));
    }

    // --- Transient query images ----------------------------------------------------------------

    private static async Task<IResult> QueryLeaseAsync(
        HttpContext context,
        FaceLeaseRequest request,
        IFaceLifecycle lifecycle,
        IFaceRelease release,
        IOptions<FaceOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!FaceContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "face_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(FaceContractRules.CapabilityHeader))
            return Problem(400, "face_capability_unexpected", "A lease request carries no capability.");
        if (release.Resolution.Definition is not { } definition ||
            !string.Equals(definition.Identity.Fingerprint, request.IdentityFingerprint, StringComparison.Ordinal))
            return Results.NoContent();

        var grant = await lifecycle.ClaimQueryAsync(workerId, definition.Identity.Fingerprint,
            TimeSpan.FromSeconds(options.Value.QueryLeaseSeconds), cancellationToken);
        if (grant is null) return Results.NoContent();
        context.Response.Headers[FaceContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new FaceQueryLeaseContract(FaceContractRules.SchemaVersion, grant.QueryId, grant.WorkerId, grant.AttemptCount,
            grant.LeaseExpiresAtUtc, Identity(definition.Identity), new FaceQueryImageContract(grant.MimeType, grant.SizeBytes, grant.Sha256)));
    }

    private static async Task<IResult> QueryImageAsync(
        Guid id,
        HttpContext context,
        IFaceLifecycle lifecycle,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, FaceContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt))
            return Problem(400, "face_query_request_invalid", "Query image request headers are invalid.");
        var image = await lifecycle.ReadQueryImageAsync(id, workerId, capability, attempt, cancellationToken);
        if (image.Refusal is { } refusal) return Refused(refusal);
        context.Response.Headers.CacheControl = "no-store";
        return Results.Bytes(image.Bytes!, image.MimeType);
    }

    private static async Task<IResult> QueryCompleteAsync(
        Guid id,
        HttpContext context,
        IFaceLifecycle lifecycle,
        IFaceRelease release,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (release.Resolution.Definition is not { } definition)
            return Problem(409, FaceOperatorEndpoints.NotConfiguredCode, "No face identity is configured.");
        if (await ReadJsonAsync<FaceQueryCompleteRequest>(context, cancellationToken) is not { } parsed)
            return Problem(400, "face_completion_invalid", "A JSON completion is required.");
        var (body, request) = parsed;
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        var result = await lifecycle.CompleteQueryAsync(id, capability, body, request, definition, cancellationToken);
        return result.IsSuccess
            ? Results.Ok(new FaceQueryCompleteResponse(FaceContractRules.SchemaVersion, "completed"))
            : Problem(result.HttpStatus, result.Code!, "The face query completion was rejected.");
    }

    private static async Task<IResult> QueryFailAsync(
        Guid id,
        HttpContext context,
        FaceQueryFailRequest request,
        IFaceLifecycle lifecycle,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != FaceContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.QueryId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !FaceContractRules.QueryFailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > FaceContractRules.MaximumFailureMessageLength)
            return Problem(400, "face_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailQueryAsync(id, workerId, capability, attempt, code, retryable, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new FaceFailResponse(FaceContractRules.SchemaVersion, outcome.Outcome == FaceFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    // --- Shared ------------------------------------------------------------------------------

    /// <summary>The raw JSON body and its parse, or null when it is not a JSON object of the record.</summary>
    private static async Task<(byte[] Body, T Request)?> ReadJsonAsync<T>(HttpContext context, CancellationToken cancellationToken)
        where T : class
    {
        if (context.Request.ContentType is not { } contentType || !contentType.StartsWith("application/json", StringComparison.Ordinal))
            return null;
        byte[] body;
        using (var buffer = new MemoryStream())
        {
            await context.Request.Body.CopyToAsync(buffer, cancellationToken);
            body = buffer.ToArray();
        }

        try
        {
            return JsonSerializer.Deserialize<T>(body, BodyJson) is { } request ? (body, request) : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string? Capability(HttpContext context) =>
        context.Request.Headers.TryGetValue(FaceContractRules.CapabilityHeader, out var values) &&
        values.Count == 1 && WorkerContractRules.IsCanonicalLeaseToken(values[0])
            ? values[0]
            : null;

    private static string? Header(HttpContext context, string name) =>
        context.Request.Headers.TryGetValue(name, out StringValues values) && values.Count == 1 ? values[0] : null;

    private static bool TryAttempt(HttpContext context, out int attempt)
    {
        attempt = 0;
        var value = Header(context, FaceContractRules.AttemptHeader);
        return value is { Length: >= 1 and <= 9 } &&
               value.All(char.IsAsciiDigit) && value[0] != '0' &&
               int.TryParse(value, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out attempt);
    }

    internal static IResult Refused(FaceRefusal refusal) => Problem(
        refusal.Code switch
        {
            "face_analysis_not_found" or FaceQuery.NotFoundCode => 404,
            FaceLifecycle.QueryImageMissingCode => 422,
            _ => 409,
        },
        refusal.Code, "The face operation was rejected.");

    private static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported",
        $"Face control-plane version {FaceContractRules.SchemaVersion} is required.");

    private static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");

    private static IResult CapabilityProblem() => Problem(400, "face_capability_invalid",
        $"Exactly one canonical {FaceContractRules.CapabilityHeader} header is required.");

    internal static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
