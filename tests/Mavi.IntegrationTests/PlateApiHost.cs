using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Api.Plates;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Plates;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Plates;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.IntegrationTests;

internal sealed record LeasedPlateUnit(PlateLeaseContract Lease, string Capability, string WorkerId)
{
    public Guid AnalysisId => Lease.AnalysisId;
    public int Attempt => Lease.AttemptCount;
}

/// <summary>
/// Plate release overlays for integration tests: the shipped Component Binding plus a <c>plates</c> role
/// bound to fixture Model Pack ids (identity A, or B with another OCR pack), over the committed fixture
/// profile. Written LF-only and compact, as the release-text rules require.
/// </summary>
internal static class PlateReleaseFixture
{
    public static readonly string FixtureDirectory = Path.Combine(VisualAttributeReleaseFixture.Root, "tests", "fixtures", "plates");
    public static readonly string PipelineProfile = Path.Combine(FixtureDirectory, "fixture-pipeline-v1.json");
    public const string OcrPackA = "mavi-model-v2-3333333333333333333333333333333333333333333333333333333333333333";
    public const string OcrPackB = "mavi-model-v2-5555555555555555555555555555555555555555555555555555555555555555";
    public const string DetectorPack = "mavi-model-v2-4444444444444444444444444444444444444444444444444444444444444444";

    public static byte[] BindingBytes(bool identityB)
    {
        var binding = JsonNode.Parse(File.ReadAllText(VisualAttributeReleaseFixture.ShippedBinding))!.AsObject();
        binding["roles"]!.AsArray().Add(new JsonObject
        {
            ["roleId"] = "plates",
            ["runtimePackFamilyId"] = "mmdetection-phase1-v1",
            ["capabilityIds"] = new JsonArray("ocr", "plate-detector"),
            ["entryPoint"] = "mavi_vision.plates.main",
            ["readinessContract"] = "worker-health-v2",
            ["provenanceContract"] = PlateContractRules.ProvenanceContract,
        });
        var bindings = binding["capabilityBindings"]!.AsArray();
        bindings.Add(Bound("ocr", identityB ? OcrPackB : OcrPackA));
        bindings.Add(Bound("plate-detector", DetectorPack));
        return Encoding.UTF8.GetBytes(binding.ToJsonString() + "\n");
    }

    public static string WriteBinding(string directory, bool identityB = false)
    {
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, identityB ? "plates-binding-b.json" : "plates-binding-a.json");
        File.WriteAllBytes(path, BindingBytes(identityB));
        return path;
    }

    private static JsonObject Bound(string capabilityId, string modelPackId) => new()
    {
        ["capabilityId"] = capabilityId,
        ["roleId"] = "plates",
        ["modelPackId"] = modelPackId,
        ["qualificationId"] = capabilityId + "-fixture",
        ["enabled"] = true,
    };
}

/// <summary>
/// The real API host over a <see cref="VisualAttributeWorld"/> with the plate release (identity A or B),
/// and a client that speaks the plate control plane exactly as the worker does — capability in the header
/// only.
/// </summary>
internal sealed class PlateApiHost : IAsyncDisposable
{
    private readonly string _releaseDirectory = Path.Combine(Path.GetTempPath(), $"mavi-plate-release-{Guid.NewGuid():N}");
    private readonly IReadOnlyDictionary<string, string?>? _configuration;
    private readonly bool _kestrel;

    private PlateApiHost(VisualAttributeWorld world, IReadOnlyDictionary<string, string?>? configuration, bool kestrel)
    {
        World = world;
        _configuration = configuration;
        _kestrel = kestrel;
    }

    public VisualAttributeWorld World { get; }
    public VisionFinalizationSubmissionApiTests.CapturingLoggerProvider Logs { get; } = new();
    public ApiTestFactory Factory { get; private set; } = null!;
    public HttpClient Client { get; private set; } = null!;

