using Mavi.Api.VisualAttributes;
using Mavi.Application.Modules.Faces;
using Mavi.Contracts.Worker.Faces;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Faces;

/// <summary>The face plane's lease-lost exception (the shared fenced stream raises it).</summary>
public sealed class FaceLeaseLostException() : LeaseLostException("face_lease_lost");

/// <summary>
/// The log trail of face-executor access to accepted evidence (ADR-013 §10) and of publications. Ids and counts only:
/// never a capability, a vector, an image or a gallery label (ADR-022 §6).
/// </summary>
public sealed partial class FaceAudit(ILogger<FaceAudit> logger) : ILeaseEvidenceAudit
{
    public void EvidenceServed(Guid analysisId, int attempt, Guid observationId, long bytes) =>
        LogEvidenceServed(logger, analysisId, attempt, observationId, bytes);

    public void EvidenceRefused(Guid analysisId, int attempt, Guid observationId, string code) =>
        LogEvidenceRefused(logger, analysisId, attempt, observationId, code);

    public void EvidenceIntegrityIncident(Guid analysisId, int attempt, Guid observationId, string reason) =>
        LogEvidenceIntegrityIncident(logger, analysisId, attempt, observationId, reason);

    public void EvidenceLeaseLost(Guid analysisId, int attempt, Guid observationId) =>
        LogEvidenceLeaseLost(logger, analysisId, attempt, observationId);

    public void Completed(Guid analysisId, int attempt, string status, int observed, int unknown, int usable) =>
        LogCompleted(logger, analysisId, attempt, status, observed, unknown, usable);

    [LoggerMessage(EventId = 2300, EventName = "face_evidence_read", Level = LogLevel.Information,
        Message = "Face evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, {Bytes} bytes, served.")]
    private static partial void LogEvidenceServed(ILogger logger, Guid analysisId, int attempt, Guid observationId, long bytes);

    [LoggerMessage(EventId = 2301, EventName = "face_evidence_read_refused", Level = LogLevel.Warning,
        Message = "Face evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, refused ({Code}).")]
    private static partial void LogEvidenceRefused(ILogger logger, Guid analysisId, int attempt, Guid observationId, string code);

    [LoggerMessage(EventId = 2302, EventName = "face_evidence_integrity_incident", Level = LogLevel.Error,
        Message = "Face evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, integrity incident ({Reason}).")]
    private static partial void LogEvidenceIntegrityIncident(ILogger logger, Guid analysisId, int attempt, Guid observationId, string reason);

    [LoggerMessage(EventId = 2303, EventName = "face_evidence_lease_lost", Level = LogLevel.Warning,
        Message = "Face evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, lease lost while streaming.")]
    private static partial void LogEvidenceLeaseLost(ILogger logger, Guid analysisId, int attempt, Guid observationId);

    [LoggerMessage(EventId = 2304, EventName = "face_completed", Level = LogLevel.Information,
        Message = "Face analysis {AnalysisId} attempt {Attempt} published as {Status}: {Observed} Tracks observed, {Unknown} unknown, {Usable} usable faces.")]
    private static partial void LogCompleted(ILogger logger, Guid analysisId, int attempt, string status, int observed, int unknown, int usable);
}

