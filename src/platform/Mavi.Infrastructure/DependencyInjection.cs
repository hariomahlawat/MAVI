using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Time;
using Mavi.Application;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Evidence;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Media;
using Mavi.Infrastructure.Security;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.Storage;
using Mavi.Infrastructure.Time;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddMaviInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configuration);

        var connectionString = configuration.GetConnectionString("Mavi")
            ?? throw new InvalidOperationException("Connection string 'Mavi' is required.");
        services.AddDbContext<MaviDbContext>(options =>
            options.UseNpgsql(connectionString, npgsql => npgsql.UseVector()));
        services.AddScoped<ICameraRepository, CameraRepository>();
        services.AddScoped<CameraService>();
        services.AddScoped<IVideoCatalog, VideoCatalog>();
        services.AddScoped<VideoImportService>();
        services.AddScoped<IProcessingOrchestrator, ProcessingOrchestrator>();
        services.AddScoped<IProcessingResultStore, ProcessingResultStore>();
        services.AddScoped<ITrackSearchRepository, TrackSearchRepository>();
        services.AddScoped<TrackSearchService>();
        services.AddScoped<ISceneConfigurationRepository, SceneConfigurationRepository>();
        services.AddScoped<SceneConfigurationService>();
        services.AddScoped<ISceneAnalysisLifecycle, SceneAnalysisLifecycle>();
        services.AddScoped<ISceneAnalysisEvidenceReader, SceneAnalysisEvidenceReader>();
        services.AddScoped<SceneAnalysisExecutor>();
        services.AddScoped<ISceneAnalyticsStatusReader, SceneAnalyticsStatusReader>();
        services.AddScoped<SceneAnalyticsStatusService>();
        services.AddScoped<IContentCatalog, ContentCatalog>();
        services.AddScoped<ContentReadService>();
        services.AddSingleton<VisionRuntimeProvenanceParser>();
        services.AddSingleton<VisionResultValidator>();
        services.AddSingleton<ILeaseCapabilityService, LeaseCapabilityService>();
        services.AddSingleton(TimeProvider.System);
        services.AddSingleton<ITimeZoneService, SystemTimeZoneService>();

        services.AddOptions<MediaStorageOptions>()
            .Bind(configuration.GetSection(MediaStorageOptions.SectionName))
            .Validate(options => !string.IsNullOrWhiteSpace(options.RootPath), "MediaStorage:RootPath is required.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.EvidenceRootPath), "MediaStorage:EvidenceRootPath is required.")
            .Validate(options => StorageRootSafety.AreDisjointAndLinkFree(options.RootPath, options.EvidenceRootPath),
                "MediaStorage roots must be physically disjoint and may not traverse symbolic-link/reparse components.")
            .ValidateOnStart();
        services.AddOptions<MediaProcessingOptions>()
            .Bind(configuration.GetSection(MediaProcessingOptions.SectionName))
            .Validate(options => !string.IsNullOrWhiteSpace(options.FfprobePath), "MediaProcessing:FfprobePath is required.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.FfmpegPath), "MediaProcessing:FfmpegPath is required.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.BundledRootPath),
                "MediaProcessing:BundledRootPath is required.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.BundledManifestPath),
                "MediaProcessing:BundledManifestPath is required.")
            .Validate(options => options.ProbeTimeoutSeconds is >= 1 and <= 300,
                "MediaProcessing:ProbeTimeoutSeconds must be between 1 and 300.")
            .ValidateOnStart();
        services.AddOptions<VideoImportOptions>()
            .Bind(configuration.GetSection(VideoImportOptions.SectionName))
            .Validate(options => options.MaximumFileSizeBytes > 0, "VideoImport:MaximumFileSizeBytes must be positive.")
            .Validate(options => options.MultipartOverheadBytes > 0 &&
                options.MaximumFileSizeBytes <= long.MaxValue - options.MultipartOverheadBytes,
                "VideoImport:MultipartOverheadBytes must be positive and the request limit must not overflow.")
            .Validate(options => options.AllowedExtensions is { Length: > 0 } &&
                options.AllowedExtensions.All(IsValidExtension),
                "VideoImport:AllowedExtensions must contain normalized extensions such as '.mp4'.")
            .ValidateOnStart();
        services.AddOptions<VisionProcessingOptions>()
            .Bind(configuration.GetSection(VisionProcessingOptions.SectionName))
            .Validate(x => !string.IsNullOrWhiteSpace(x.Pipeline) && x.Pipeline.Length <= 64,
                "VisionProcessing:Pipeline is required and limited to 64 characters.")
            .Validate(x => !string.IsNullOrWhiteSpace(x.PipelineVersion) && x.PipelineVersion.Length <= 64,
                "VisionProcessing:PipelineVersion is required and limited to 64 characters.")
            .Validate(x => x.MaximumAttempts is >= 1 and <= 100, "VisionProcessing:MaximumAttempts must be between 1 and 100.")
            .Validate(x => x.LeaseSeconds is >= 1 and <= 86400, "VisionProcessing:LeaseSeconds must be between 1 and 86400.")
            .Validate(x => x.HeartbeatExtensionSeconds is >= 1 and <= 86400,
                "VisionProcessing:HeartbeatExtensionSeconds must be between 1 and 86400.")
            .ValidateOnStart();
        services.AddSceneAnalyticsOptions(configuration);
        services.AddOptions<LocalizationOptions>()
            .Bind(configuration.GetSection(LocalizationOptions.SectionName))
            .ValidateOnStart();
        services.AddSingleton<IValidateOptions<LocalizationOptions>, LocalizationOptionsValidator>();
        services.AddSingleton<LocalMediaStore>();
        services.AddSingleton<IMediaStore>(provider => provider.GetRequiredService<LocalMediaStore>());
        services.AddSingleton<IAcceptedEvidenceStore, AcceptedEvidenceStore>();
        services.AddSingleton<IAcceptedEvidenceReader, AcceptedEvidenceReader>();
        services.AddSingleton<ILocalMediaPathResolver>(provider => provider.GetRequiredService<LocalMediaStore>());
        services.AddSingleton<IVideoMetadataReader, FfprobeVideoMetadataReader>();
        return services;
    }

    private static bool IsValidExtension(string extension) =>
        !string.IsNullOrWhiteSpace(extension) && extension[0] == '.' &&
        string.Equals(extension, extension.Trim(), StringComparison.Ordinal) &&
        string.Equals(extension, extension.ToLowerInvariant(), StringComparison.Ordinal) &&
        extension.IndexOfAny(['/', '\\']) < 0;

}

