using Microsoft.Extensions.Configuration;

namespace Mavi.Api.Startup;

public static class MachineConfigurationStartup
{
    public const string ConfigurationPathEnvironmentVariable = "MAVI_MACHINE_CONFIG";

    public static void AddMaviMachineConfiguration(this WebApplicationBuilder builder)
    {
        ArgumentNullException.ThrowIfNull(builder);

        var configuredPath = Environment.GetEnvironmentVariable(
            ConfigurationPathEnvironmentVariable);
        var path = string.IsNullOrWhiteSpace(configuredPath)
            ? GetDefaultPath(builder.Environment)
            : Path.GetFullPath(
                Environment.ExpandEnvironmentVariables(configuredPath));

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
        if (!OperatingSystem.IsWindows())
            return null;

        string root;
        string fileName;
        if (environment.IsDevelopment())
        {
            root = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            fileName = "appsettings.development.machine.json";
        }
        else if (environment.IsProduction())
        {
            root = Environment.GetFolderPath(
                Environment.SpecialFolder.CommonApplicationData);
            fileName = "appsettings.machine.json";
        }
        else
        {
            return null;
        }

        if (string.IsNullOrWhiteSpace(root))
            return null;
        return Path.Combine(root, "MAVI", "config", fileName);
    }
}
