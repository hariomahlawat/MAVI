using System.Security;
using Mavi.Infrastructure.Configuration;
using Microsoft.Extensions.Configuration;

namespace Mavi.MeasurementExport;

/// <summary>
/// The tool's whole entry boundary: environment and machine-configuration resolution,
/// then <see cref="MeasurementExportCommand"/>. Configuration failures are refusals
/// (exit 2, <c>export_configuration_invalid</c>, nothing written), like every other.
/// </summary>
public static class MeasurementExportProgram
{
    public const string DotnetEnvironmentVariable = "DOTNET_ENVIRONMENT";
    public const string AspNetCoreEnvironmentVariable = "ASPNETCORE_ENVIRONMENT";
    public const string DefaultEnvironment = "Production";

    /// <summary>
    /// The web host's effective environment: <c>WebApplication.CreateBuilder</c> lets
    /// <c>DOTNET_ENVIRONMENT</c> win over <c>ASPNETCORE_ENVIRONMENT</c>, and defaults to Production.
    /// </summary>
    public static string ResolveEnvironmentName()
    {
        var dotnet = Environment.GetEnvironmentVariable(DotnetEnvironmentVariable);
        if (!string.IsNullOrEmpty(dotnet))
            return dotnet;
        var aspNetCore = Environment.GetEnvironmentVariable(AspNetCoreEnvironmentVariable);
        return string.IsNullOrEmpty(aspNetCore) ? DefaultEnvironment : aspNetCore;
    }

    public static async Task<int> RunAsync(
        IReadOnlyList<string> args,
        TextWriter output,
        TextWriter error,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(args);
        ArgumentNullException.ThrowIfNull(output);
        ArgumentNullException.ThrowIfNull(error);

        var environmentName = ResolveEnvironmentName();
        IConfiguration configuration;
        string source;
        try
        {
            configuration = BuildConfiguration(environmentName, out source);
        }
        // Path resolution and file-provider loading failures only; a malformed JSON file
        // surfaces as InvalidDataException from the provider.
        catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException
                                              or ArgumentException or NotSupportedException or SecurityException)
        {
            await error.WriteLineAsync(
                $"refused {MeasurementExportCommand.ConfigurationInvalid}: the machine configuration cannot be loaded: {exception.Message}");
            return MeasurementExportCommand.Refused;
        }

        // Say which configuration was read, so a Production fallback on a Development host is visible.
        await output.WriteLineAsync($"configuration {environmentName}: {source}");
        return await MeasurementExportCommand.RunAsync(args, configuration, output, error, cancellationToken);
    }

    /// <summary>
    /// The same layering as the web host: the machine file, then environment variables.
    /// A file named explicitly by <c>MAVI_MACHINE_CONFIG</c> must exist; a missing default
    /// file is skipped, as the host skips it.
    /// </summary>
    private static IConfiguration BuildConfiguration(string environmentName, out string source)
    {
        var explicitPath = !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(MachineConfigurationPath.EnvironmentVariable));
        var machinePath = MachineConfigurationPath.Resolve(environmentName);
        var builder = new ConfigurationBuilder();
        if (machinePath is not null && File.Exists(machinePath))
        {
            builder.AddJsonFile(machinePath, optional: false, reloadOnChange: false);
            source = machinePath;
        }
        else if (explicitPath)
        {
            throw new FileNotFoundException(
                $"{MachineConfigurationPath.EnvironmentVariable} names a file that does not exist: {machinePath}");
        }
        else
        {
            source = $"no machine file ({machinePath ?? "none for this environment"}); environment variables only";
        }

        builder.AddEnvironmentVariables();
        return builder.Build();
    }
}
