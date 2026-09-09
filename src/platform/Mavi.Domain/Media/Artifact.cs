using System.Text.RegularExpressions;
using Mavi.Domain.Common;

namespace Mavi.Domain.Media;

public sealed partial class Artifact
{
    // Construction
    private Artifact() { }

    public static Artifact Create(
        ArtifactType artifactType,
        string storageKey,
        string mimeType,
        long sizeBytes,
        string sha256,
        string? metadataJson = null,
        DateTimeOffset? createdAtUtc = null)
    {
        ValidateStorageKey(storageKey);
        if (string.IsNullOrWhiteSpace(mimeType) || mimeType.Trim().Length > 128)
        {
            throw new DomainValidationException("artifact_mime_type_invalid", "A valid MIME type is required.");
        }

        if (sizeBytes < 0)
        {
            throw new DomainValidationException("artifact_size_invalid", "Artifact size cannot be negative.");
        }

        if (sha256 is null || !Sha256Pattern().IsMatch(sha256))
        {
            throw new DomainValidationException("artifact_sha256_invalid", "SHA-256 must be 64 lowercase hexadecimal characters.");
        }

        return new Artifact
        {
            Id = Guid.CreateVersion7(),
            ArtifactType = artifactType,
            StorageKey = storageKey,
            MimeType = mimeType.Trim(),
            SizeBytes = sizeBytes,
            Sha256 = sha256,
            MetadataJson = metadataJson,
            CreatedAtUtc = (createdAtUtc ?? DateTimeOffset.UtcNow).ToUniversalTime(),
        };
    }

    // Properties
    public Guid Id { get; private set; }
    public ArtifactType ArtifactType { get; private set; }
    public string StorageKey { get; private set; } = string.Empty;
    public string MimeType { get; private set; } = string.Empty;
    public long SizeBytes { get; private set; }
    public string Sha256 { get; private set; } = string.Empty;
    public string? MetadataJson { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }

    // Validation
    private static void ValidateStorageKey(string storageKey)
    {
        if (string.IsNullOrWhiteSpace(storageKey) || storageKey.Length > 512 ||
            storageKey.StartsWith('/') || storageKey.Contains('\\') || storageKey.Contains(':') ||
            storageKey.Split('/').Any(segment => segment is ".." or "." or ""))
        {
            throw new DomainValidationException("artifact_storage_key_invalid", "Storage key must be a safe relative slash-separated path.");
        }
    }

    [GeneratedRegex("^[0-9a-f]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex Sha256Pattern();
}
