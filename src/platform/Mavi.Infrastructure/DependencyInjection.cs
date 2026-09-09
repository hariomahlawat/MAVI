using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Time;
using Mavi.Application;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Media;
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
        services.AddSingleton(TimeProvider.System);
        services.AddSingleton<ITimeZoneService, SystemTimeZoneService>();

        services.AddOptions<MediaStorageOptions>()
            .Bind(configuration.GetSection(MediaStorageOptions.SectionName))
            .Validate(options => !string.IsNullOrWhiteSpace(options.RootPath), "MediaStorage:RootPath is required.")
            .ValidateOnStart();
        services.AddOptions<MediaProcessingOptions>()
            .Bind(configuration.GetSection(MediaProcessingOptions.SectionName))
            .Validate(options => !string.IsNullOrWhiteSpace(options.FfprobePath), "MediaProcessing:FfprobePath is required.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.FfmpegPath), "MediaProcessing:FfmpegPath is required.")
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
        services.AddOptions<LocalizationOptions>()
            .Bind(configuration.GetSection(LocalizationOptions.SectionName))
            .ValidateOnStart();
        services.AddSingleton<IValidateOptions<LocalizationOptions>, LocalizationOptionsValidator>();
        services.AddSingleton<LocalMediaStore>();
        services.AddSingleton<IMediaStore>(provider => provider.GetRequiredService<LocalMediaStore>());
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
