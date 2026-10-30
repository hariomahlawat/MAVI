using Mavi.Application.Modules.Faces;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Faces;

/// <summary>
/// Reads the face release once and keeps the resolution for the life of the process: a model or profile
/// change is a redeploy, and the preferred identity changes only with it (ADR-022 §3).
/// </summary>
public sealed class FaceReleaseSource : IFaceRelease
{
    public FaceReleaseSource(IOptions<FaceOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var configured = options.Value;
        if (!configured.IsConfigured)
        {
            Resolution = FaceReleaseResolution.NotConfigured;
            return;
        }

        try
        {
            Resolution = FaceReleaseParser.Parse(
                File.ReadAllBytes(Path.GetFullPath(configured.ModelManifestPath)),
                File.ReadAllBytes(Path.GetFullPath(configured.PipelineProfilePath)));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            Resolution = new FaceReleaseResolution(null, "face_release_unreadable");
        }
    }

    public FaceReleaseResolution Resolution { get; }
}
