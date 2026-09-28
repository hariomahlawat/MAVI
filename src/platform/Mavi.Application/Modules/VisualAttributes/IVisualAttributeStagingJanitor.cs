namespace Mavi.Application.Modules.VisualAttributes;

/// <summary>
/// Reclaims <c>staging-attributes/{analysisId}/attempt-NNNN</c> directories that the
/// VisualAttributeAnalysis row proves dead (S2b plan §12). Its authority is that row alone;
/// it never opens the VisionJob staging tree or the accepted-evidence root.
/// </summary>
public interface IVisualAttributeStagingJanitor
{
    /// <summary>One cycle; returns the number of attempt directories removed.</summary>
    Task<int> RunCycleAsync(CancellationToken cancellationToken);
}
