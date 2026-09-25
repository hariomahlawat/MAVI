using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// A real <c>Mavi.Api</c> process for the crash harness (F4 plan §11 H rows): the built API
/// assembly the test project already carries, started with <c>dotnet Mavi.Api.dll</c> against
/// the test database, media and evidence roots, killed with <see cref="Process.Kill(bool)"/>.
/// Its console log is captured so finalizer events (1504, 1509) can be read back. The
/// finalizer configuration is the <c>appsettings.json</c> beside the assembly, except what
/// <paramref name="extra"/> overrides (recorded in the row).
/// </summary>
internal sealed class ChildApiHost : IAsyncDisposable
{
    private readonly Process _process;
    private readonly ConcurrentQueue<string> _output = new();

    private ChildApiHost(string name, Process process, Uri baseAddress)
    {
        Name = name;
        _process = process;
        BaseAddress = baseAddress;
        _process.OutputDataReceived += (_, e) => { if (e.Data is not null) _output.Enqueue(e.Data); };
        _process.ErrorDataReceived += (_, e) => { if (e.Data is not null) _output.Enqueue(e.Data); };
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
    }

    public string Name { get; }
    public Uri BaseAddress { get; }
    public DateTimeOffset StartedAtUtc { get; } = DateTimeOffset.UtcNow;
    public IReadOnlyList<string> Output => [.. _output];
    public bool HasExited => _process.HasExited;

    public static int FreePort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    public static ChildApiHost Start(string name, string connectionString, string mediaRoot, string evidenceRoot, IReadOnlyDictionary<string, string>? extra = null)
    {
        var assembly = Path.Combine(AppContext.BaseDirectory, "Mavi.Api.dll");
        if (!File.Exists(assembly)) throw new FileNotFoundException("Mavi.Api.dll is not beside the test assembly", assembly);
        var port = FreePort();
        var start = new ProcessStartInfo("dotnet", [assembly])
        {
            WorkingDirectory = AppContext.BaseDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        var environment = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["ASPNETCORE_ENVIRONMENT"] = "Testing",
            ["ASPNETCORE_URLS"] = $"http://127.0.0.1:{port}",
            ["ConnectionStrings__Mavi"] = connectionString,
            ["MediaStorage__RootPath"] = mediaRoot,
            ["MediaStorage__EvidenceRootPath"] = evidenceRoot,
            ["MediaProcessing__FfprobePath"] = "ffprobe",
            ["MediaProcessing__FfmpegPath"] = "ffmpeg",
            ["MediaProcessing__VerifyOnStartup"] = "false",
            ["DatabaseMigrations__Enabled"] = "false",
            ["SceneAnalytics__Enabled"] = "false",
            ["StagingJanitor__Enabled"] = "false",
            ["VisionFinalization__Enabled"] = "true",
            ["TrackSearch__CursorSigningKey"] = ApiTestFactory.DefaultCursorSigningKey,
            ["Logging__Console__FormatterName"] = "simple",
            ["Logging__LogLevel__Default"] = "Information",
            ["Logging__LogLevel__Microsoft.EntityFrameworkCore"] = "Warning",
        };
        foreach (var (key, value) in extra ?? new Dictionary<string, string>())
            environment[key] = value;
        foreach (var (key, value) in environment)
            start.Environment[key] = value;
        var process = Process.Start(start) ?? throw new InvalidOperationException("dotnet did not start");
        return new ChildApiHost(name, process, new Uri($"http://127.0.0.1:{port}"));
    }

    public HttpClient Client() => new() { BaseAddress = BaseAddress, Timeout = Timeout.InfiniteTimeSpan };

    /// <summary>Waits for <c>/health/live</c>; returns how long the host took to come up.</summary>
    public async Task<TimeSpan> WaitHealthyAsync(TimeSpan timeout)
    {
        using var client = new HttpClient { BaseAddress = BaseAddress, Timeout = TimeSpan.FromSeconds(5) };
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (_process.HasExited)
                throw new InvalidOperationException($"{Name} exited with {_process.ExitCode}: {string.Join('\n', Output.TakeLast(40))}");
            try
            {
                using var response = await client.GetAsync("/health/live");
                if (response.IsSuccessStatusCode) return DateTimeOffset.UtcNow - StartedAtUtc;
            }
            catch (HttpRequestException)
            {
            }
            catch (TaskCanceledException)
            {
            }

            await Task.Delay(100);
        }

        throw new TimeoutException($"{Name} did not become healthy: {string.Join('\n', Output.TakeLast(40))}");
    }

    /// <summary>Process loss: the whole tree, immediately, with no graceful shutdown.</summary>
    public DateTimeOffset Kill()
    {
        if (!_process.HasExited) _process.Kill(entireProcessTree: true);
        _process.WaitForExit();
        return DateTimeOffset.UtcNow;
    }

    public async ValueTask DisposeAsync()
    {
        Kill();
        await Task.CompletedTask;
        _process.Dispose();
    }
}
