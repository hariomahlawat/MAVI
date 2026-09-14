using System.Reflection;
using Mavi.Api.Endpoints;
using Mavi.Api.Middleware;
using Mavi.Application.Health;
using Mavi.Application;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Server.IIS;
using System.Text.Json.Serialization;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddMaviInfrastructure(builder.Configuration);
builder.Services.AddHealthChecks();
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
app.UseVisionCompletionRequestLimits();
app.UseDefaultFiles();
app.UseStaticFiles();

app.MapGet("/api/health", () =>
{
    var assembly = typeof(Program).Assembly;
    var version = assembly.GetName().Version?.ToString() ?? "0.1.0";
    var metadata = assembly
        .GetCustomAttributes<AssemblyMetadataAttribute>()
        .ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);

    metadata.TryGetValue("MaviBuild", out var build);
    metadata.TryGetValue("MaviCommit", out var commit);
    return Results.Ok(GetPlatformHealth.Execute(version, build, commit));
});

app.MapHealthChecks("/health/live");
app.MapCameraEndpoints();
app.MapVideoEndpoints();
app.MapProcessingEndpoints();
app.MapVisionJobEndpoints();
app.MapTrackEndpoints();
app.MapArtifactEndpoints();
app.MapGet("/api/system/config", (Microsoft.Extensions.Options.IOptions<LocalizationOptions> options) =>
    Results.Ok(new { displayTimeZoneId = options.Value.DefaultDisplayTimeZoneId }));

// API/health fallthrough must never be rewritten to the SPA.
app.MapGet("/api/{**path}", () => Results.NotFound());
app.MapGet("/health/{**path}", () => Results.NotFound());

// Frontend deep links are resolved only after API and static-file routing.
app.MapFallbackToFile("{*path:nonfile}", "index.html");

app.Run();

public partial class Program;
