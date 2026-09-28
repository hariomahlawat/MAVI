using System.Diagnostics;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.VisualAttributes;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Primitives;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The attribute worker control plane (S2b plan §9–§12). The lease capability travels only in
/// the <c>X-Mavi-Lease-Capability</c> header, in both directions; no body, URL, error or log
/// ever carries it. Business rules live in <see cref="IVisualAttributeLifecycle"/>.
/// </summary>
public static class VisualAttributeEndpoints
{
    public static IEndpointRouteBuilder MapVisualAttributeEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var group = endpoints.MapGroup(VisualAttributeContractRules.RoutePrefix);
        group.MapPost("/lease", LeaseAsync);
        group.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        group.MapPost("/{id:guid}/fail", FailAsync);
        group.MapGet("/{id:guid}/evidence/{observationId:guid}", EvidenceAsync);
        group.MapPut("/{id:guid}/predictions", UploadAsync);
        group.MapPost("/{id:guid}/complete", VisualAttributeCompletionEndpoint.CompleteAsync);
        endpoints.MapGet("/api/processing/runs/{processingRunId:guid}/visual-attributes", ReadinessAsync);
        return endpoints;
    }

    // --- Lease -------------------------------------------------------------------------------

    private static async Task<IResult> LeaseAsync(
        HttpContext context,
        VisualAttributeLeaseRequest request,
        IVisualAttributeLifecycle lifecycle,
        VisualAttributeWorkerPresence presence,
        IOptions<VisualAttributeOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != VisualAttributeContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!VisualAttributeContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "visual_attribute_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(VisualAttributeContractRules.CapabilityHeader))
            return Problem(400, "visual_attribute_capability_unexpected", "A lease request carries no capability.");

        // A worker leases only while READY, so this poll is the platform's proof of one.
        presence.RecordPoll(workerId, request.IdentityFingerprint!);
        var grant = await lifecycle.ClaimNextAsync(workerId, request.IdentityFingerprint!, options.Value.LeasePolicy, cancellationToken);
        if (grant is null) return Results.NoContent();

        context.Response.Headers[VisualAttributeContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new VisualAttributeLeaseContract(
            VisualAttributeContractRules.SchemaVersion,
            grant.AnalysisId,
            grant.ProcessingRunId,
            grant.WorkerId,
            grant.AttemptCount,
            grant.LeaseExpiresAtUtc,
            grant.DeadlineAtUtc,
            Map(grant.Identity),
            grant.Tracks.Select(track => new VisualAttributeLeaseTrackContract(
                track.TrackId,
                track.ObjectClass,
                track.Observations.Select(item => new VisualAttributeLeaseObservationContract(
                    item.ObservationId, item.Role, item.EvidenceRank, item.SizeBytes, item.Sha256)).ToList())).ToList()));
    }

    private static VisualAttributeIdentityContract Map(VisualAttributeIdentityFields identity)
    {
        var capabilities = System.Text.Json.JsonSerializer.Deserialize<List<VisualAttributeCapabilityIdentityContract>>(
            identity.CapabilitiesCanonical, CapabilityJson) ?? [];
        return new VisualAttributeIdentityContract(
            identity.Fingerprint, identity.AttributeSchemaId, identity.AttributeSchemaVersion, identity.AttributeSchemaSha256,
            identity.PipelineId, identity.PipelineVersion, identity.AggregationPolicyId, identity.AggregationPolicyVersion,
            identity.AggregationPolicySha256, capabilities, identity.ParametersSha256);
    }

    private static readonly System.Text.Json.JsonSerializerOptions CapabilityJson = new(System.Text.Json.JsonSerializerDefaults.Web);

    // --- Heartbeat and failure -----------------------------------------------------------------

    private static async Task<IResult> HeartbeatAsync(
        Guid id,
        HttpContext context,
        VisualAttributeHeartbeatRequest request,
        IVisualAttributeLifecycle lifecycle,
        IOptions<VisualAttributeOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != VisualAttributeContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1))
            return Problem(400, "visual_attribute_heartbeat_invalid", "Heartbeat input is invalid.");
        if (Capability(context) is not { } capability) return CapabilityProblem();

        var outcome = await lifecycle.HeartbeatAsync(id, workerId, capability, attempt, options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new VisualAttributeHeartbeatResponse(VisualAttributeContractRules.SchemaVersion, outcome.LeaseExpiresAtUtc!.Value))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> FailAsync(
        Guid id,
        HttpContext context,
        VisualAttributeFailRequest request,
        IVisualAttributeLifecycle lifecycle,
        IOptions<VisualAttributeOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != VisualAttributeContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !VisualAttributeContractRules.FailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > VisualAttributeContractRules.MaximumFailureMessageLength ||
            // Raw capabilities never cross into persisted diagnostic fields.
            (request.FailureMessage?.Contains(capability, StringComparison.Ordinal) ?? false))
            return Problem(400, "visual_attribute_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailAsync(id, workerId, capability, attempt, code, retryable, request.FailureMessage,
            options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new VisualAttributeFailResponse(VisualAttributeContractRules.SchemaVersion,
                outcome.Outcome == VisualAttributeFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    // --- Evidence read -------------------------------------------------------------------------

    private static async Task<IResult> EvidenceAsync(
        Guid id,
        Guid observationId,
        HttpContext context,
        IVisualAttributeLifecycle lifecycle,
        IAcceptedEvidenceReader evidenceReader,
        VisualAttributeAudit audit,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, VisualAttributeContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt))
            return Problem(400, "visual_attribute_evidence_request_invalid", "Evidence request headers are invalid.");

        var authorization = await lifecycle.AuthorizeEvidenceReadAsync(id, workerId, capability, attempt, observationId, cancellationToken);
        if (!authorization.IsAuthorised)
        {
            audit.EvidenceRefused(id, attempt, observationId, authorization.Refusal!.Code);
            return Refused(authorization.Refusal!);
        }

        var grant = authorization.Grant!;
        Stream? stream = null;
        try
        {
            stream = await evidenceReader.OpenReadAsync(grant.StorageKey, cancellationToken);
        }
        catch (Exception exception) when (exception is FileNotFoundException or DirectoryNotFoundException)
        {
            audit.EvidenceIntegrityIncident(id, attempt, observationId, "evidence_missing");
            return Problem(422, "visual_attribute_evidence_missing", "The accepted evidence object is missing.");
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            // Not an authoritative statement about the object: the worker retries within its lease.
            audit.EvidenceRefused(id, attempt, observationId, "evidence_unreadable");
            return Problem(503, "visual_attribute_evidence_unreadable", "The accepted evidence object could not be read now.");
        }

        // The at-rest size is checked before any response header, so a short or long object
        // is an explicit, authoritative integrity failure — never a truncated 200 (plan §10).
        if (!stream.CanSeek || stream.Length != grant.SizeBytes)
        {
            await stream.DisposeAsync();
            audit.EvidenceIntegrityIncident(id, attempt, observationId, "evidence_integrity_failed");
            return Problem(422, "visual_attribute_evidence_integrity_failed", "The accepted evidence object does not match its record.");
        }

        audit.EvidenceServed(id, attempt, observationId, grant.SizeBytes);
        context.Response.Headers.ContentLength = grant.SizeBytes;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Stream(stream, grant.MimeType, enableRangeProcessing: false);
    }

    // --- Prediction upload ---------------------------------------------------------------------

    private static async Task<IResult> UploadAsync(
        Guid id,
        HttpContext context,
        IVisualAttributeLifecycle lifecycle,
        IAttributeStagingStore staging,
        VisualAttributeAudit audit,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, VisualAttributeContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt) ||
            Header(context, VisualAttributeContractRules.ContentSha256Header) is not { } sha256 ||
            !VisualAttributeContractRules.IsCanonicalSha256(sha256) ||
            !string.Equals(context.Request.ContentType, VisualAttributeContractRules.PredictionsMediaType, StringComparison.Ordinal))
            return Problem(400, "visual_attribute_upload_invalid", "Upload headers are invalid.");
        if (context.Request.ContentLength is not { } length)
            return Problem(411, "visual_attribute_upload_length_required", "An upload declares its length.");

        var authorization = await lifecycle.AuthorizeUploadAsync(id, workerId, capability, attempt, cancellationToken);
        if (authorization is not null) return Refused(authorization);

        var result = await staging.WriteAsync(id, attempt, context.Request.Body, length, sha256, cancellationToken);
        audit.UploadHandled(id, attempt, result.SizeBytes, result.Status.ToString());
        return result.Status switch
        {
            AttributeUploadStatus.Stored or AttributeUploadStatus.AlreadyStored => Results.Ok(new
            {
                schemaVersion = VisualAttributeContractRules.SchemaVersion,
                status = result.Status == AttributeUploadStatus.Stored ? "stored" : "already_stored",
                sizeBytes = result.SizeBytes,
                sha256 = result.Sha256,
            }),
            AttributeUploadStatus.Conflict => Problem(409, "visual_attribute_upload_conflict", "This attempt already staged different bytes."),
            AttributeUploadStatus.TooLarge => Problem(413, "visual_attribute_upload_too_large", "The upload exceeds its declared length."),
            AttributeUploadStatus.Truncated => Problem(400, "visual_attribute_upload_truncated", "The upload ended before its declared length."),
            AttributeUploadStatus.IntegrityMismatch => Problem(422, VisualAttributeContractRules.ArtifactIntegrityFailedCode,
                "The uploaded bytes do not match the declared SHA-256."),
            _ => throw new UnreachableException(),
        };
    }

    // --- Readiness -----------------------------------------------------------------------------

    private static async Task<IResult> ReadinessAsync(
        Guid processingRunId, VisualAttributeReadinessService readiness, CancellationToken cancellationToken)
    {
        var result = await readiness.GetAsync(processingRunId, cancellationToken);
        return result is null
            ? Problem(404, "processing_run_not_found", "The processing run was not found.")
            : Results.Ok(new
            {
                processingRunId = result.ProcessingRunId,
                state = result.State.ToString(),
                detail = result.Detail,
                preferredIdentityFingerprint = result.PreferredIdentityFingerprint,
                defaultAnalysisId = result.DefaultAnalysisId,
                lastReadyWorkerPollUtc = result.LastReadyWorkerPollUtc,
                analyses = result.Analyses,
            });
    }

    // --- Shared ------------------------------------------------------------------------------

    /// <summary>Exactly one canonical capability in the header, or none.</summary>
    internal static string? Capability(HttpContext context) =>
        context.Request.Headers.TryGetValue(VisualAttributeContractRules.CapabilityHeader, out var values) &&
        values.Count == 1 && WorkerContractRules.IsCanonicalLeaseToken(values[0])
            ? values[0]
            : null;

    private static string? Header(HttpContext context, string name) =>
        context.Request.Headers.TryGetValue(name, out StringValues values) && values.Count == 1 ? values[0] : null;

    private static bool TryAttempt(HttpContext context, out int attempt)
    {
        attempt = 0;
        var value = Header(context, VisualAttributeContractRules.AttemptHeader);
        return value is { Length: >= 1 and <= 9 } &&
               value.All(char.IsAsciiDigit) && value[0] != '0' &&
               int.TryParse(value, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out attempt);
    }

    internal static IResult Refused(VisualAttributeRefusal refusal) => Problem(
        refusal.Code == "visual_attribute_analysis_not_found" ? 404 : 409,
        refusal.Code,
        "The visual attribute operation was rejected.");

    internal static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported",
        $"Attribute control-plane version {VisualAttributeContractRules.SchemaVersion} is required.");

    internal static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");

    internal static IResult CapabilityProblem() => Problem(400, "visual_attribute_capability_invalid",
        $"Exactly one canonical {VisualAttributeContractRules.CapabilityHeader} header is required.");

    internal static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
