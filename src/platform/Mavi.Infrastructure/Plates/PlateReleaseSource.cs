using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Release;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Plates;

/// <summary>
/// Reads the plate release once and keeps the resolution for the life of the process: a binding change
/// is a redeploy, and the preferred plate identity changes only with it.
/// </summary>
public sealed class PlateReleaseSource : IPlateRelease
{
    public PlateReleaseSource(IOptions<PlateOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var configured = options.Value;
        if (string.IsNullOrWhiteSpace(configured.ComponentBindingPath))
        {
            Resolution = PlateReleaseResolution.NotConfigured("plate_release_not_configured");
            return;
        }

        var bindingPath = Path.GetFullPath(configured.ComponentBindingPath);
        var profilePath = Path.GetFullPath(configured.PipelineProfilePath);
        var profileDirectory = Path.GetDirectoryName(profilePath) ?? throw new PlateReleaseException("plate_pipeline_profile_required");
        Resolution = PlateReleaseParser.Parse(
            ReadReleaseFile(bindingPath, "component_binding_unreadable"),
            () => ReadReleaseFile(profilePath, "plate_pipeline_profile_unreadable"),
            // The parser admits only a plain file name, so this cannot leave the directory.
            name => File.ReadAllBytes(Path.Combine(profileDirectory, name)));
    }

    public PlateReleaseResolution Resolution { get; }

    private static byte[] ReadReleaseFile(string path, string code)
    {
        try
        {
            return File.ReadAllBytes(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new PlateReleaseException(code);
        }
    }
}
