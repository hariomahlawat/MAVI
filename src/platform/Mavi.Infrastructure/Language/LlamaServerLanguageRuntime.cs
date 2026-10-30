using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Language;

/// <summary>
/// The language role's configuration (ADR-026 §3), written by the PoC installer. <see cref="Enabled"/> false (the default)
/// leaves Ask MAVI refusing with <c>language_unavailable</c>.
/// </summary>
public sealed class LanguageOptions
{
    public const string SectionName = "Language";

    public bool Enabled { get; set; }

    /// <summary>The llama-server port on 127.0.0.1. The host is fixed: the role is loopback only (ADR-026 §3).</summary>
    public int Port { get; set; } = 62301;

    public int TimeoutSeconds { get; set; } = 120;

    public string? ModelPackId { get; set; }

    public string? ModelId { get; set; }

    public string? Quantisation { get; set; }

    public string? RuntimeId { get; set; }

    /// <summary>The device record the launcher writes (<c>resolvedDevicePolicy</c>, <c>deviceResolutionReason</c>).</summary>
    public string? DeviceReportPath { get; set; }
}

/// <summary>
/// Calls llama-server's <c>/completion</c> once per question, with the grammar and greedy decoding, prompt caching on (the
/// shared prefix is reused; recordings are made the same way). Loopback only; a refusal of the role is a typed
/// <see cref="LanguageRuntimeUnavailableException"/>, never a fallback.
/// </summary>
public sealed class LlamaServerLanguageRuntime : ILanguageRuntime, IDisposable
{
    private readonly HttpClient client;
    private readonly LanguageOptions options;

    public LlamaServerLanguageRuntime(IOptions<LanguageOptions> options)
    {
        this.options = options.Value;
        if (this.options.Port is < 1 or > 65535)
            throw new InvalidOperationException("Language:Port must be a TCP port (ADR-026 §3).");
        var baseUri = new UriBuilder(Uri.UriSchemeHttp, IPAddress.Loopback.ToString(), this.options.Port).Uri;
        client = new HttpClient(new SocketsHttpHandler { UseProxy = false }) { BaseAddress = baseUri, Timeout = Timeout.InfiniteTimeSpan };
    }

    public LanguageRuntimeIdentity Identity
    {
        get
        {
            var (device, reason) = ReadDevice(options.DeviceReportPath);
            return new LanguageRuntimeIdentity(true, options.ModelPackId, options.ModelId, options.Quantisation, options.RuntimeId, device, reason);
        }
    }

    public async Task<bool> IsAnsweringAsync(CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(3));
        try
        {
            using var response = await client.GetAsync("/health", timeout.Token);
            return response.IsSuccessStatusCode;
        }
        catch (Exception exception) when (exception is HttpRequestException or OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            return false;
        }
    }

    public async Task<LanguageCompletion> CompleteAsync(LanguageCompletionRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var body = Body(request);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(options.TimeoutSeconds));
        try
        {
            using var content = new StringContent(body.ToJsonString(), System.Text.Encoding.UTF8, "application/json");
            using var response = await client.PostAsync("/completion", content, timeout.Token);
            if (!response.IsSuccessStatusCode)
                throw new LanguageRuntimeUnavailableException(AskCodes.LanguageUnavailable,
                    $"The language role answered {(int)response.StatusCode}.");
            var result = await response.Content.ReadFromJsonAsync<JsonElement>(timeout.Token);
            return Parse(result);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new LanguageRuntimeUnavailableException(AskCodes.LanguageTimeout,
                $"The language role did not answer within {options.TimeoutSeconds} s.");
        }
        catch (HttpRequestException exception)
        {
            throw new LanguageRuntimeUnavailableException(AskCodes.LanguageUnavailable, AskCodes.LanguageUnavailableMessage, exception);
        }
        catch (Exception exception) when (exception is JsonException or KeyNotFoundException or InvalidOperationException or FormatException)
        {
            throw new LanguageRuntimeUnavailableException(AskCodes.LanguageUnavailable, "The language role's reply was not a completion.", exception);
        }
    }

    /// <summary>The <c>/completion</c> body: every sampler pinned so decoding is greedy whatever the server defaults are.</summary>
    public static JsonObject Body(LanguageCompletionRequest request) => new()
    {
        ["prompt"] = request.Prompt,
        ["json_schema"] = JsonNode.Parse(request.Grammar),
        ["n_predict"] = request.Decoding.MaxTokens,
        ["temperature"] = request.Decoding.Temperature,
        ["top_k"] = request.Decoding.TopK,
        ["top_p"] = 1.0,
        ["min_p"] = 0.0,
        ["typical_p"] = 1.0,
        ["repeat_penalty"] = 1.0,
        ["presence_penalty"] = 0.0,
        ["frequency_penalty"] = 0.0,
        ["seed"] = request.Decoding.Seed,
        ["cache_prompt"] = true,
        ["stream"] = false,
    };

    public static LanguageCompletion Parse(JsonElement result)
    {
        var text = result.GetProperty("content").GetString() ?? string.Empty;
        var promptTokens = result.TryGetProperty("tokens_evaluated", out var evaluated) ? evaluated.GetInt32() : 0;
        var generated = result.TryGetProperty("tokens_predicted", out var predicted) ? predicted.GetInt32() : 0;
        var truncated = result.TryGetProperty("stop_type", out var stopType) && stopType.GetString() == "limit";
        return new LanguageCompletion(text, promptTokens, generated, truncated);
    }

    private static (string? Device, string? Reason) ReadDevice(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return (null, null);
        try
        {
            using var stream = File.OpenRead(path);
            using var document = JsonDocument.Parse(stream);
            var root = document.RootElement;
            return (
                root.TryGetProperty("device", out var device) ? device.GetString() : null,
                root.TryGetProperty("deviceResolutionReason", out var reason) ? reason.GetString() : null);
        }
        catch (Exception exception) when (exception is IOException or JsonException or UnauthorizedAccessException)
        {
            return (null, null);
        }
    }

    public void Dispose() => client.Dispose();
}
