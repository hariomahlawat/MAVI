using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Release;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.VisualAttributes;

/// <summary>
/// Reads the release overlay once, at first use (the host resolves it at startup), and keeps
/// the resolution for the life of the process: a binding change is a redeploy, and the
/// platform's preferred identity changes only with it (ADR-013 implementation amendment
/// 2026-09-28, item 1).
/// </summary>
public sealed class VisualAttributeReleaseSource : IVisualAttributeRelease
{
    public VisualAttributeReleaseSource(IOptions<VisualAttributeOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var configured = options.Value;
        if (string.IsNullOrWhiteSpace(configured.ComponentBindingPath))
        {
            Resolution = VisualAttributeReleaseResolution.NotConfigured("attribute_release_not_configured");
            return;
        }

        var bindingPath = Path.GetFullPath(configured.ComponentBindingPath);
        var profilePath = Path.GetFullPath(configured.PipelineProfilePath);
        var profileDirectory = Path.GetDirectoryName(profilePath)
            ?? throw new VisualAttributeReleaseException("attribute_pipeline_profile_required");
        Resolution = VisualAttributeReleaseParser.Parse(
            ReadReleaseFile(bindingPath, "component_binding_unreadable"),
            () => ReadReleaseFile(profilePath, "attribute_pipeline_profile_unreadable"),
            // The parser admits only a plain file name, so this cannot leave the directory.
            name => File.ReadAllBytes(Path.Combine(profileDirectory, name)));
    }

    public VisualAttributeReleaseResolution Resolution { get; }

    private static byte[] ReadReleaseFile(string path, string code)
    {
        try
        {
            return File.ReadAllBytes(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new VisualAttributeReleaseException(code);
        }
    }
}
