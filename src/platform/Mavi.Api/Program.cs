using Mavi.Application.Health;
using Mavi.Infrastructure;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddMaviInfrastructure();
builder.Services.AddHealthChecks();

var app = builder.Build();

app.MapGet("/api/health", () =>
{
    var version = typeof(Program).Assembly.GetName().Version?.ToString() ?? "0.1.0";
    return Results.Ok(GetPlatformHealth.Execute(version));
});

app.MapHealthChecks("/health/live");

app.Run();

public partial class Program;
