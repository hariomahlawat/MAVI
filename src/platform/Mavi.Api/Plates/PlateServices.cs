using Mavi.Api.VisualAttributes;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker.Plates;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Plates;

/// <summary>The plate plane's lease-lost exception (the shared fenced stream raises it).</summary>
public sealed class PlateLeaseLostException() : LeaseLostException("plate_lease_lost");

/// <summary>
/// The audit trail of plate-executor access to accepted evidence and of re-analysis requests (ADR-013
/// §10). Never carries a capability, and never a plate text.
/// </summary>
public sealed partial class PlateAudit(ILogger<PlateAudit> logger, PlateIntegrityMonitor integrity, TimeProvider clock) : ILeaseEvidenceAudit
{
    public void EvidenceServed(Guid analysisId, int attempt, Guid observationId, long bytes) =>
        LogEvidenceServed(logger, analysisId, attempt, observationId, bytes);

    public void EvidenceRefused(Guid analysisId, int attempt, Guid observationId, string code) =>
        LogEvidenceRefused(logger, analysisId, attempt, observationId, code);

    public void EvidenceIntegrityIncident(Guid analysisId, int attempt, Guid observationId, string reason)
    {
        integrity.RecordEvidenceReadIncident(analysisId, clock.GetUtcNow());
        LogEvidenceIntegrityIncident(logger, analysisId, attempt, observationId, reason);
    }

    public void EvidenceLeaseLost(Guid analysisId, int attempt, Guid observationId) =>
        LogEvidenceLeaseLost(logger, analysisId, attempt, observationId);

    public void UploadHandled(Guid analysisId, int attempt, long bytes, string outcome) =>
        LogUpload(logger, analysisId, attempt, bytes, outcome);

    public void ReanalysisRequested(string scope, int matched, int queued, int alreadyQueued, int notEligible, IReadOnlyList<Guid> selectedRunIds)
    {
        if (!logger.IsEnabled(LogLevel.Information))
            return;

        var selected = string.Join(",", selectedRunIds);
        LogReanalysis(logger, scope, matched, queued, alreadyQueued, notEligible, selected);
    }

    /// <summary>A refused explicit re-analysis request: its scope and the refusal code only.</summary>
    public void ReanalysisRefused(string scope, string code) => LogReanalysisRefused(logger, scope, code);

    [LoggerMessage(EventId = 2126, EventName = "plate_reanalysis_refused", Level = LogLevel.Warning,
        Message = "Plate re-analysis requested by {Scope} was refused ({Code}); nothing was queued.")]
    private static partial void LogReanalysisRefused(ILogger logger, string scope, string code);

    [LoggerMessage(EventId = 2120, EventName = "plate_evidence_read", Level = LogLevel.Information,
        Message = "Plate evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, {Bytes} bytes, served.")]
    private static partial void LogEvidenceServed(ILogger logger, Guid analysisId, int attempt, Guid observationId, long bytes);

    [LoggerMessage(EventId = 2121, EventName = "plate_evidence_read_refused", Level = LogLevel.Warning,
        Message = "Plate evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, refused ({Code}).")]
    private static partial void LogEvidenceRefused(ILogger logger, Guid analysisId, int attempt, Guid observationId, string code);

    [LoggerMessage(EventId = 2122, EventName = "plate_evidence_integrity_incident", Level = LogLevel.Error,
        Message = "Accepted evidence integrity incident: plate analysis {AnalysisId} attempt {Attempt} Observation {ObservationId} ({Reason}).")]
    private static partial void LogEvidenceIntegrityIncident(ILogger logger, Guid analysisId, int attempt, Guid observationId, string reason);

    [LoggerMessage(EventId = 2123, EventName = "plate_upload", Level = LogLevel.Information,
        Message = "Plate prediction upload: analysis {AnalysisId} attempt {Attempt}, {Bytes} bytes, {Outcome}.")]
    private static partial void LogUpload(ILogger logger, Guid analysisId, int attempt, long bytes, string outcome);

    [LoggerMessage(EventId = 2124, EventName = "plate_evidence_read_lease_lost", Level = LogLevel.Warning,
        Message = "Plate evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, stopped: the attempt lost its lease.")]
    private static partial void LogEvidenceLeaseLost(ILogger logger, Guid analysisId, int attempt, Guid observationId);

    [LoggerMessage(EventId = 2125, EventName = "plate_reanalysis_requested", Level = LogLevel.Information,
        Message = "Plate re-analysis requested by {Scope}: {Matched} runs selected, {Queued} queued, {AlreadyQueued} already queued, {NotEligible} not eligible; selected runs {SelectedRunIds}.")]
    private static partial void LogReanalysis(ILogger logger, string scope, int matched, int queued, int alreadyQueued, int notEligible, string selectedRunIds);
}

