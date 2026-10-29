using System.Reflection;
using Mavi.Api.Deployment;
using Mavi.Api.Endpoints;
using Mavi.Api.Finalization;
using Mavi.Api.Identity;
using Mavi.Api.Middleware;
using Mavi.Api.Plates;
using Mavi.Api.SceneAnalytics;
using Mavi.Api.Storage;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Api.Startup;
using Mavi.Application.Health;
using Mavi.Application;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Server.IIS;
using System.Text.Json.Serialization;

var builder = WebApplication.CreateBuilder(args);
// Request URLs may carry plate text (Stage 4 plan §5.5): never log them, whatever the configured level.
builder.Logging.AddPlateTextLogPrivacy();
builder.AddMaviMachineConfiguration();
builder.Services.AddMaviInfrastructure(builder.Configuration);
builder.Services.AddDatabaseMigrationStartup(builder.Configuration);
builder.Services.AddHealthChecks();
// Deployment profile disclosure (ADR-020 §3): the installer declares the profile; under
// poc-single-host the disclosure is fixed by code and the host refuses inconsistent metadata.
builder.Services.Configure<Mavi.Application.Deployment.DeploymentOptions>(
    builder.Configuration.GetSection(Mavi.Application.Deployment.DeploymentOptions.SectionName));
// Operator identity and the operator policy (ADR-010). Identity:Mode defaults to disabled; existing
// endpoints stay anonymous and only endpoints that require OperatorPolicy are attributable.
builder.Services.AddMaviOperatorIdentity(builder.Configuration);
// The platform's first background service. It shares this process deliberately (ADR-008
// puts the API host on the operational plane) and is bounded so it cannot compete with
// serving requests; SceneAnalytics:Enabled turns it off entirely.
builder.Services.AddHostedService<SceneAnalyticsHostedService>();
// Platform-owned reclamation of worker attempt staging (ADR-006 §6, S1.2 §6.5).
// The VisionJob row is its sole authority; StagingJanitor:Enabled turns it off.
builder.Services.AddHostedService<StagingJanitorHostedService>();
// The asynchronous finalizer (S1.4 B3 F3): claims Finalizing hand-offs, seals evidence and
// publishes the graph. VisionFinalization:Enabled gates it together with completion 3.1; while
// off it only refreshes the Finalizing counts for /api/health.
builder.Services.AddHostedService<VisionFinalizationHostedService>();
// The Visual Attribute authority loop (S2b): activation, queueing, the deadline/exhaustion
// sweep and attribute staging reclamation. VisualAttributes:Enabled gates it; with nothing
// configured it idles and the release reports NotConfigured.
builder.Services.AddSingleton<VisualAttributeHostedService>();
builder.Services.AddHostedService(provider => provider.GetRequiredService<VisualAttributeHostedService>());
builder.Services.AddSingleton<VisualAttributeAudit>();
// The plate authority loop (Stage 4 PR-3): activation, queueing, the deadline/exhaustion sweep and
// plate staging reclamation. It always runs; Plates:Enabled gates only activation and queueing, and with nothing
// configured it only sweeps and reclaims (NotConfigured).
builder.Services.AddSingleton<PlateHostedService>();
builder.Services.AddHostedService(provider => provider.GetRequiredService<PlateHostedService>());
builder.Services.AddSingleton<PlateAudit>();
// The embedding authority loop (PoC S4; ADR-021): activation, queueing and the deadline/exhaustion sweep.
// Embeddings:Enabled gates it; with nothing configured it idles and similarity answers notConfigured.
builder.Services.AddSingleton<Mavi.Api.Embeddings.EmbeddingHostedService>();
builder.Services.AddHostedService(provider => provider.GetRequiredService<Mavi.Api.Embeddings.EmbeddingHostedService>());
builder.Services.AddSingleton<Mavi.Api.Embeddings.EmbeddingAudit>();
// Canonical API JSON policy: property names are case-sensitive and numeric properties must be JSON numbers.
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNameCaseInsensitive = false;
    options.SerializerOptions.NumberHandling = JsonNumberHandling.Strict;
});
var maximumFileSize = builder.Configuration.GetValue<long>($"{VideoImportOptions.SectionName}:MaximumFileSizeBytes");
var multipartOverhead = builder.Configuration.GetValue<long>($"{VideoImportOptions.SectionName}:MultipartOverheadBytes");
var maximumRequestSize = checked(maximumFileSize + multipartOverhead);
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = maximumRequestSize);
builder.Services.Configure<IISServerOptions>(options => options.MaxRequestBodySize = maximumRequestSize);
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = maximumRequestSize;
});

