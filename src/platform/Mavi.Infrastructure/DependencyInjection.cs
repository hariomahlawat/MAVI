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

        var mediaRoot = configuration[$"{MediaStorageOptions.SectionName}:RootPath"]
            ?? throw new InvalidOperationException("MediaStorage:RootPath is required.");
        var ffprobePath = configuration[$"{MediaProcessingOptions.SectionName}:FfprobePath"] ?? "ffprobe";
        services.Configure<MediaStorageOptions>(options => options.RootPath = mediaRoot);
        services.Configure<MediaProcessingOptions>(options => options.FfprobePath = ffprobePath);
        services.AddSingleton<LocalMediaStore>();
        services.AddSingleton<IMediaStore>(provider => provider.GetRequiredService<LocalMediaStore>());
        services.AddSingleton<IVideoMetadataReader, FfprobeVideoMetadataReader>();
        return services;
    }
}