internal sealed class LocalizationOptionsValidator(ITimeZoneService timeZones) : IValidateOptions<LocalizationOptions>
{
    public ValidateOptionsResult Validate(string? name, LocalizationOptions options) =>
        timeZones.IsValidIanaTimeZoneId(options.DefaultDisplayTimeZoneId)
            ? ValidateOptionsResult.Success
            : ValidateOptionsResult.Fail("Localization:DefaultDisplayTimeZoneId must be a recognized IANA timezone ID.");
}

/// <summary>
/// The analytics host's configuration contract, registered separately so that the rules
/// themselves can be exercised by a test rather than restated in one.
/// </summary>
public static class SceneAnalyticsOptionsRegistration
{
    public static IServiceCollection AddSceneAnalyticsOptions(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(services);
        services.AddOptions<SceneAnalyticsOptions>()
            .Bind(configuration.GetSection(SceneAnalyticsOptions.SectionName))
            .Validate(x => x.ReconcileIntervalSeconds is >= 1 and <= 3600,
                "SceneAnalytics:ReconcileIntervalSeconds must be between 1 and 3600.")
            .Validate(x => x.LeaseSeconds is >= 1 and <= 86400,
                "SceneAnalytics:LeaseSeconds must be between 1 and 86400.")
            .Validate(x => x.MaxUnitDurationSeconds is >= 1 and <= 86400,
                "SceneAnalytics:MaxUnitDurationSeconds must be between 1 and 86400.")
            .Validate(x => x.ReclaimGraceSeconds is >= 0 and <= 86400,
                "SceneAnalytics:ReclaimGraceSeconds must be between 0 and 86400.")
            .Validate(x => x.MaximumAttempts is >= 1 and <= 100,
                "SceneAnalytics:MaximumAttempts must be between 1 and 100.")
            // Pinned rather than ranged: the host executes units in turn, so a larger
            // value would promise concurrency the implementation does not provide.
            .Validate(x => x.MaxConcurrentUnits == 1,
                "SceneAnalytics:MaxConcurrentUnits must be 1; the host executes one unit per cycle in v1.")
            .Validate(x => x.ReconcileBatchSize is >= 1 and <= 1000,
                "SceneAnalytics:ReconcileBatchSize must be between 1 and 1000.")
            .Validate(x => x.ReconcileLookbackDays is >= 0 and <= 3650,
                "SceneAnalytics:ReconcileLookbackDays must be between 0 and 3650.")
            // There is no heartbeat in v1, so the lease is the only thing between a slow
            // attempt and being reclaimed underneath itself. Refusing the configuration
            // is better than shipping a fence that fails intermittently under load.
            .Validate(x => x.LeaseSeconds >= 2 * x.MaxUnitDurationSeconds,
                "SceneAnalytics:LeaseSeconds must be at least twice MaxUnitDurationSeconds.")
            .ValidateOnStart();
        return services;
    }
}
