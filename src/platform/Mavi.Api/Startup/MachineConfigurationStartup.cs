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

        var root = environment.IsDevelopment()
            ? Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData)
            : Environment.GetFolderPath(
                Environment.SpecialFolder.CommonApplicationData);

        if (string.IsNullOrWhiteSpace(root))
            return null;

        var fileName = environment.IsDevelopment()
            ? "appsettings.development.machine.json"
            : "appsettings.machine.json";
        return Path.Combine(root, "MAVI", "config", fileName);
    }
}