/// <summary>
/// The platform's plate authority loop: records the preferred identity's activation, queues eligible
/// runs completed after it, fails units past their deadline or out of attempts — none of which waits for
/// a worker — and reclaims plate staging. The loop always runs: with the release removed, or with
/// <c>Plates:Enabled</c> off, it only sweeps and reclaims, so no lease or staging is ever stranded (see
/// <see cref="PlateOptions.Enabled"/>).
/// </summary>
public sealed partial class PlateHostedService(
    IServiceScopeFactory scopeFactory,
    IPlateRelease release,
    IOptions<PlateOptions> options,
    TimeProvider timeProvider,
    ILogger<PlateHostedService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
            LogAnalysisDisabled(logger);
        else if (release.Resolution.Definition is null)
            LogIdle(logger, release.Resolution.NotConfiguredReason ?? "configured");

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
    public async Task<PlateCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        var configured = options.Value;
        // Disabled analysis queues nothing new; the sweep and the janitor below still govern what exists.
        var definition = configured.Enabled ? release.Resolution.Definition : null;
        await using var scope = scopeFactory.CreateAsyncScope();
        var lifecycle = scope.ServiceProvider.GetRequiredService<IPlateLifecycle>();
        var queued = 0;
        if (definition is not null)
        {
            var activatedAtUtc = await lifecycle.EnsureActivationAsync(definition, cancellationToken);
            queued = await lifecycle.QueueEligibleAsync(definition, activatedAtUtc, configured.ReconcileBatchSize, cancellationToken);
        }

        var sweep = await lifecycle.SweepAsync(configured.LeasePolicy, configured.ReconcileBatchSize, cancellationToken);
        var janitor = await scope.ServiceProvider.GetRequiredService<IPlateStagingJanitor>().RunCycleAsync(cancellationToken);
        if (queued + sweep.DeadlineFailed + sweep.ExhaustedFailed + janitor > 0)
            LogCycle(logger, queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, janitor);
        return new PlateCycleResult(queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, janitor);
    }

    [LoggerMessage(EventId = 2130, EventName = "plate_host_idle", Level = LogLevel.Information,
        Message = "Plate host queues no analysis (release: {Reason}); the sweep and staging janitor run.")]
    private static partial void LogIdle(ILogger logger, string reason);

    [LoggerMessage(EventId = 2133, EventName = "plate_analysis_disabled", Level = LogLevel.Information,
        Message = "Plate analysis is disabled (Plates:Enabled false): nothing new is activated or queued; the sweep and staging janitor run.")]
    private static partial void LogAnalysisDisabled(ILogger logger);

    [LoggerMessage(EventId = 2131, EventName = "plate_cycle", Level = LogLevel.Information,
        Message = "Plate cycle: queued {Queued}, deadline-failed {DeadlineFailed}, exhausted {Exhausted}, staging removed {StagingRemoved}.")]
    private static partial void LogCycle(ILogger logger, int queued, int deadlineFailed, int exhausted, int stagingRemoved);

    [LoggerMessage(EventId = 2132, EventName = "plate_cycle_failed", Level = LogLevel.Error,
        Message = "Plate cycle failed; the next cycle runs on schedule.")]
    private static partial void LogCycleFailed(ILogger logger, Exception exception);
}

public sealed record PlateCycleResult(int Queued, int DeadlineFailed, int ExhaustedFailed, int StagingRemoved);

/// <summary>
/// The interim authorisation of <c>POST /api/plates/reanalysis</c> (PoC S3, register row C4.2). MAVI has no operator
/// identity before ADR-010 (S11-min replaces this gate with it), so the request must present an operator key whose
/// SHA-256 the installation configured (<see cref="PlateOptions.ReanalysisOperatorKeySha256"/>). Fails closed: with no
/// key configured every request is refused. The key is compared by digest in constant time and never logged.
/// </summary>
public static class PlateReanalysisAuthorisation
{
    public const string NotConfiguredCode = "plate_reanalysis_authorisation_not_configured";
    public const string UnauthorisedCode = "plate_reanalysis_unauthorised";

    public sealed record RefusalResult(int Status, string Code, string Detail);

    /// <summary>The refusal for this request, or <see langword="null"/> when it is authorised.</summary>
    public static RefusalResult? Refusal(IHeaderDictionary headers, PlateOptions options)
    {
        ArgumentNullException.ThrowIfNull(headers);
        ArgumentNullException.ThrowIfNull(options);
        // Validate() refuses a malformed digest at start-up; one that still reaches here is treated as not configured.
        if (!options.IsReanalysisAuthorisationConfigured || options.ReanalysisOperatorKeySha256.Length != 64 ||
            !options.ReanalysisOperatorKeySha256.All(char.IsAsciiHexDigitLower))
            return new RefusalResult(StatusCodes.Status403Forbidden, NotConfiguredCode,
                "Plate re-analysis is not authorised on this installation (no operator key is configured).");

        if (!headers.TryGetValue(PlateOptions.ReanalysisOperatorKeyHeader, out var values) || values.Count != 1 ||
            string.IsNullOrEmpty(values[0]) || values[0]!.Length > 256)
            return new RefusalResult(StatusCodes.Status401Unauthorized, UnauthorisedCode, "A valid operator key is required.");

        var expected = Convert.FromHexString(options.ReanalysisOperatorKeySha256);
        var presented = System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(values[0]!));
        return System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(presented, expected)
            ? null
            : new RefusalResult(StatusCodes.Status401Unauthorized, UnauthorisedCode, "A valid operator key is required.");
    }
}

