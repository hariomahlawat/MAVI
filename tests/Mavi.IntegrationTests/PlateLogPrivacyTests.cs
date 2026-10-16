using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Mavi.Api.Middleware;
using Mavi.Api.Startup;
using Mavi.Application.Modules.Plates;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Mavi.IntegrationTests;

/// <summary>
/// Plate text, cursors and raw query strings never reach the platform's logs — in message text, structured
/// state, scopes or exception text — and every response carries <c>Referrer-Policy: no-referrer</c>
/// (Stage 4 plan §5.5; ADR-013 item 20; cold review P0-1, P2-2).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateLogPrivacyTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);

    private static readonly Dictionary<string, string?> EverythingAtTrace = new()
    {
        ["Logging:LogLevel:Default"] = "Trace",
        ["Logging:LogLevel:Microsoft"] = "Trace",
        ["Logging:LogLevel:Microsoft.AspNetCore"] = "Trace",
        ["Logging:LogLevel:Microsoft.AspNetCore.Hosting.Diagnostics"] = "Trace",
        ["Logging:LogLevel:Microsoft.AspNetCore.Server.Kestrel"] = "Trace",
        ["Logging:LogLevel:Microsoft.AspNetCore.Server.Kestrel.BadRequests"] = "Trace",
        ["Logging:LogLevel:Microsoft.EntityFrameworkCore"] = "Trace",
    };

    [Fact]
    public async Task NoMessageStateScopeOrExceptionCarriesAPlateTextCursorOrQuery()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now, configuration: EverythingAtTrace, kestrel: true);
        var deep = new DeepLogCapture();
        host.Factory.Services.GetRequiredService<ILoggerFactory>().AddProvider(deep);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var run = await host.World.SeedRunAsync(persons: 0, vehicles: 3);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, run);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, identity,
            [.. run.Tracks.Select(track => SeedPlateTrack.Analysed(track.TrackId,
                new SeedPlate(track.Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9))))]);

        var first = await host.Client.GetFromJsonAsync<JsonElement>("/api/tracks?plateText=KA01AB1234&plateMatch=contains&limit=1");
        var cursor = first.GetProperty("nextCursor").GetString()!;
        var rawQuery = $"plateText=KA01AB1234&plateMatch=contains&limit=1&cursor={Uri.EscapeDataString(cursor)}";
        using (var next = await host.Client.GetAsync("/api/tracks?" + rawQuery))
            Assert.Equal(HttpStatusCode.OK, next.StatusCode);
        using (var refused = await host.Client.GetAsync("/api/tracks?plateText=KA01AB1234&cursor=tampered" + cursor[..8]))
            Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
        await host.Client.GetAsync($"/api/tracks/{run.Track(0).TrackId}");
        // A malformed request straight to Kestrel: its request line carries the plate text and a cursor.
        await SendMalformedRequestAsync(host.Client.BaseAddress!, $"/api/tracks?plateText=KA01AB1234&cursor={cursor}");

        Assert.NotEmpty(deep.Records);
        Assert.Contains(deep.Records, record => record.Category.StartsWith("Microsoft.EntityFrameworkCore", StringComparison.Ordinal));
        Assert.Contains(deep.Records, record => record.Level <= LogLevel.Debug);
        foreach (var forbidden in new[] { "KA01AB1234", cursor, Uri.EscapeDataString(cursor), rawQuery, "plateText=", "cursor=" })
        {
            var leaking = deep.Records.Where(record => record.Contains(forbidden)).ToArray();
            Assert.True(leaking.Length == 0,
                $"'{forbidden[..Math.Min(forbidden.Length, 16)]}…' reached the logs: " +
                string.Join(" | ", leaking.Take(3).Select(record => $"[{record.Category}/{record.EventId}] {record.Text[..Math.Min(record.Text.Length, 200)]}")));
        }

        // The two framework categories that write raw request targets are held at Warning whatever the
        // configuration says.
        var factory = host.Factory.Services.GetRequiredService<ILoggerFactory>();
        Assert.False(factory.CreateLogger(PlateTextLogPrivacy.RequestUrlCategory).IsEnabled(LogLevel.Information));
        Assert.False(factory.CreateLogger(PlateTextLogPrivacy.KestrelBadRequestCategory).IsEnabled(LogLevel.Debug));
        Assert.True(factory.CreateLogger(PlateTextLogPrivacy.KestrelBadRequestCategory).IsEnabled(LogLevel.Warning));
        Assert.DoesNotContain(deep.Records, record => record.Category == PlateTextLogPrivacy.KestrelBadRequestCategory && record.Level < LogLevel.Warning);
    }

    [Fact]
    public async Task EveryResponseCarriesNoReferrerPolicy()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);

        foreach (var path in new[] { "/api/tracks?plateText=KA01", "/api/tracks?plateText=K", "/api/health", "/", "/investigation?plateText=KA01", "/assets/missing.js" })
        {
            using var response = await host.Client.GetAsync(path);
            Assert.True(response.Headers.TryGetValues(ReferrerPolicyMiddleware.HeaderName, out var values), $"{path}: {(int)response.StatusCode} has no {ReferrerPolicyMiddleware.HeaderName}");
            Assert.Equal(ReferrerPolicyMiddleware.Policy, Assert.Single(values));
        }
    }

    private static async Task SendMalformedRequestAsync(Uri baseAddress, string target)
    {
        using var client = new TcpClient();
        await client.ConnectAsync(baseAddress.Host, baseAddress.Port);
        await using var stream = client.GetStream();
        // A control character in the request target makes the request line invalid.
        var request = Encoding.Latin1.GetBytes($"GET {target}\u0001 HTTP/1.1\r\nHost: {baseAddress.Host}\r\n\r\n");
        await stream.WriteAsync(request);
        var buffer = new byte[1024];
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            _ = await stream.ReadAsync(buffer, timeout.Token);
        }
        catch (Exception exception) when (exception is IOException or OperationCanceledException)
        {
            // Kestrel answers 400 and may close first; either way the request was processed.
        }
    }

    /// <summary>Captures everything a log record can carry: message, structured state, scopes and exception.</summary>
    private sealed class DeepLogCapture : ILoggerProvider, ISupportExternalScope
    {
        private IExternalScopeProvider _scopes = new LoggerExternalScopeProvider();

        public ConcurrentQueue<Record> Queue { get; } = new();

        public IReadOnlyCollection<Record> Records => Queue.ToArray();

        public ILogger CreateLogger(string categoryName) => new Capturing(this, categoryName);

        public void SetScopeProvider(IExternalScopeProvider scopeProvider) => _scopes = scopeProvider;

        public void Dispose()
        {
        }

        public sealed record Record(string Category, LogLevel Level, EventId EventId, string Text)
        {
            public bool Contains(string value) => Text.Contains(value, StringComparison.OrdinalIgnoreCase);
        }

        private sealed class Capturing(DeepLogCapture owner, string category) : ILogger
        {
            public IDisposable? BeginScope<TState>(TState state) where TState : notnull => owner._scopes.Push(state);

            public bool IsEnabled(LogLevel logLevel) => true;

            public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
            {
                var text = new StringBuilder();
                text.Append(formatter(state, exception)).Append('\n');
                AppendState(text, state);
                if (exception is not null) text.Append(exception).Append('\n');
                owner._scopes.ForEachScope((scope, builder) =>
                {
                    builder.Append(scope).Append('\n');
                    AppendState(builder, scope);
                }, text);
                owner.Queue.Enqueue(new Record(category, logLevel, eventId, text.ToString()));
            }

            private static void AppendState(StringBuilder text, object? state)
            {
                if (state is IEnumerable<KeyValuePair<string, object?>> pairs)
                {
                    foreach (var (key, value) in pairs)
                        text.Append(key).Append('=').Append(value is string or null ? value : JsonOrString(value)).Append('\n');
                }
            }

            private static string JsonOrString(object value)
            {
                if (value is System.Collections.IEnumerable sequence and not string)
                    return string.Join(",", sequence.Cast<object?>());
                return value.ToString() ?? string.Empty;
            }
        }
    }
}
