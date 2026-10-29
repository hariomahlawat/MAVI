using Mavi.Api.VisualAttributes;
using Mavi.Application.Modules.Embeddings;
using Mavi.Contracts.Worker.Embeddings;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Embeddings;

/// <summary>The embedding plane's lease-lost exception (the shared fenced stream raises it).</summary>
public sealed class EmbeddingLeaseLostException() : LeaseLostException("embedding_lease_lost");

/// <summary>The audit trail of embedding-executor access to accepted evidence (ADR-013 §10). Never carries a capability.</summary>
public sealed partial class EmbeddingAudit(ILogger<EmbeddingAudit> logger) : ILeaseEvidenceAudit
{
    public void EvidenceServed(Guid analysisId, int attempt, Guid observationId, long bytes) =>
        LogEvidenceServed(logger, analysisId, attempt, observationId, bytes);

    public void EvidenceRefused(Guid analysisId, int attempt, Guid observationId, string code) =>
        LogEvidenceRefused(logger, analysisId, attempt, observationId, code);

    public void EvidenceIntegrityIncident(Guid analysisId, int attempt, Guid observationId, string reason) =>
        LogEvidenceIntegrityIncident(logger, analysisId, attempt, observationId, reason);

    public void EvidenceLeaseLost(Guid analysisId, int attempt, Guid observationId) =>
        LogEvidenceLeaseLost(logger, analysisId, attempt, observationId);

    public void Completed(Guid analysisId, int attempt, string status, int embedded, int unavailable) =>
        LogCompleted(logger, analysisId, attempt, status, embedded, unavailable);

    [LoggerMessage(EventId = 2200, EventName = "embedding_evidence_read", Level = LogLevel.Information,
        Message = "Embedding evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, {Bytes} bytes, served.")]
    private static partial void LogEvidenceServed(ILogger logger, Guid analysisId, int attempt, Guid observationId, long bytes);

    [LoggerMessage(EventId = 2201, EventName = "embedding_evidence_read_refused", Level = LogLevel.Warning,
        Message = "Embedding evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, refused ({Code}).")]
    private static partial void LogEvidenceRefused(ILogger logger, Guid analysisId, int attempt, Guid observationId, string code);

    [LoggerMessage(EventId = 2202, EventName = "embedding_evidence_integrity_incident", Level = LogLevel.Error,
        Message = "Embedding evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, integrity incident ({Reason}).")]
    private static partial void LogEvidenceIntegrityIncident(ILogger logger, Guid analysisId, int attempt, Guid observationId, string reason);

    [LoggerMessage(EventId = 2203, EventName = "embedding_evidence_lease_lost", Level = LogLevel.Warning,
        Message = "Embedding evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, lease lost while streaming.")]
    private static partial void LogEvidenceLeaseLost(ILogger logger, Guid analysisId, int attempt, Guid observationId);

    [LoggerMessage(EventId = 2204, EventName = "embedding_completed", Level = LogLevel.Information,
        Message = "Embedding analysis {AnalysisId} attempt {Attempt} published as {Status}: {Embedded} Tracks embedded, {Unavailable} unavailable.")]
    private static partial void LogCompleted(ILogger logger, Guid analysisId, int attempt, string status, int embedded, int unavailable);
}