/// <summary>Every plate route's own intentional request-body limit; none inherits the video-import limit.</summary>
public static class PlateRequestLimitMiddleware
{
    public const long ReanalysisRequestBodyBytes = 64 * 1024;

    public static IApplicationBuilder UsePlateRequestLimits(this IApplicationBuilder app)
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
        if (string.Equals(value, "/api/plates/reanalysis", StringComparison.OrdinalIgnoreCase)) return ReanalysisRequestBodyBytes;
        if (!value.StartsWith(PlateContractRules.RoutePrefix + "/", StringComparison.OrdinalIgnoreCase)) return null;
        var segments = value[(PlateContractRules.RoutePrefix.Length + 1)..].Split('/');
        return segments switch
        {
            ["lease"] => PlateContractRules.MaximumLeaseRequestBodyBytes,
            [_, "heartbeat"] => PlateContractRules.MaximumHeartbeatRequestBodyBytes,
            [_, "fail"] => PlateContractRules.MaximumFailRequestBodyBytes,
            [_, "complete"] => PlateContractRules.MaximumCompletionRequestBodyBytes,
            [_, "predictions"] => PlateContractRules.MaximumPredictionArtifactBytes,
            _ => 0,
        };
    }
}

/// <summary>
/// Resolves the plate release at startup and refuses a Development-only definition outside Development and
/// Testing: the fixture role is refused in Production. The one other host that may run a Development-only
/// definition is a platform <b>built</b> for <c>poc-single-host</c> (assembly metadata <c>MaviDeploymentProfile</c>;
/// ADR-020 §1: Development-grade Model Packs, Development evidence class, never Production-qualified), and only for
/// the plan-D4 composition: the analysis identity of PD5 + OC1-S on <c>plates-onnx-v1</c>
/// (<see cref="PocPlateIdentityFingerprint"/>). Configuration cannot grant it: a <c>Deployment:Profile</c> key on an
/// ordinary build does not, and no other Development-only definition (the fixture included) is accepted there.
/// </summary>
public static class PlateReleaseStartup
{
    public const string FixtureForbiddenCode = "plate_development_definition_forbidden";

    /// <summary>
    /// The plate analysis identity of the committed PD5 + OC1-S release
    /// (<c>src/vision/config/components/development-plates-onnx-pilot-v1.json</c> with its profile; the #226 pilot's
    /// identity). A test re-derives it from the committed files, so the two cannot drift apart silently.
    /// </summary>
    public const string PocPlateIdentityFingerprint = "c86c930b038d4f933f66ec2ed2f0c886f2df18dc932f79ec2f703c5f882f066e";

    private static readonly Action<ILogger, string, Exception?> LogConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2140, "PlateReleaseConfigured"),
            "Plate analysis is configured for identity {Fingerprint}.");

    private static readonly Action<ILogger, string, Exception?> LogNotConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(2141, "PlateReleaseNotConfigured"),
            "Plate analysis is not configured ({Reason}).");

    public static void VerifyPlateRelease(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var resolution = app.Services.GetRequiredService<IPlateRelease>().Resolution;
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Mavi.Plates");
        if (resolution.Definition is not { } definition)
        {
            LogNotConfigured(logger, resolution.NotConfiguredReason!, null);
            return;
        }

        RequireAllowed(definition, app.Environment, Deployment.DeploymentEndpoints.BuildProfile);
        LogConfigured(logger, definition.Identity.Fingerprint, null);
    }

    /// <param name="buildProfile">The profile the platform was built for (never a configured value).</param>
    public static void RequireAllowed(PlateReleaseDefinition definition, IHostEnvironment environment, string? buildProfile = null)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(environment);
        if (!definition.DevelopmentOnly || environment.IsDevelopment() || environment.IsEnvironment("Testing"))
            return;
        if (string.Equals(buildProfile, DeploymentProfiles.PocSingleHost, StringComparison.Ordinal) &&
            string.Equals(definition.Identity.Fingerprint, PocPlateIdentityFingerprint, StringComparison.Ordinal))
            return;
        throw new InvalidOperationException(FixtureForbiddenCode);
    }
}
