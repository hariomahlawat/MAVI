using Mavi.Api.Endpoints;
using Mavi.Application.Health;
using Mavi.Application;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure;
using Microsoft.AspNetCore.Http.Features;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddMaviInfrastructure(builder.Configuration);
builder.Services.AddHealthChecks();
var maximumFileSize = builder.Configuration.GetValue<long>($"{VideoImportOptions.SectionName}:MaximumFileSizeBytes");
var multipartOverhead = builder.Configuration.GetValue<long>($"{VideoImportOptions.SectionName}:MultipartOverheadBytes");
var maximumRequestSize = checked(maximumFileSize + multipartOverhead);
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = maximumRequestSize);
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = maximumRequestSize;
});

var app = builder.Build();

app.MapGet("/api/health", () =>
{
    var version = typeof(Program).Assembly.GetName().Version?.ToString() ?? "0.1.0";
    return Results.Ok(GetPlatformHealth.Execute(version));
});

app.MapHealthChecks("/health/live");
app.MapCameraEndpoints();
app.MapVideoEndpoints();
app.MapGet("/api/system/config", (Microsoft.Extensions.Options.IOptions<LocalizationOptions> options) =>
    Results.Ok(new { displayTimeZoneId = options.Value.DefaultDisplayTimeZoneId }));

app.Run();

public partial class Program;
