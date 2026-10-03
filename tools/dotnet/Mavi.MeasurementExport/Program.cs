using Mavi.Infrastructure.Configuration;
using Microsoft.Extensions.Configuration;

namespace Mavi.MeasurementExport;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        // The same machine configuration file the web host reads (MAVI_MACHINE_CONFIG or the
        // environment's default path), then environment variables, exactly as the host layers them.
        var environmentName = Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT")
            ?? Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT")
            ?? "Production";
        var builder = new ConfigurationBuilder();
        var machinePath = MachineConfigurationPath.Resolve(environmentName);
        var machineFileUsed = machinePath is not null && File.Exists(machinePath);
        if (machineFileUsed)
            builder.AddJsonFile(machinePath!, optional: false, reloadOnChange: false);
        builder.AddEnvironmentVariables();

        // Say which configuration was read, so a Production fallback on a Development host is visible.
        await Console.Out.WriteLineAsync(machineFileUsed
            ? $"configuration {environmentName}: {machinePath}"
            : $"configuration {environmentName}: no machine file ({machinePath ?? "none for this environment"}); environment variables only");

        using var cancellation = new CancellationTokenSource();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            cancellation.Cancel();
        };

        try
        {
            return await MeasurementExportCommand.RunAsync(args, builder.Build(), Console.Out, Console.Error, cancellation.Token);
        }
        catch (OperationCanceledException)
        {
            await Console.Error.WriteLineAsync("refused export_cancelled: the export was cancelled; nothing was written.");
            return MeasurementExportCommand.Refused;
        }
    }
}