/// <summary>
/// The face authority loop (ADR-022 §3, §5): queues the visible runs of opted-in cameras, fails units past their
/// deadline or out of attempts, erases expired query images and purges expired queries. With <c>Faces:Enabled</c>
/// off it does not run. Nothing here touches a ProcessingRun.
/// </summary>
public sealed partial class FaceHostedService(
    IServiceScopeFactory scopeFactory,
    IFaceRelease release,
    IOptions<FaceOptions> options,
    TimeProvider timeProvider,
    ILogger<FaceHostedService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
        {
            LogIdle(logger, release.Resolution.Definition is null ? "not_configured" : "disabled");
            return;
        }

        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(configured.ReconcileIntervalSeconds), timeProvider);
        do
        {
            try
            {
                await RunCycleAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
#pragma warning disable CA1031 // One failed cycle must not stop the host or the schedule.
            catch (Exception exception)
#pragma warning restore CA1031
            {
                LogCycleFailed(logger, exception);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    /// <summary>One cycle in its own scope; public so a test drives it without a timer.</summary>
    public async Task<FaceCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        var definition = release.Resolution.Definition;
        var configured = options.Value;
        await using var scope = scopeFactory.CreateAsyncScope();
        var lifecycle = scope.ServiceProvider.GetRequiredService<IFaceLifecycle>();
        var queued = definition is null ? 0 : await lifecycle.QueueEligibleAsync(definition, configured.ReconcileBatchSize, cancellationToken);
        var sweep = await lifecycle.SweepAsync(configured.LeasePolicy, configured.ReconcileBatchSize, cancellationToken);
        if (queued + sweep.DeadlineFailed + sweep.ExhaustedFailed + sweep.QueriesExhausted + sweep.QueryImagesErased + sweep.QueriesPurged > 0)
            LogCycle(logger, queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, sweep.QueryImagesErased, sweep.QueriesPurged);
        return new FaceCycleResult(queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, sweep.QueriesExhausted, sweep.QueryImagesErased,
            sweep.QueriesPurged);
    }

    [LoggerMessage(EventId = 2310, EventName = "face_host_idle", Level = LogLevel.Information,
        Message = "Face host is idle ({Reason}).")]
    private static partial void LogIdle(ILogger logger, string reason);

    [LoggerMessage(EventId = 2311, EventName = "face_cycle", Level = LogLevel.Information,
        Message = "Face cycle: queued {Queued}, deadline-failed {DeadlineFailed}, exhausted {Exhausted}, query images erased {Erased}, queries purged {Purged}.")]
    private static partial void LogCycle(ILogger logger, int queued, int deadlineFailed, int exhausted, int erased, int purged);

    [LoggerMessage(EventId = 2312, EventName = "face_cycle_failed", Level = LogLevel.Error,
        Message = "Face cycle failed; the next cycle runs on schedule.")]
    private static partial void LogCycleFailed(ILogger logger, Exception exception);
}

public sealed record FaceCycleResult(int Queued, int DeadlineFailed, int ExhaustedFailed, int QueriesExhausted, int QueryImagesErased, int QueriesPurged);

/// <summary>Every face route's own intentional request-body limit; none inherits the video-import limit.</summary>
public static class FaceRequestLimitMiddleware
{
    public const long SmallRequestBodyBytes = 16 * 1024;

    /// <summary>A query upload: at most 2 MB of image as base64 in a JSON envelope.</summary>
    public const long QueryUploadBodyBytes = 3L * 1024 * 1024;

    public static IApplicationBuilder UseFaceRequestLimits(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        return app.Use(async (context, next) =>
        {
            if (LimitFor(context.Request.Path) is { } limit)
            {
                var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
                if (feature is { IsReadOnly: false })
                    feature.MaxRequestBodySize = limit;
                if (context.Request.ContentLength is { } length && length > limit)
                {
                    context.Response.StatusCode = StatusCodes.Status413PayloadTooLarge;
                    return;
                }
            }

            await next();
        });
    }

    public static long? LimitFor(PathString path)
    {
        var value = path.Value;
        if (value is null || !value.StartsWith("/api/faces/", StringComparison.OrdinalIgnoreCase)) return null;
        if (value.StartsWith(FaceContractRules.AnalysisRoutePrefix + "/", StringComparison.OrdinalIgnoreCase))
        {
            var segments = value[(FaceContractRules.AnalysisRoutePrefix.Length + 1)..].Split('/');
            return segments switch
            {
                ["lease"] or [_, "heartbeat"] or [_, "fail"] => SmallRequestBodyBytes,
                [_, "complete"] => FaceContractRules.MaximumCompletionBodyBytes,
                _ => 0,
            };
        }

        if (string.Equals(value, FaceContractRules.QueryWorkerRoutePrefix, StringComparison.OrdinalIgnoreCase)) return QueryUploadBodyBytes;
        if (value.StartsWith(FaceContractRules.QueryWorkerRoutePrefix + "/", StringComparison.OrdinalIgnoreCase))
        {
            var segments = value[(FaceContractRules.QueryWorkerRoutePrefix.Length + 1)..].Split('/');
            return segments switch
            {
                ["lease"] or [_, "fail"] => SmallRequestBodyBytes,
                [_, "complete"] => FaceContractRules.MaximumQueryCompletionBodyBytes,
                _ => 0,
            };
        }

        return SmallRequestBodyBytes;
    }
}

/// <summary>
/// Resolves the face release at startup and refuses a Development-only definition outside Development, Testing and
/// the PoC environment (ADR-022 §2, §9: the face packs are Development-grade and the role is refused under P1–P3).
/// </summary>
public static class FaceReleaseStartup
{
    public const string DevelopmentDefinitionForbiddenCode = "face_development_definition_forbidden";

    private static readonly Action<ILogger, string, Exception?> LogConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2320, "FaceReleaseConfigured"),
            "Face analysis is configured for identity {Fingerprint}.");

    private static readonly Action<ILogger, string, Exception?> LogNotConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2321, "FaceReleaseNotConfigured"),
            "Face analysis is not configured ({Reason}).");

    public static void VerifyFaceRelease(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var resolution = app.Services.GetRequiredService<IFaceRelease>().Resolution;
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Mavi.Faces");
        if (resolution.RefusalCode is { } refusal) throw new InvalidOperationException(refusal);
        if (resolution.Definition is not { } definition)
        {
            LogNotConfigured(logger, "not_configured", null);
            return;
        }

        RequireAllowed(definition, app.Environment);
        LogConfigured(logger, definition.Identity.Fingerprint, null);
    }

    /// <summary>
    /// The face role is Development-only in this slice (ADR-022 §9): a definition runs in Development, Testing and
    /// the <c>poc-single-host</c> profile's <c>PoC</c> environment, and is refused anywhere else, Development-only
    /// flag or not.
    /// </summary>
    public static void RequireAllowed(FaceReleaseDefinition definition, IHostEnvironment environment)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(environment);
        if (!environment.IsDevelopment() && !environment.IsEnvironment("Testing") && !environment.IsEnvironment("PoC"))
            throw new InvalidOperationException(DevelopmentDefinitionForbiddenCode);
    }
}
