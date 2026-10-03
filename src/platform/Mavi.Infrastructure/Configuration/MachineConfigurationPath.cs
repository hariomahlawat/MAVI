namespace Mavi.Infrastructure.Configuration;

/// <summary>
/// Where a MAVI host's machine configuration file lives. The web host and the
/// operator tools resolve it here, so both read the one machine file (connection
/// string, storage roots) rather than each keeping its own configuration path.
/// </summary>
public static class MachineConfigurationPath
{
    public const string EnvironmentVariable = "MAVI_MACHINE_CONFIG";

    private const string Development = "Development";
    private const string Production = "Production";

    /// <summary>
    /// <c>MAVI_MACHINE_CONFIG</c> when set (environment variables expanded), otherwise
    /// the environment's default path. <see langword="null"/> when neither applies.
    /// </summary>
    public static string? Resolve(string environmentName)
    {
        var configuredPath = Environment.GetEnvironmentVariable(EnvironmentVariable);
        return string.IsNullOrWhiteSpace(configuredPath)
            ? GetDefaultPath(environmentName)
            : Path.GetFullPath(Environment.ExpandEnvironmentVariables(configuredPath));
    }

    /// <summary>The Windows default for Development and Production; <see langword="null"/> otherwise.</summary>
    public static string? GetDefaultPath(string environmentName)
    {
        if (!OperatingSystem.IsWindows())
            return null;

        var isDevelopment = string.Equals(environmentName, Development, StringComparison.OrdinalIgnoreCase);
        var isProduction = string.Equals(environmentName, Production, StringComparison.OrdinalIgnoreCase);
        if (!isDevelopment && !isProduction)
            return null;

        var commonApplicationData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
        if (isDevelopment)
            return Path.Combine(commonApplicationData, "MAVI", Development, "config", "appsettings.development.machine.json");
        return string.IsNullOrWhiteSpace(commonApplicationData)
            ? null
            : Path.Combine(commonApplicationData, "MAVI", "config", "appsettings.machine.json");
    }
}
