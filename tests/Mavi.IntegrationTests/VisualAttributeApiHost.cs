using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Api.VisualAttributes;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.VisualAttributes;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

internal sealed record LeasedUnit(VisualAttributeLeaseContract Lease, string Capability, string WorkerId)
{
    public Guid AnalysisId => Lease.AnalysisId;
    public int Attempt => Lease.AttemptCount;
}

/// <summary>
/// The real API host over a <see cref="VisualAttributeWorld"/>: the attribute release overlay
/// (identity A or B), the world's clock and storage roots, and a client that speaks the
/// attribute control plane exactly as the worker does — capability in the header only.
/// </summary>
internal sealed class VisualAttributeApiHost : IAsyncDisposable
{
    private readonly string _releaseDirectory = Path.Combine(Path.GetTempPath(), $"mavi-va-release-{Guid.NewGuid():N}");

    private readonly string _pipelineProfile;
    private readonly IReadOnlyDictionary<string, string?>? _configuration;
    private readonly Action<IServiceCollection>? _services;
    private readonly bool _kestrel;

    private VisualAttributeApiHost(VisualAttributeWorld world, string pipelineProfile,
        IReadOnlyDictionary<string, string?>? configuration, Action<IServiceCollection>? services, bool kestrel)
    {
        World = world;
        _pipelineProfile = pipelineProfile;
        _configuration = configuration;
        _services = services;
        _kestrel = kestrel;
    }

    public VisualAttributeWorld World { get; }

    /// <summary>Every log entry of every host generation, for timings and for capability-absence checks.</summary>
    public VisionFinalizationSubmissionApiTests.CapturingLoggerProvider Logs { get; } = new();

    public string AllLogText() => string.Join('\n', Logs.Entries.Select(entry => entry.Message));
    public ApiTestFactory Factory { get; private set; } = null!;
    public HttpClient Client { get; private set; } = null!;

    public static async Task<VisualAttributeApiHost> CreateAsync(
        PostgresFixture fixture, DateTimeOffset nowUtc, bool identityB = false, string? pipelineProfile = null,
        IReadOnlyDictionary<string, string?>? configuration = null, Action<IServiceCollection>? services = null,
        bool kestrel = false)
    {
        var host = new VisualAttributeApiHost(await VisualAttributeWorld.CreateAsync(fixture, nowUtc),
            pipelineProfile ?? VisualAttributeReleaseFixture.PipelineProfile, configuration, services, kestrel);
        host.Start(identityB);
        return host;
    }

