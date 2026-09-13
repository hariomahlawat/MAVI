using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class AcceptedEvidenceLeafSafetyTests : IDisposable
{
    private readonly string _mediaRoot =
        Path.Combine(Path.GetTempPath(), $"mavi-leaf-media-{Guid.NewGuid():N}");
    private readonly string _evidenceRoot =
        Path.Combine(Path.GetTempPath(), $"mavi-leaf-evidence-{Guid.NewGuid():N}");

    [Fact]
    public async Task LinkedStagingLeafIsRejectedBeforeEvidenceIsSealed()
    {
        var options = Options.Create(new MediaStorageOptions
        {
            RootPath = _mediaRoot,
            EvidenceRootPath = _evidenceRoot,
        });
        var mediaStore = new LocalMediaStore(options);
        var target = await mediaStore.WriteAsync(
            "legacy/earlier.jpg",
            new MemoryStream(Encoding.UTF8.GetBytes("earlier-attempt-evidence")),
            CancellationToken.None);

        var targetPath = Path.Combine(_mediaRoot, "legacy", "earlier.jpg");
        var linkedLeaf = Path.Combine(
            _mediaRoot,
            "staging",
            "job",
            "attempt-0001",
            "thumbnails",
            "person-000001.jpg");
        Directory.CreateDirectory(Path.GetDirectoryName(linkedLeaf)!);
        try
        {
            try
            {
                File.CreateSymbolicLink(linkedLeaf, targetPath);
            }
            catch (Exception exception) when (
                exception is PlatformNotSupportedException or UnauthorizedAccessException or IOException)
            {
                return;
            }

            var sealer = new AcceptedEvidenceStore(mediaStore, options);
            var acceptedKey =
                $"evidence/job/attempt-0001/thumbnails/person-000001-{target.Sha256}.jpg";

            var result = await sealer.SealAsync(
                "staging/job/attempt-0001/thumbnails/person-000001.jpg",
                acceptedKey,
                target.SizeBytes,
                target.Sha256,
                CancellationToken.None);

            Assert.Equal(AcceptedEvidenceSealStatus.IntegrityMismatch, result.Status);
            Assert.False(File.Exists(EvidencePath(acceptedKey)));
        }
        finally
        {
            if (File.Exists(linkedLeaf)) File.Delete(linkedLeaf);
        }
    }

    public void Dispose()
    {
        if (Directory.Exists(_mediaRoot)) Directory.Delete(_mediaRoot, true);
        if (Directory.Exists(_evidenceRoot))
        {
            foreach (var file in Directory.GetFiles(_evidenceRoot, "*", SearchOption.AllDirectories))
                File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(_evidenceRoot, true);
        }
        GC.SuppressFinalize(this);
    }

    private string EvidencePath(string storageKey) =>
        Path.Combine(
            _evidenceRoot,
            storageKey["evidence/".Length..]
                .Replace('/', Path.DirectorySeparatorChar));
}
