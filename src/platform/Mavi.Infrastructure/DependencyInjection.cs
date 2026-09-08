using Microsoft.Extensions.DependencyInjection;

namespace Mavi.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddMaviInfrastructure(this IServiceCollection services)
    {
        ArgumentNullException.ThrowIfNull(services);
        return services;
    }
}