    /// <summary>A platform restart with another enabled binding: same database, storage and clock.</summary>
    public async Task RestartWithAsync(bool identityB)
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        Start(identityB);
    }

    /// <summary>A platform restart with the attribute release removed (NotConfigured).</summary>
    public async Task RestartNotConfiguredAsync(IReadOnlyDictionary<string, string?>? configuration = null)
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        Start(identityB: false, configured: false, configuration);
    }

    private void Start(bool identityB, bool configured = true, IReadOnlyDictionary<string, string?>? configuration = null)
    {
        Factory = new ApiTestFactory
        {
            Clock = World.Clock,
            MediaRootOverride = World.MediaRoot,
            EvidenceRootOverride = World.EvidenceRoot,
            VisualAttributeComponentBindingPath = configured ? VisualAttributeReleaseFixture.WriteBinding(_releaseDirectory, identityB) : null,
            VisualAttributePipelineProfilePath = configured ? _pipelineProfile : null,
            AdditionalConfiguration = configuration is null ? _configuration
                : new Dictionary<string, string?>((_configuration ?? new Dictionary<string, string?>()).Concat(configuration)),
            OverrideServices = services =>
            {
                services.AddSingleton<Microsoft.Extensions.Logging.ILoggerProvider>(Logs);
                _services?.Invoke(services);
            },
        };
        if (_kestrel)
        {
            // A real socket: the in-memory test server buffers a request body before the endpoint
            // runs, which would hide any race inside a streamed upload.
            Factory.UseKestrel(0);
            Factory.StartServer();
        }

        Client = Factory.CreateClient();
    }

    public Task<VisualAttributeCycleResult> RunCycleAsync() =>
        Factory.Services.GetRequiredService<VisualAttributeHostedService>().RunCycleAsync(CancellationToken.None);

    /// <summary>One platform sweep with the host's configured lease policy, as the hosted loop runs it.</summary>
    public async Task<VisualAttributeSweepResult> SweepAsync()
    {
        await using var scope = Factory.Services.CreateAsyncScope();
        var options = scope.ServiceProvider.GetRequiredService<Microsoft.Extensions.Options.IOptions<VisualAttributeOptions>>().Value;
        return await scope.ServiceProvider.GetRequiredService<IVisualAttributeLifecycle>()
            .SweepAsync(options.LeasePolicy, options.ReconcileBatchSize, CancellationToken.None);
    }

    public async Task<VisualAttributeAnalysisStatus> StatusAsync(Guid analysisId)
    {
        await using var db = World.Read();
        return (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync(x => x.Id == analysisId)).Status;
    }

    public string PreferredFingerprint =>
        Factory.Services.GetRequiredService<IVisualAttributeRelease>().Resolution.Definition!.Identity.Fingerprint;

    // --- Control plane --------------------------------------------------------------------

    public Task<HttpResponseMessage> PostLeaseAsync(string workerId, string? fingerprint = null) =>
        Client.PostAsJsonAsync($"{VisualAttributeContractRules.RoutePrefix}/lease", new
        {
            schemaVersion = VisualAttributeContractRules.SchemaVersion,
            workerId,
            identityFingerprint = fingerprint ?? PreferredFingerprint,
        });

    public async Task<LeasedUnit> LeaseAsync(string workerId = "attributes-01")
    {
        using var response = await PostLeaseAsync(workerId);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var lease = await response.Content.ReadFromJsonAsync<VisualAttributeLeaseContract>();
        var capability = Assert.Single(response.Headers.GetValues(VisualAttributeContractRules.CapabilityHeader));
        return new LeasedUnit(lease!, capability, workerId);
    }

    public Task<HttpResponseMessage> HeartbeatAsync(LeasedUnit unit, string? capability = null, int? attempt = null) =>
        SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/heartbeat", capability ?? unit.Capability, new
        {
            schemaVersion = VisualAttributeContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = attempt ?? unit.Attempt,
        });

    public Task<HttpResponseMessage> FailAsync(LeasedUnit unit, string code, string? message = null) =>
        SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/fail", unit.Capability, new
        {
            schemaVersion = VisualAttributeContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = unit.Attempt,
            failureCode = code,
            failureMessage = message,
        });

    public Task<HttpResponseMessage> EvidenceAsync(LeasedUnit unit, Guid observationId, Guid? analysisId = null, string? capability = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Get,
            $"{VisualAttributeContractRules.RoutePrefix}/{analysisId ?? unit.AnalysisId}/evidence/{observationId}");
        Headers(request, capability ?? unit.Capability, unit.WorkerId, unit.Attempt);
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> UploadAsync(LeasedUnit unit, byte[] bytes, string? declaredSha256 = null, int? attempt = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Put, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/predictions")
        {
            Content = new ByteArrayContent(bytes),
        };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue(VisualAttributeContractRules.PredictionsMediaType);
        Headers(request, unit.Capability, unit.WorkerId, attempt ?? unit.Attempt);
        request.Headers.Add(VisualAttributeContractRules.ContentSha256Header, declaredSha256 ?? Sha256(bytes));
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> CompleteAsync(LeasedUnit unit, VisualAttributeCompleteRequest body, string? capability = null) =>
        SendJsonAsync(HttpMethod.Post, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/complete", capability ?? unit.Capability, body);

    /// <summary>Upload the artefact, then complete: the worker's success path.</summary>
    public async Task<HttpResponseMessage> UploadAndCompleteAsync(LeasedUnit unit, BuiltCompletion completion)
    {
        using (var uploaded = await UploadAsync(unit, completion.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        return await CompleteAsync(unit, completion.Request);
    }

    public async Task<HttpResponseMessage> SendJsonAsync(HttpMethod method, string path, string? capability, object body)
    {
        var request = new HttpRequestMessage(method, path)
        {
            Content = new StringContent(JsonSerializer.Serialize(body, JsonSerializerOptions.Web), Encoding.UTF8, "application/json"),
        };
        if (capability is not null) request.Headers.Add(VisualAttributeContractRules.CapabilityHeader, capability);
        return await Client.SendAsync(request);
    }

    private static void Headers(HttpRequestMessage request, string? capability, string workerId, int attempt)
    {
        if (capability is not null) request.Headers.Add(VisualAttributeContractRules.CapabilityHeader, capability);
        request.Headers.Add(VisualAttributeContractRules.WorkerHeader, workerId);
        request.Headers.Add(VisualAttributeContractRules.AttemptHeader, attempt.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    public static async Task<string?> ProblemCodeAsync(HttpResponseMessage response)
    {
        var text = await response.Content.ReadAsStringAsync();
        if (string.IsNullOrEmpty(text)) return null;
        using var document = JsonDocument.Parse(text);
        return document.RootElement.TryGetProperty("code", out var code) ? code.GetString() : null;
    }

    public static string Sha256(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));

    // --- The service, with its test seams -------------------------------------------------

    /// <summary>
    /// The completion service composed exactly as the host composes it, in a scope of its own,
    /// with the reclaim-race and ambiguous-commit seams.
    /// </summary>
    public (VisualAttributeCompletionService Service, IServiceScope Scope) CompletionService(
        Func<CancellationToken, Task>? beforePhaseC = null,
        Func<Task>? beforeCommit = null,
        Func<Task>? afterCommit = null)
    {
        var scope = Factory.Services.CreateScope();
        var services = scope.ServiceProvider;
        var service = new VisualAttributeCompletionService(
            services.GetRequiredService<MaviDbContext>(),
            services.GetRequiredService<TimeProvider>(),
            services.GetRequiredService<ILeaseCapabilityService>(),
            services.GetRequiredService<IVisualAttributeRelease>(),
            services.GetRequiredService<IAttributeStagingStore>(),
            services.GetRequiredService<IAcceptedEvidenceStore>(),
            services.GetRequiredService<VisualAttributeIntegrityMonitor>(),
            services.GetRequiredService<Microsoft.Extensions.Options.IOptions<VisualAttributeOptions>>(),
            NullLogger<VisualAttributeCompletionService>.Instance)
        {
            BeforePhaseC = beforePhaseC,
            BeforeCommit = beforeCommit,
            AfterCommit = afterCommit,
        };
        return (service, scope);
    }

    public async ValueTask DisposeAsync()
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        World.Dispose();
        if (Directory.Exists(_releaseDirectory)) Directory.Delete(_releaseDirectory, recursive: true);
    }
}
