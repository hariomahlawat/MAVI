using System.Text.Json;
using Mavi.Api.Embeddings;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Embeddings;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Primitives;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The embedding worker control plane <c>mavi-embedding-control-v1</c> (PoC S4; ADR-021 §3–§4) and the bounded
/// re-analysis request. The lease capability travels only in <c>X-Mavi-Lease-Capability</c>; no body, URL, error
/// or log carries it. Business rules live in <see cref="IEmbeddingLifecycle"/>.
/// </summary>
public static class EmbeddingEndpoints
{
    private static readonly JsonSerializerOptions BodyJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict,
    };

    private static readonly LeaseEvidencePlane EvidencePlane = new("embedding", () => new EmbeddingLeaseLostException(),
        context => Refused(new EmbeddingRefusal(EmbeddingAnalysis.LeaseInvalidCode)).ExecuteAsync(context));

    public static IEndpointRouteBuilder MapEmbeddingEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var analyses = endpoints.MapGroup(EmbeddingContractRules.AnalysisRoutePrefix);
        analyses.MapPost("/lease", LeaseAsync);
        analyses.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        analyses.MapPost("/{id:guid}/fail", FailAsync);
        analyses.MapGet("/{id:guid}/evidence/{observationId:guid}", EvidenceAsync);
        analyses.MapPost("/{id:guid}/complete", CompleteAsync);
        var texts = endpoints.MapGroup(EmbeddingContractRules.TextQueryRoutePrefix);
        texts.MapPost("/lease", TextLeaseAsync);
        texts.MapPost("/{id:guid}/complete", TextCompleteAsync);
        texts.MapPost("/{id:guid}/fail", TextFailAsync);
        endpoints.MapPost("/api/embeddings/reanalysis", ReanalysisAsync);
        return endpoints;
    }

    // --- Analyses ----------------------------------------------------------------------------

    private static async Task<IResult> LeaseAsync(
        HttpContext context,
        EmbeddingLeaseRequest request,
        IEmbeddingLifecycle lifecycle,
        IEmbeddingRelease release,
        IOptions<EmbeddingOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!EmbeddingContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "embedding_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(EmbeddingContractRules.CapabilityHeader))
            return Problem(400, "embedding_capability_unexpected", "A lease request carries no capability.");
        // A worker composed from another identity never takes ownership of a unit it cannot reproduce.
        if (release.Resolution.Definition is not { } definition ||
            !string.Equals(definition.Identity.Fingerprint, request.IdentityFingerprint, StringComparison.Ordinal))
            return Results.NoContent();

        var grant = await lifecycle.ClaimNextAsync(workerId, definition, options.Value.LeasePolicy, cancellationToken);
        if (grant is null) return Results.NoContent();

        context.Response.Headers[EmbeddingContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        var identity = grant.Identity;
        return Results.Ok(new EmbeddingLeaseContract(
            EmbeddingContractRules.SchemaVersion,
            grant.AnalysisId,
            grant.ProcessingRunId,
            grant.WorkerId,
            grant.AttemptCount,
            grant.LeaseExpiresAtUtc,
            grant.DeadlineAtUtc,
            new EmbeddingIdentityContract(identity.Fingerprint, EmbeddingContractRules.IdentitySchemaVersion,
                new EmbeddingModelIdentityContract(identity.ModelId, identity.ModelVersion, identity.ManifestSha256, identity.Dimension),
                new EmbeddingPipelineIdentityContract(identity.PipelineId, identity.PipelineVersion, identity.PipelineSha256)),
            grant.Tracks.Select(track => new EmbeddingLeaseTrackContract(track.TrackId, track.ObjectClass,
                track.Observations.Select(item => new EmbeddingLeaseObservationContract(
                    item.ObservationId, item.Role, item.EvidenceRank, item.SizeBytes, item.Sha256)).ToList())).ToList()));
    }

    private static async Task<IResult> HeartbeatAsync(
        Guid id,
        HttpContext context,
        EmbeddingHeartbeatRequest request,
        IEmbeddingLifecycle lifecycle,
        IOptions<EmbeddingOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1))
            return Problem(400, "embedding_heartbeat_invalid", "Heartbeat input is invalid.");
        if (Capability(context) is not { } capability) return CapabilityProblem();

        var outcome = await lifecycle.HeartbeatAsync(id, workerId, capability, attempt, options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new EmbeddingHeartbeatResponse(EmbeddingContractRules.SchemaVersion, outcome.LeaseExpiresAtUtc!.Value))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> FailAsync(
        Guid id,
        HttpContext context,
        EmbeddingFailRequest request,
        IEmbeddingLifecycle lifecycle,
        IOptions<EmbeddingOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !EmbeddingContractRules.FailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > EmbeddingContractRules.MaximumFailureMessageLength ||
            (request.FailureMessage?.Contains(capability, StringComparison.Ordinal) ?? false))
            return Problem(400, "embedding_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailAsync(id, workerId, capability, attempt, code, retryable, request.FailureMessage,
            options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new EmbeddingFailResponse(EmbeddingContractRules.SchemaVersion,
                outcome.Outcome == EmbeddingFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> EvidenceAsync(
        Guid id,
        Guid observationId,
        HttpContext context,
        IEmbeddingLifecycle lifecycle,
        IAcceptedEvidenceReader evidenceReader,
        EmbeddingAudit audit,
        TimeProvider clock,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, EmbeddingContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt))
            return Problem(400, "embedding_evidence_request_invalid", "Evidence request headers are invalid.");

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
        IEmbeddingLifecycle lifecycle,
        IEmbeddingRelease release,
        EmbeddingAudit audit,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (context.Request.ContentType is not { } contentType || !contentType.StartsWith("application/json", StringComparison.Ordinal))
            return Problem(415, "embedding_completion_media_type", "A JSON completion is required.");

        byte[] body;
        using (var buffer = new MemoryStream())
        {
            await context.Request.Body.CopyToAsync(buffer, cancellationToken);
            body = buffer.ToArray();
        }

        EmbeddingCompleteRequest? request;
        try
        {
            request = JsonSerializer.Deserialize<EmbeddingCompleteRequest>(body, BodyJson);
        }
        catch (JsonException)
        {
            return Problem(400, "embedding_completion_invalid", "The completion is not valid JSON.");
        }

        if (request is null) return Problem(400, "embedding_completion_invalid", "The completion is empty.");
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();

        var result = await lifecycle.CompleteAsync(id, capability, body, request, release.Resolution.Definition, cancellationToken);
        if (!result.IsSuccess)
            return Problem(result.HttpStatus, result.Code!, "The embedding completion was rejected.");

        audit.Completed(id, request.AttemptCount ?? 0, result.Status!, result.TracksEmbedded, result.TracksUnavailable);
        return Results.Ok(new EmbeddingCompleteResponse(EmbeddingContractRules.SchemaVersion, id, result.ProcessingRunId!.Value,
            result.Status!, result.CompletedAtUtc!.Value, result.TracksEmbedded, result.TracksUnavailable));
    }

    // --- Appearance text queries ---------------------------------------------------------------

    private static async Task<IResult> TextLeaseAsync(
        HttpContext context,
        EmbeddingLeaseRequest request,
        IEmbeddingLifecycle lifecycle,
        IEmbeddingRelease release,
        IOptions<EmbeddingOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!EmbeddingContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "embedding_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(EmbeddingContractRules.CapabilityHeader))
            return Problem(400, "embedding_capability_unexpected", "A lease request carries no capability.");
        if (release.Resolution.Definition is not { } definition ||
            !string.Equals(definition.Identity.Fingerprint, request.IdentityFingerprint, StringComparison.Ordinal))
            return Results.NoContent();

        var grant = await lifecycle.ClaimTextAsync(workerId, definition.Identity.Fingerprint,
            TimeSpan.FromSeconds(options.Value.TextQueryLeaseSeconds), cancellationToken);
        if (grant is null) return Results.NoContent();
        context.Response.Headers[EmbeddingContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new EmbeddingTextQueryLeaseContract(EmbeddingContractRules.SchemaVersion, grant.QueryId, grant.WorkerId,
            grant.AttemptCount, grant.LeaseExpiresAtUtc, grant.IdentityFingerprint, grant.Text));
    }

    private static async Task<IResult> TextCompleteAsync(
        Guid id,
        HttpContext context,
        EmbeddingTextQueryCompleteRequest request,
        IEmbeddingLifecycle lifecycle,
        IEmbeddingRelease release,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (release.Resolution.Definition is not { } definition)
            return Problem(409, TrackSimilarityService.NotConfiguredCode, "No embedding identity is configured.");
        if (request.QueryId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            EmbeddingContractRules.TryDecodeVector(request.Embedding, definition.Identity.Dimension) is not { } vector)
            return Problem(400, "embedding_text_completion_invalid", "Text completion input is invalid.");

        var refusal = await lifecycle.CompleteTextAsync(id, workerId, capability, attempt, vector, definition.Identity.Dimension, cancellationToken);
        return refusal is null
            ? Results.Ok(new EmbeddingTextQueryCompleteResponse(EmbeddingContractRules.SchemaVersion, "completed"))
            : Refused(refusal);
    }

    private static async Task<IResult> TextFailAsync(
        Guid id,
        HttpContext context,
        EmbeddingTextQueryFailRequest request,
        IEmbeddingLifecycle lifecycle,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != EmbeddingContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.QueryId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !EmbeddingContractRules.TextFailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > EmbeddingContractRules.MaximumFailureMessageLength)
            return Problem(400, "embedding_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailTextAsync(id, workerId, capability, attempt, code, retryable, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new EmbeddingFailResponse(EmbeddingContractRules.SchemaVersion,
                outcome.Outcome == EmbeddingFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    // --- Re-analysis ------------------------------------------------------------------------------

    public sealed record EmbeddingReanalysisRequestContract(IReadOnlyList<Guid>? ProcessingRunIds);

    private static async Task<IResult> ReanalysisAsync(
        EmbeddingReanalysisRequestContract request,
        IEmbeddingRelease release,
        IEmbeddingLifecycle lifecycle,
        IOptions<EmbeddingOptions> options,
        CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition)
            return Problem(409, TrackSimilarityService.NotConfiguredCode, "No embedding identity is configured.");
        var result = await lifecycle.RequestReanalysisAsync(definition, new EmbeddingReanalysisRequest(request.ProcessingRunIds ?? []),
            options.Value.MaximumRunsPerReanalysisRequest, cancellationToken);
        if (!result.IsSuccess)
            return Problem(result.Refusal!.Code == "processing_run_not_found" ? 404 : 400, result.Refusal.Code,
                "The embedding re-analysis request was rejected.");
        return Results.Accepted(value: new
        {
            identityFingerprint = definition.Identity.Fingerprint,
            runsMatched = result.RunsMatched,
            queued = result.Queued,
            alreadyQueued = result.AlreadyQueued,
            notEligible = result.NotEligible,
        });
    }

    // --- Shared ------------------------------------------------------------------------------

    private static string? Capability(HttpContext context) =>
        context.Request.Headers.TryGetValue(EmbeddingContractRules.CapabilityHeader, out var values) &&
        values.Count == 1 && WorkerContractRules.IsCanonicalLeaseToken(values[0])
            ? values[0]
            : null;

    private static string? Header(HttpContext context, string name) =>
        context.Request.Headers.TryGetValue(name, out StringValues values) && values.Count == 1 ? values[0] : null;

    private static bool TryAttempt(HttpContext context, out int attempt)
    {
        attempt = 0;
        var value = Header(context, EmbeddingContractRules.AttemptHeader);
        return value is { Length: >= 1 and <= 9 } &&
               value.All(char.IsAsciiDigit) && value[0] != '0' &&
               int.TryParse(value, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out attempt);
    }

    internal static IResult Refused(EmbeddingRefusal refusal) => Problem(
        refusal.Code is "embedding_analysis_not_found" or AppearanceQueryEmbedding.NotFoundCode ? 404 : 409,
        refusal.Code, "The embedding operation was rejected.");

    private static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported",
        $"Embedding control-plane version {EmbeddingContractRules.SchemaVersion} is required.");

    private static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");

    private static IResult CapabilityProblem() => Problem(400, "embedding_capability_invalid",
        $"Exactly one canonical {EmbeddingContractRules.CapabilityHeader} header is required.");

    internal static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
