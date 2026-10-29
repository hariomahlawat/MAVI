using Mavi.Application.Modules.Embeddings;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Embeddings;

/// <summary>
/// Reads the embedding release once and keeps the resolution for the life of the process: a model or profile
/// change is a redeploy, and the preferred identity changes only with it (ADR-021 §3).
/// </summary>
public sealed class EmbeddingReleaseSource : IEmbeddingRelease
{
    public EmbeddingReleaseSource(IOptions<EmbeddingOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var configured = options.Value;
        if (!configured.IsConfigured)
        {
            Resolution = EmbeddingReleaseResolution.NotConfigured;
            return;
        }

        try
        {
            Resolution = EmbeddingReleaseParser.Parse(
                File.ReadAllBytes(Path.GetFullPath(configured.ModelManifestPath)),
                File.ReadAllBytes(Path.GetFullPath(configured.PipelineProfilePath)));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            Resolution = new EmbeddingReleaseResolution(null, "embedding_release_unreadable");
        }
    }

    public EmbeddingReleaseResolution Resolution { get; }
}
