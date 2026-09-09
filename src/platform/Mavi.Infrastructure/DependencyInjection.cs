using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure.Media;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.Storage;
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
            .Validate(options => options.AllowedExtensions is { Length: > 0 } &&
                options.AllowedExtensions.All(IsValidExtension),
                "VideoImport:AllowedExtensions must contain normalized extensions such as '.mp4'.")
            .ValidateOnStart();
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
