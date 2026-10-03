using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.Infrastructure.Measurement;

/// <summary>
/// The read-only measurement export's registrations, for the operator tool. It uses the
/// platform's own database context and storage readers with the same configuration
/// contract as the web host, and nothing else: no hosted services, no writers.
/// </summary>
public static class MeasurementExportRegistration
{
    public static IServiceCollection AddMaviMeasurementExport(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configuration);

        services.AddMaviDbContext(configuration);
        services.AddMediaStorageOptions(configuration);
        services.AddSingleton<LocalMediaStore>();
        services.AddSingleton<IMediaStore>(provider => provider.GetRequiredService<LocalMediaStore>());
        services.AddSingleton<IAcceptedEvidenceReader, AcceptedEvidenceReader>();
        services.AddSingleton<VisionRuntimeProvenanceParser>();
        services.AddScoped<SubclassMeasurementExporter>();
        return services;
    }
}
