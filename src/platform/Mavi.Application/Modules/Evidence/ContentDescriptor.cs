using Mavi.Domain.Media;

namespace Mavi.Application.Modules.Evidence;

public enum ContentStorageKind
{
    ManagedMedia,
    AcceptedEvidence,
}

public sealed record ContentDescriptor(
    Guid ArtifactId,
    ArtifactType ArtifactType,
    string StorageKey,
    string MimeType,
    long SizeBytes,
    string Sha256,
    ContentStorageKind StorageKind);


public sealed record VideoContentLookup(
    bool VideoExists,
    ContentDescriptor? Descriptor);
