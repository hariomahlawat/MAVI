using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;

namespace Mavi.Infrastructure.SceneAnalytics;

/// <summary>
/// Reads one sealed trajectory artefact for the heatmap, through the accepted-evidence
/// reader, which is the only sanctioned way into the evidence root.
/// </summary>
/// <remarks>
/// A missing artefact returns null rather than throwing, so the caller can report it
/// as the evidence-integrity failure it is for an analysed Track. Every other I/O
/// fault is a host problem and propagates.
/// <para>
/// No storage key or filesystem path ever leaves this boundary (plan §16).
/// </para>
/// </remarks>
public sealed class HeatmapEvidenceReader(IAcceptedEvidenceReader evidence) : IHeatmapEvidenceReader
{
    public async Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = await evidence.OpenReadAsync(storageKey, cancellationToken);
            using var buffer = new MemoryStream();
            await stream.CopyToAsync(buffer, cancellationToken);
            return buffer.ToArray();
        }
        catch (FileNotFoundException)
        {
            return null;
        }
        catch (DirectoryNotFoundException)
        {
            return null;
        }
    }
}