/// <summary>
/// The embedding authority loop (ADR-021 §3): records the preferred identity's activation, queues the visible runs
/// completed after it, and fails units past their deadline or out of attempts (and exhausted text queries). With
/// <c>Embeddings:Enabled</c> off it does not run. Nothing here touches a ProcessingRun.
/// </summary>
public sealed partial class EmbeddingHostedService(
    IServiceScopeFactory scopeFactory,
    IEmbeddingRelease release,
    IOptions<EmbeddingOptions> options,
    TimeProvider timeProvider,
    ILogger<EmbeddingHostedService> logger) : BackgroundService
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
    public async Task<EmbeddingCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        var definition = release.Resolution.Definition;
        var configured = options.Value;
        await using var scope = scopeFactory.CreateAsyncScope();
        var lifecycle = scope.ServiceProvider.GetRequiredService<IEmbeddingLifecycle>();
        var queued = 0;
        if (definition is not null)
        {
            var activatedAtUtc = await lifecycle.EnsureActivationAsync(definition, cancellationToken);
            queued = await lifecycle.QueueEligibleAsync(definition, activatedAtUtc, configured.ReconcileBatchSize, cancellationToken);
        }

        var sweep = await lifecycle.SweepAsync(configured.LeasePolicy, configured.ReconcileBatchSize, cancellationToken);
        if (queued + sweep.DeadlineFailed + sweep.ExhaustedFailed + sweep.TextQueriesExhausted > 0)
            LogCycle(logger, queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, sweep.TextQueriesExhausted);
        return new EmbeddingCycleResult(queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, sweep.TextQueriesExhausted);
    }

    [LoggerMessage(EventId = 2210, EventName = "embedding_host_idle", Level = LogLevel.Information,
        Message = "Embedding host is idle ({Reason}).")]
    private static partial void LogIdle(ILogger logger, string reason);

    [LoggerMessage(EventId = 2211, EventName = "embedding_cycle", Level = LogLevel.Information,
        Message = "Embedding cycle: queued {Queued}, deadline-failed {DeadlineFailed}, exhausted {Exhausted}, text queries exhausted {TextExhausted}.")]
    private static partial void LogCycle(ILogger logger, int queued, int deadlineFailed, int exhausted, int textExhausted);

    [LoggerMessage(EventId = 2212, EventName = "embedding_cycle_failed", Level = LogLevel.Error,
        Message = "Embedding cycle failed; the next cycle runs on schedule.")]
    private static partial void LogCycleFailed(ILogger logger, Exception exception);
}

public sealed record EmbeddingCycleResult(int Queued, int DeadlineFailed, int ExhaustedFailed, int TextQueriesExhausted);

/// <summary>Every embedding route's own intentional request-body limit; none inherits the video-import limit.</summary>
public static class EmbeddingRequestLimitMiddleware
{
    public const long SmallRequestBodyBytes = 16 * 1024;
    public const long TextCompletionBodyBytes = 64 * 1024;

    public static IApplicationBuilder UseEmbeddingRequestLimits(this IApplicationBuilder app)
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
        if (value is null) return null;
        if (string.Equals(value, "/api/embeddings/reanalysis", StringComparison.OrdinalIgnoreCase)) return SmallRequestBodyBytes;
        if (value.StartsWith(EmbeddingContractRules.TextQueryRoutePrefix + "/", StringComparison.OrdinalIgnoreCase))
        {
            var text = value[(EmbeddingContractRules.TextQueryRoutePrefix.Length + 1)..].Split('/');
            return text switch
            {
                ["lease"] or [_, "fail"] => SmallRequestBodyBytes,
                [_, "complete"] => TextCompletionBodyBytes,
                _ => 0,
            };
        }

        if (!value.StartsWith(EmbeddingContractRules.AnalysisRoutePrefix + "/", StringComparison.OrdinalIgnoreCase)) return null;
        var segments = value[(EmbeddingContractRules.AnalysisRoutePrefix.Length + 1)..].Split('/');
        return segments switch
        {
            ["lease"] or [_, "heartbeat"] or [_, "fail"] => SmallRequestBodyBytes,
            [_, "complete"] => EmbeddingContractRules.MaximumCompletionBodyBytes,
            _ => 0,
        };
    }
}

/// <summary>
/// Resolves the embedding release at startup and refuses a Development-only definition outside Development and
/// Testing (ADR-021 §2: the SigLIP 2 pack is Development-grade).
/// </summary>
public static class EmbeddingReleaseStartup
{
    public const string DevelopmentDefinitionForbiddenCode = "embedding_development_definition_forbidden";

    private static readonly Action<ILogger, string, Exception?> LogConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2220, "EmbeddingReleaseConfigured"),
            "Embedding analysis is configured for identity {Fingerprint}.");

    private static readonly Action<ILogger, string, Exception?> LogNotConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2221, "EmbeddingReleaseNotConfigured"),
            "Embedding analysis is not configured ({Reason}).");

    public static void VerifyEmbeddingRelease(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var resolution = app.Services.GetRequiredService<IEmbeddingRelease>().Resolution;
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Mavi.Embeddings");
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
    /// A Development-only definition runs in Development, Testing and the <c>poc-single-host</c> profile's
    /// <c>PoC</c> environment (ADR-020 §1 admits Development-grade Model Packs there); any other host refuses it.
    /// </summary>
    public static void RequireAllowed(EmbeddingReleaseDefinition definition, IHostEnvironment environment)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(environment);
        if (definition.DevelopmentOnly && !environment.IsDevelopment() && !environment.IsEnvironment("Testing") &&
            !environment.IsEnvironment("PoC"))
            throw new InvalidOperationException(DevelopmentDefinitionForbiddenCode);
    }
}
