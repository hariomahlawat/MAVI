using Mavi.Api.Endpoints;
using Mavi.Application.Health;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure;
using Microsoft.AspNetCore.Http.Features;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddMaviInfrastructure(builder.Configuration);
builder.Services.AddHealthChecks();
var maximumFileSize = builder.Configuration.GetValue<long>($"{VideoImportOptions.SectionName}:MaximumFileSizeBytes");
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = maximumFileSize);
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = maximumFileSize;
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

app.Run();

public partial class Program;
