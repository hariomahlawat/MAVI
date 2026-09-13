namespace Mavi.Infrastructure.Storage;

public sealed class MediaStorageOptions
{
    public const string SectionName = "MediaStorage";

    /// <summary>
    /// Shared managed-media root used for source media and worker attempt staging.
    /// </summary>
    public string RootPath { get; init; } = string.Empty;

    /// <summary>
    /// Platform-owned root for accepted immutable evidence. Production deployment
    /// must grant the worker no write access to this root.
    /// </summary>
    public string EvidenceRootPath { get; init; } = string.Empty;
}
