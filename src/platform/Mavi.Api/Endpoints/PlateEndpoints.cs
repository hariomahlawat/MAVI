using System.Diagnostics;
using System.Text.Json;
using Mavi.Api.Plates;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Completion;
using Mavi.Contracts.Api.Plates;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Primitives;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The plate worker control plane <c>mavi-plate-control-v1</c> (Stage 4 plan §5.3), run-level plate
/// readiness and the bounded re-analysis request. The lease capability travels only in the
/// <c>X-Mavi-Lease-Capability</c> header; no body, URL, error or log ever carries it, and no log carries
/// a plate text. Business rules live in <see cref="IPlateLifecycle"/> and <see cref="IPlateCompletionService"/>.
/// </summary>
public static class PlateEndpoints
{
    private static readonly JsonSerializerOptions CapabilityJson = new(JsonSerializerDefaults.Web);

    private static readonly LeaseEvidencePlane EvidencePlane = new("plate", () => new PlateLeaseLostException(),
        context => Refused(new PlateRefusal(PlateAnalysis.LeaseInvalidCode)).ExecuteAsync(context));

    public static IEndpointRouteBuilder MapPlateEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var group = endpoints.MapGroup(PlateContractRules.RoutePrefix);
        group.MapPost("/lease", LeaseAsync);
        group.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        group.MapPost("/{id:guid}/fail", FailAsync);
        group.MapGet("/{id:guid}/evidence/{observationId:guid}", EvidenceAsync);
        group.MapPut("/{id:guid}/predictions", UploadAsync);
        group.MapPost("/{id:guid}/complete", CompleteAsync);
        endpoints.MapGet("/api/processing/runs/{processingRunId:guid}/plates", ReadinessAsync);
        endpoints.MapPost("/api/plates/reanalysis", ReanalysisAsync);
        return endpoints;
    }

    // --- Lease -------------------------------------------------------------------------------

    private static async Task<IResult> LeaseAsync(
        HttpContext context,
        PlateLeaseRequest request,
        IPlateLifecycle lifecycle,
        PlateWorkerPresence presence,
        IOptions<PlateOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != PlateContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!PlateContractRules.IsCanonicalSha256(request.IdentityFingerprint))
            return Problem(400, "plate_identity_invalid", "A canonical identity fingerprint is required.");
        if (context.Request.Headers.ContainsKey(PlateContractRules.CapabilityHeader))
            return Problem(400, "plate_capability_unexpected", "A lease request carries no capability.");

        presence.RecordPoll(workerId, request.IdentityFingerprint!);
        var grant = await lifecycle.ClaimNextAsync(workerId, request.IdentityFingerprint!, options.Value.LeasePolicy, cancellationToken);
        if (grant is null) return Results.NoContent();

        context.Response.Headers[PlateContractRules.CapabilityHeader] = grant.LeaseToken;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new PlateLeaseContract(
            PlateContractRules.SchemaVersion,
            grant.AnalysisId,
            grant.ProcessingRunId,
            grant.WorkerId,
            grant.AttemptCount,
            grant.LeaseExpiresAtUtc,
            grant.DeadlineAtUtc,
            Map(grant.Identity),
            grant.Tracks.Select(track => new PlateLeaseTrackContract(
                track.TrackId,
                PlateContractRules.ObjectClassVehicle,
                track.Observations.Select(item => new PlateLeaseObservationContract(
                    item.ObservationId, item.Role, item.EvidenceRank, item.SizeBytes, item.Sha256)).ToList())).ToList()));
    }

    private static PlateIdentityContract Map(PlateIdentityFields identity)
    {
        var capabilities = JsonSerializer.Deserialize<List<PlateCapabilityIdentityContract>>(identity.CapabilitiesCanonical, CapabilityJson) ?? [];
        return new PlateIdentityContract(
            identity.Fingerprint, identity.PipelineId, identity.PipelineVersion, identity.PredictionsSchemaVersion,
            new PlateNormalisationIdentityContract(identity.NormalisationId, identity.NormalisationSha256),
            new PlateSummaryPolicyIdentityContract(identity.SummaryPolicyId, identity.SummaryPolicyVersion, identity.SummaryPolicySha256),
            capabilities, identity.ParametersSha256);
    }

    // --- Heartbeat and failure -----------------------------------------------------------------

    private static async Task<IResult> HeartbeatAsync(
        Guid id,
        HttpContext context,
        PlateHeartbeatRequest request,
        IPlateLifecycle lifecycle,
        PlateWorkerPresence presence,
        IOptions<PlateOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != PlateContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1))
            return Problem(400, "plate_heartbeat_invalid", "Heartbeat input is invalid.");
        if (Capability(context) is not { } capability) return CapabilityProblem();

        var outcome = await lifecycle.HeartbeatAsync(id, workerId, capability, attempt, options.Value.LeasePolicy, cancellationToken);
        if (outcome.IsSuccess) presence.RecordPoll(workerId, outcome.IdentityFingerprint!);
        return outcome.IsSuccess
            ? Results.Ok(new PlateHeartbeatResponse(PlateContractRules.SchemaVersion, outcome.LeaseExpiresAtUtc!.Value))
            : Refused(outcome.Refusal!);
    }

    private static async Task<IResult> FailAsync(
        Guid id,
        HttpContext context,
        PlateFailRequest request,
        IPlateLifecycle lifecycle,
        IOptions<PlateOptions> options,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != PlateContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.AnalysisId != id || request.AttemptCount is not ({ } attempt and >= 1) ||
            request.FailureCode is not { } code ||
            !PlateContractRules.FailureCodeRetryable.TryGetValue(code, out var retryable) ||
            request.FailureMessage?.Length > PlateContractRules.MaximumFailureMessageLength ||
            (request.FailureMessage?.Contains(capability, StringComparison.Ordinal) ?? false))
            return Problem(400, "plate_failure_invalid", "Failure input is invalid.");

        var outcome = await lifecycle.FailAsync(id, workerId, capability, attempt, code, retryable, request.FailureMessage,
            options.Value.LeasePolicy, cancellationToken);
        return outcome.IsSuccess
            ? Results.Ok(new PlateFailResponse(PlateContractRules.SchemaVersion, outcome.Outcome == PlateFailOutcome.Requeued ? "requeued" : "failed"))
            : Refused(outcome.Refusal!);
    }

    // --- Evidence read (the shared lease-scoped handler) -------------------------------------------

    private static async Task<IResult> EvidenceAsync(
        Guid id,
        Guid observationId,
        HttpContext context,
        IPlateLifecycle lifecycle,
        IAcceptedEvidenceReader evidenceReader,
        PlateAudit audit,
        TimeProvider clock,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, PlateContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt))
            return Problem(400, "plate_evidence_request_invalid", "Evidence request headers are invalid.");

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

    // --- Prediction upload ---------------------------------------------------------------------

    private static async Task<IResult> UploadAsync(
        Guid id,
        HttpContext context,
        IPlateLifecycle lifecycle,
        IPlateStagingStore staging,
        PlateAudit audit,
        TimeProvider clock,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(Header(context, PlateContractRules.WorkerHeader), out var workerId) ||
            !TryAttempt(context, out var attempt) ||
            Header(context, PlateContractRules.ContentSha256Header) is not { } sha256 ||
            !PlateContractRules.IsCanonicalSha256(sha256) ||
            !string.Equals(context.Request.ContentType, PlateContractRules.PredictionsMediaType, StringComparison.Ordinal))
            return Problem(400, "plate_upload_invalid", "Upload headers are invalid.");
        if (context.Request.ContentLength is not { } length)
            return Problem(411, "plate_upload_length_required", "An upload declares its length.");

        var authorization = await lifecycle.AuthorizeUploadAsync(id, workerId, capability, attempt, cancellationToken);
        if (authorization is not null) return Refused(authorization);

        PlateUploadResult result;
        await using (var body = new LeaseFencedStream(context.Request.Body,
                         token => lifecycle.RevalidateLeaseAsync(id, workerId, capability, attempt, token), clock,
                         DateTimeOffset.MinValue, DateTimeOffset.MinValue, () => new PlateLeaseLostException()))
        {
            try
            {
                result = await staging.WriteAsync(id, attempt, body, length, sha256, cancellationToken);
            }
            catch (PlateLeaseLostException)
            {
                audit.UploadHandled(id, attempt, 0, "LeaseLost");
                return Refused(new PlateRefusal(PlateAnalysis.LeaseInvalidCode));
            }
        }

        audit.UploadHandled(id, attempt, result.SizeBytes, result.Status.ToString());
        return result.Status switch
        {
            PlateUploadStatus.Stored or PlateUploadStatus.AlreadyStored => Results.Ok(new
            {
                schemaVersion = PlateContractRules.SchemaVersion,
                status = result.Status == PlateUploadStatus.Stored ? "stored" : "already_stored",
                sizeBytes = result.SizeBytes,
                sha256 = result.Sha256,
            }),
            PlateUploadStatus.Conflict => Problem(409, "plate_upload_conflict", "This attempt already staged different bytes."),
            PlateUploadStatus.TooLarge => Problem(413, "plate_upload_too_large", "The upload exceeds its declared length."),
            PlateUploadStatus.Truncated => Problem(400, "plate_upload_truncated", "The upload ended before its declared length."),
            PlateUploadStatus.IntegrityMismatch => Problem(422, PlateContractRules.ArtifactIntegrityFailedCode,
                "The uploaded bytes do not match the declared SHA-256."),
            _ => throw new UnreachableException(),
        };
    }

    // --- Completion ----------------------------------------------------------------------------

    private static async Task<IResult> CompleteAsync(
        Guid id,
        HttpContext context,
        PlateCompleteRequest request,
        IPlateCompletionService completion,
        CancellationToken cancellationToken)
    {
        if (Capability(context) is not { } capability) return CapabilityProblem();
        if (request.SchemaVersion != PlateContractRules.SchemaVersion) return VersionProblem();

        var result = await completion.CompleteAsync(id, capability, request, cancellationToken);
        if (result.Status == PlateCompletionStatus.Refused)
            return Problem(result.HttpStatus, result.Code!, "The plate completion was rejected.");

        return Results.Ok(new PlateCompleteResponse(
            PlateContractRules.SchemaVersion,
            id,
            result.ProcessingRunId!.Value,
            result.Status == PlateCompletionStatus.Completed ? "completed" : "superseded",
            result.CompletedAtUtc!.Value,
            result.TracksAnalysed,
            result.TracksUnavailable));
    }

    // --- Readiness and re-analysis ----------------------------------------------------------------

    private static async Task<IResult> ReadinessAsync(Guid processingRunId, PlateReadinessService readiness, CancellationToken cancellationToken)
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
                analyses = result.Analyses.Select(item => new
                {
                    analysisId = item.AnalysisId,
                    identityFingerprint = item.IdentityFingerprint,
                    status = item.Status.ToString(),
                    attemptCount = item.AttemptCount,
                    queuedAtUtc = item.QueuedAtUtc,
                    completedAtUtc = item.CompletedAtUtc,
                    failureCode = item.FailureCode,
                    isPreferredIdentity = item.IsPreferredIdentity,
                    isDefault = item.IsDefault,
                }),
            });
    }

    private static async Task<IResult> ReanalysisAsync(
        PlateReanalysisRequestContract request,
        IPlateRelease release,
        IPlateLifecycle lifecycle,
        PlateAudit audit,
        IOptions<PlateOptions> options,
        CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition)
            return Problem(409, "plate_not_configured", "No plate analysis is configured in this release.");
        var result = await lifecycle.RequestReanalysisAsync(definition,
            new PlateReanalysisRequest(request.ProcessingRunIds, request.CameraId, request.FromUtc, request.ToUtc),
            options.Value.MaximumRunsPerReanalysisRequest, cancellationToken);
        if (!result.IsSuccess)
        {
            var status = result.Refusal!.Code == "processing_run_not_found" ? 404 : result.Refusal.Code == "plate_reanalysis_too_many_runs" ? 422 : 400;
            return Problem(status, result.Refusal.Code, "The plate re-analysis request was rejected.");
        }

        audit.ReanalysisRequested(request.ProcessingRunIds is null ? "camera-window" : "runs", result.RunsMatched, result.Queued,
            result.AlreadyQueued, result.NotEligible);
        return Results.Accepted(value: new PlateReanalysisResponseContract(result.IdentityFingerprint, result.RunsMatched, result.Queued,
            result.AlreadyQueued, result.NotEligible));
    }

    // --- Shared ------------------------------------------------------------------------------

    internal static string? Capability(HttpContext context) =>
        context.Request.Headers.TryGetValue(PlateContractRules.CapabilityHeader, out var values) &&
        values.Count == 1 && WorkerContractRules.IsCanonicalLeaseToken(values[0])
            ? values[0]
            : null;

    private static string? Header(HttpContext context, string name) =>
        context.Request.Headers.TryGetValue(name, out StringValues values) && values.Count == 1 ? values[0] : null;

    private static bool TryAttempt(HttpContext context, out int attempt)
    {
        attempt = 0;
        var value = Header(context, PlateContractRules.AttemptHeader);
        return value is { Length: >= 1 and <= 9 } &&
               value.All(char.IsAsciiDigit) && value[0] != '0' &&
               int.TryParse(value, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out attempt);
    }

    internal static IResult Refused(PlateRefusal refusal) => Problem(
        refusal.Code == "plate_analysis_not_found" ? 404 : 409, refusal.Code, "The plate operation was rejected.");

    private static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported",
        $"Plate control-plane version {PlateContractRules.SchemaVersion} is required.");

    private static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");

    private static IResult CapabilityProblem() => Problem(400, "plate_capability_invalid",
        $"Exactly one canonical {PlateContractRules.CapabilityHeader} header is required.");

    internal static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