    public static async Task<PlateApiHost> CreateAsync(PostgresFixture fixture, DateTimeOffset nowUtc, bool identityB = false,
        bool configured = true, IReadOnlyDictionary<string, string?>? configuration = null, bool kestrel = false)
    {
        var host = new PlateApiHost(await VisualAttributeWorld.CreateAsync(fixture, nowUtc), configuration, kestrel);
        host.Start(identityB, configured);
        return host;
    }

    /// <summary>A platform restart with another enabled binding: same database, storage and clock.</summary>
    public async Task RestartWithAsync(bool identityB, bool configured = true)
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        Start(identityB, configured);
    }

    private void Start(bool identityB, bool configured)
    {
        Factory = new ApiTestFactory
        {
            Clock = World.Clock,
            MediaRootOverride = World.MediaRoot,
            EvidenceRootOverride = World.EvidenceRoot,
            PlateComponentBindingPath = configured ? PlateReleaseFixture.WriteBinding(_releaseDirectory, identityB) : null,
            PlatePipelineProfilePath = configured ? PlateReleaseFixture.PipelineProfile : null,
            AdditionalConfiguration = _configuration,
            OverrideServices = services => services.AddSingleton<Microsoft.Extensions.Logging.ILoggerProvider>(Logs),
        };
        if (_kestrel)
        {
            Factory.UseKestrel(0);
            Factory.StartServer();
        }

        Client = Factory.CreateClient();
    }

    public Task<PlateCycleResult> RunCycleAsync() =>
        Factory.Services.GetRequiredService<PlateHostedService>().RunCycleAsync(CancellationToken.None);

    public async Task<PlateSweepResult> SweepAsync()
    {
        await using var scope = Factory.Services.CreateAsyncScope();
        var options = scope.ServiceProvider.GetRequiredService<Microsoft.Extensions.Options.IOptions<PlateOptions>>().Value;
        return await scope.ServiceProvider.GetRequiredService<IPlateLifecycle>().SweepAsync(options.LeasePolicy, options.ReconcileBatchSize, CancellationToken.None);
    }

    public async Task<PlateAnalysis> UnitAsync(Guid analysisId)
    {
        await using var db = World.Read();
        return await db.PlateAnalyses.AsNoTracking().SingleAsync(x => x.Id == analysisId);
    }

    public string PreferredFingerprint => Factory.Services.GetRequiredService<IPlateRelease>().Resolution.Definition!.Identity.Fingerprint;

    // --- Control plane --------------------------------------------------------------------

    public Task<HttpResponseMessage> PostLeaseAsync(string workerId, string? fingerprint = null) =>
        Client.PostAsJsonAsync($"{PlateContractRules.RoutePrefix}/lease", new
        {
            schemaVersion = PlateContractRules.SchemaVersion,
            workerId,
            identityFingerprint = fingerprint ?? PreferredFingerprint,
        });

    public async Task<LeasedPlateUnit> LeaseAsync(string workerId = "plates-01")
    {
        using var response = await PostLeaseAsync(workerId);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var lease = await response.Content.ReadFromJsonAsync<PlateLeaseContract>();
        var capability = Assert.Single(response.Headers.GetValues(PlateContractRules.CapabilityHeader));
        return new LeasedPlateUnit(lease!, capability, workerId);
    }

    public Task<HttpResponseMessage> HeartbeatAsync(LeasedPlateUnit unit, string? capability = null, int? attempt = null) =>
        SendJsonAsync(HttpMethod.Post, $"{PlateContractRules.RoutePrefix}/{unit.AnalysisId}/heartbeat", capability ?? unit.Capability, new
        {
            schemaVersion = PlateContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = attempt ?? unit.Attempt,
        });

    public Task<HttpResponseMessage> FailAsync(LeasedPlateUnit unit, string code, string? message = null) =>
        SendJsonAsync(HttpMethod.Post, $"{PlateContractRules.RoutePrefix}/{unit.AnalysisId}/fail", unit.Capability, new
        {
            schemaVersion = PlateContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = unit.Attempt,
            failureCode = code,
            failureMessage = message,
        });

    public Task<HttpResponseMessage> EvidenceAsync(LeasedPlateUnit unit, Guid observationId, string? capability = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{PlateContractRules.RoutePrefix}/{unit.AnalysisId}/evidence/{observationId}");
        Headers(request, capability ?? unit.Capability, unit.WorkerId, unit.Attempt);
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> UploadAsync(LeasedPlateUnit unit, byte[] bytes, string? declaredSha256 = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Put, $"{PlateContractRules.RoutePrefix}/{unit.AnalysisId}/predictions")
        {
            Content = new ByteArrayContent(bytes),
        };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue(PlateContractRules.PredictionsMediaType);
        Headers(request, unit.Capability, unit.WorkerId, unit.Attempt);
        request.Headers.Add(PlateContractRules.ContentSha256Header, declaredSha256 ?? Convert.ToHexStringLower(SHA256.HashData(bytes)));
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> CompleteAsync(LeasedPlateUnit unit, PlateCompleteRequest body, string? capability = null) =>
        SendJsonAsync(HttpMethod.Post, $"{PlateContractRules.RoutePrefix}/{unit.AnalysisId}/complete", capability ?? unit.Capability, body);

    public async Task<HttpResponseMessage> UploadAndCompleteAsync(LeasedPlateUnit unit, BuiltPlateCompletion completion)
    {
        using (var uploaded = await UploadAsync(unit, completion.Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        return await CompleteAsync(unit, completion.Request);
    }

    public Task<HttpResponseMessage> ReanalysisAsync(object body) => Client.PostAsJsonAsync("/api/plates/reanalysis", body);

    public async Task<JsonElement> ReadinessAsync(Guid runId) => await Client.GetFromJsonAsync<JsonElement>($"/api/processing/runs/{runId}/plates");

    public async Task<HttpResponseMessage> SendJsonAsync(HttpMethod method, string path, string? capability, object body)
    {
        var request = new HttpRequestMessage(method, path)
        {
            Content = new StringContent(JsonSerializer.Serialize(body, JsonSerializerOptions.Web), Encoding.UTF8, "application/json"),
        };
        if (capability is not null) request.Headers.Add(PlateContractRules.CapabilityHeader, capability);
        return await Client.SendAsync(request);
    }

    private static void Headers(HttpRequestMessage request, string? capability, string workerId, int attempt)
    {
        if (capability is not null) request.Headers.Add(PlateContractRules.CapabilityHeader, capability);
        request.Headers.Add(PlateContractRules.WorkerHeader, workerId);
        request.Headers.Add(PlateContractRules.AttemptHeader, attempt.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    /// <summary>The completion service composed exactly as the host composes it, with the reclaim-race and ambiguous-commit seams.</summary>
    public (PlateCompletionService Service, IServiceScope Scope) CompletionService(
        Func<CancellationToken, Task>? beforePhaseC = null, Func<Task>? beforeCommit = null)
    {
        var scope = Factory.Services.CreateScope();
        var services = scope.ServiceProvider;
        var service = new PlateCompletionService(
            services.GetRequiredService<MaviDbContext>(),
            services.GetRequiredService<TimeProvider>(),
            services.GetRequiredService<ILeaseCapabilityService>(),
            services.GetRequiredService<IPlateRelease>(),
            services.GetRequiredService<IPlateStagingStore>(),
            services.GetRequiredService<IAcceptedEvidenceStore>(),
            services.GetRequiredService<PlateIntegrityMonitor>(),
            services.GetRequiredService<Microsoft.Extensions.Options.IOptions<PlateOptions>>(),
            NullLogger<PlateCompletionService>.Instance)
        {
            BeforePhaseC = beforePhaseC,
            BeforeCommit = beforeCommit,
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
