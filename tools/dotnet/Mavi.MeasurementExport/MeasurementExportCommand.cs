using Mavi.Infrastructure.Measurement;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.MeasurementExport;

/// <summary>
/// <c>Mavi.MeasurementExport --run &lt;guid&gt; --pipeline-profile &lt;file&gt; --out &lt;new-dir&gt;</c>.
/// Exit 0 with the export identity on success; exit 2, a stable code and no output
/// directory on any refusal or failure.
/// </summary>
public static class MeasurementExportCommand
{
    public const int Success = 0;
    public const int Refused = 2;
    public const string UsageInvalid = "export_usage_invalid";
    public const string ConfigurationInvalid = "export_configuration_invalid";
    public const string Failed = "export_failed";

    private const string Usage = "usage: Mavi.MeasurementExport --run <guid> --pipeline-profile <file> --out <new-dir>";

    public static async Task<int> RunAsync(
        IReadOnlyList<string> args,
        IConfiguration configuration,
        TextWriter output,
        TextWriter error,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(args);
        ArgumentNullException.ThrowIfNull(configuration);
        ArgumentNullException.ThrowIfNull(output);
        ArgumentNullException.ThrowIfNull(error);

        if (!TryParse(args, out var runId, out var profilePath, out var outputDirectory))
            return await RefuseAsync(error, UsageInvalid, Usage);

        ServiceProvider provider;
        try
        {
            provider = new ServiceCollection()
                .AddMaviMeasurementExport(configuration)
                .BuildServiceProvider(new ServiceProviderOptions { ValidateScopes = true, ValidateOnBuild = true });
        }
        catch (Exception exception) when (exception is InvalidOperationException or AggregateException)
        {
            return await RefuseAsync(error, ConfigurationInvalid, exception.Message);
        }

        await using (provider)
        {
            try
            {
                await using var scope = provider.CreateAsyncScope();
                var exporter = scope.ServiceProvider.GetRequiredService<SubclassMeasurementExporter>();
                var result = await exporter.RunAsync(runId, profilePath, outputDirectory, cancellationToken);
                await output.WriteLineAsync($"exportSha256 {result.ExportSha256}");
                await output.WriteLineAsync($"tracks {result.TrackCount}; evidence files {result.EvidenceFileCount}");
                await output.WriteLineAsync($"written {result.OutputDirectory}");
                return Success;
            }
            catch (SubclassMeasurementExportException exception)
            {
                return await RefuseAsync(error, exception.Code, exception.Message);
            }
            catch (OptionsValidationException exception)
            {
                return await RefuseAsync(error, ConfigurationInvalid, exception.Message);
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                // A database or file-system failure: the export wrote nothing, so this is a refusal too.
                return await RefuseAsync(error, Failed, exception.Message);
            }
        }
    }

    private static bool TryParse(
        IReadOnlyList<string> args,
        out Guid runId,
        out string profilePath,
        out string outputDirectory)
    {
        runId = Guid.Empty;
        profilePath = string.Empty;
        outputDirectory = string.Empty;
        if (args.Count != 6)
            return false;

        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < args.Count; index += 2)
        {
            if (args[index] is not ("--run" or "--pipeline-profile" or "--out") ||
                string.IsNullOrWhiteSpace(args[index + 1]) ||
                !values.TryAdd(args[index], args[index + 1]))
                return false;
        }

        if (!Guid.TryParseExact(values["--run"], "D", out runId) || runId == Guid.Empty)
            return false;
        profilePath = values["--pipeline-profile"];
        outputDirectory = values["--out"];
        return true;
    }

    private static async Task<int> RefuseAsync(TextWriter error, string code, string message)
    {
        await error.WriteLineAsync($"refused {code}: {message}");
        return Refused;
    }
}