var app = builder.Build();
await app.VerifyNativeMediaToolsAsync();
app.VerifyTrackCursorSigning();
app.VerifyVisualAttributeRelease();
app.VerifyDeploymentDisclosure();
app.VerifyOperatorIdentity();
app.VerifyPlateRelease();
Mavi.Api.Embeddings.EmbeddingReleaseStartup.VerifyEmbeddingRelease(app);
await app.ApplyDatabaseMigrationsAsync();
// Sanitised request start/finish telemetry in place of the framework's raw-URL lines (Stage 4 §5.5).
app.UseSafeRequestTelemetry();
// A plate-bearing search URL is never sent onward as a Referer (Stage 4 §5.5; defence in depth).
app.UseNoReferrerPolicy();
// Client-aborted requests are expected control flow. Keep cancellation propagation intact in
// repositories and services, but prevent routine RequestAborted exceptions from surfacing as
// application failures (or debugger user-unhandled breaks) at the HTTP boundary.
app.UseMaviRequestCancellationHandling();
app.UseVisionCompletionRequestLimits();
app.UseVisualAttributeRequestLimits();
app.UsePlateRequestLimits();
Mavi.Api.Embeddings.EmbeddingRequestLimitMiddleware.UseEmbeddingRequestLimits(app);
app.UseDefaultFiles();
app.UseStaticFiles();
app.UseAuthentication();
app.UseAuthorization();

app.MapGet("/api/health", (IStagingJanitorMonitor stagingJanitor, IVisionFinalizationMonitor visionFinalization,
    Mavi.Application.Modules.VisualAttributes.VisualAttributeIntegrityMonitor visualAttributeIntegrity,
    Mavi.Application.Modules.Plates.PlateIntegrityMonitor plateIntegrity) =>
{
    var assembly = typeof(Program).Assembly;
    var version = assembly.GetName().Version?.ToString() ?? "0.1.0";
    var metadata = assembly
        .GetCustomAttributes<AssemblyMetadataAttribute>()
        .ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);

    metadata.TryGetValue("MaviBuild", out var build);
    metadata.TryGetValue("MaviCommit", out var commit);
    return Results.Ok(GetPlatformHealth.Execute(
        version, build, commit, new PlatformHealthDetails(stagingJanitor.Current, visionFinalization.Current, visualAttributeIntegrity.Current,
            plateIntegrity.Current)));
});

app.MapHealthChecks("/health/live");
app.MapCameraEndpoints();
app.MapVideoEndpoints();
app.MapProcessingEndpoints();
app.MapStorageTopologyEndpoints();
app.MapVisionJobEndpoints();
app.MapVisualAttributeEndpoints();
app.MapPlateEndpoints();
app.MapEmbeddingEndpoints();
app.MapTrackEndpoints();
app.MapAnalyticsEndpoints();
app.MapArtifactEndpoints();
app.MapSceneEndpoints();
app.MapSceneAnalyticsEndpoints();
app.MapDeploymentEndpoints();
app.MapOperatorIdentityEndpoints();
app.MapGet("/api/system/config", (Microsoft.Extensions.Options.IOptions<LocalizationOptions> options) =>
    Results.Ok(new { displayTimeZoneId = options.Value.DefaultDisplayTimeZoneId }));

// API/health fallthrough must never be rewritten to the SPA.
app.MapGet("/api/{**path}", () => Results.NotFound());
app.MapGet("/health/{**path}", () => Results.NotFound());

// Frontend deep links are resolved only after API and static-file routing.
app.MapFallbackToFile("{*path:nonfile}", "index.html");

app.Run();

public partial class Program;
