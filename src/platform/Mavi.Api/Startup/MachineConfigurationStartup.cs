using Mavi.Infrastructure.Configuration;
using Microsoft.Extensions.Configuration;

namespace Mavi.Api.Startup;

public static class MachineConfigurationStartup
{
    public const string ConfigurationPathEnvironmentVariable = MachineConfigurationPath.EnvironmentVariable;

    public static void AddMaviMachineConfiguration(this WebApplicationBuilder builder)
    {
        ArgumentNullException.ThrowIfNull(builder);

        var path = MachineConfigurationPath.Resolve(builder.Environment.EnvironmentName);
        if (path is null || !File.Exists(path))
            return;

        builder.Configuration.AddJsonFile(
            path,
            optional: false,
            reloadOnChange: false);

        // Environment variables remain the final machine-level override.
        builder.Configuration.AddEnvironmentVariables();
    }

    public static string? GetDefaultPath(IHostEnvironment environment)
    {
        ArgumentNullException.ThrowIfNull(environment);
        return MachineConfigurationPath.GetDefaultPath(environment.EnvironmentName);
    }
}
