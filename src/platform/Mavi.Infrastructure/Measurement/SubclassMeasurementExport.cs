namespace Mavi.Infrastructure.Measurement;

/// <summary>
/// One completed run's verified measurement export, before it is written: the canonical
/// export JSON, its identity, and the Evidence Set files the JSON names.
/// </summary>
public sealed record SubclassMeasurementExport(
    byte[] Json,
    string ExportSha256,
    IReadOnlyList<SubclassMeasurementExportEvidence> Evidence);

/// <summary>An evidence file the export carries, by content identity; the storage key is where it is read from.</summary>
public sealed record SubclassMeasurementExportEvidence(
    string Sha256,
    long SizeBytes,
    string StorageKey);

/// <summary>A written export: its directory and identity.</summary>
public sealed record SubclassMeasurementExportResult(
    string OutputDirectory,
    string ExportSha256,
    int TrackCount,
    int EvidenceFileCount);
