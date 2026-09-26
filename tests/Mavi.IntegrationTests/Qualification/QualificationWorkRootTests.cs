using System.Security.Cryptography;
using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The B3 harnesses' cleanup of their own work roots, which hold accepted evidence the
/// product sealed read-only. The M2R Windows B3-B run died in its cleanup with
/// <see cref="UnauthorizedAccessException"/> on a sealed <c>.jpg</c>: Windows refuses to
/// delete a read-only file, and the harnesses deleted with a raw recursive delete.
/// </summary>
public sealed class QualificationWorkRootTests : IDisposable
{
    private readonly string _base = Path.Combine(Path.GetTempPath(), $"mavi-workroot-{Guid.NewGuid():N}");

    public QualificationWorkRootTests() => Directory.CreateDirectory(_base);

    public void Dispose()
    {
        if (Directory.Exists(_base)) QualificationWorkRoot.Delete(_base);
    }

    private string ReadOnlyFile(string relative, string content = "sealed")
    {
        var path = Path.Combine(_base, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, content);
        File.SetAttributes(path, File.GetAttributes(path) | FileAttributes.ReadOnly);
        Assert.True(File.GetAttributes(path).HasFlag(FileAttributes.ReadOnly));
        return path;
    }

    private static List<string> ReadOnlyBeneath(string root) =>
        new DirectoryInfo(root)
            .EnumerateFileSystemInfos("*", new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = 0 })
            .Where(entry => entry.Attributes.HasFlag(FileAttributes.ReadOnly))
            .Select(entry => entry.FullName)
            .ToList();

    /// <summary>Deletes as Windows does: a read-only file under the root is refused.</summary>
    private static void DeleteLikeWindows(string root, bool recursive)
    {
        var readOnly = ReadOnlyBeneath(root);
        if (readOnly.Count > 0) throw new UnauthorizedAccessException($"Access to the path '{readOnly[0]}' is denied.");
        Directory.Delete(root, recursive);
    }

    [Fact]
    public void ARawRecursiveDeleteOfSealedEvidenceIsRefusedOnWindows()
    {
        // The M2R defect, where the OS enforces it; elsewhere the Windows rule is
        // modelled by DeleteLikeWindows, which the helper's tests below use.
        var root = Path.Combine(_base, "raw");
        ReadOnlyFile(Path.Combine("raw", "evidence", "job", "person-000001.jpg"));
        if (OperatingSystem.IsWindows())
            Assert.Throws<UnauthorizedAccessException>(() => Directory.Delete(root, recursive: true));
        Assert.Throws<UnauthorizedAccessException>(() => DeleteLikeWindows(root, true));
    }

    [Fact]
    public void AWorkRootHoldingReadOnlyFilesIsDeleted()
    {
        var root = Path.Combine(_base, "work");
        ReadOnlyFile(Path.Combine("work", "evidence", "person-000001.jpg"));
        QualificationWorkRoot.Delete(root, DeleteLikeWindows);
        Assert.False(Directory.Exists(root));
        // And on the real OS delete, whatever the platform.
        ReadOnlyFile(Path.Combine("work2", "evidence", "person-000002.jpg"));
        QualificationWorkRoot.Delete(Path.Combine(_base, "work2"));
        Assert.False(Directory.Exists(Path.Combine(_base, "work2")));
    }

    [Fact]
    public void NormalFilesStillDelete()
    {
        var root = Path.Combine(_base, "normal");
        Directory.CreateDirectory(Path.Combine(root, "media", "staging"));
        File.WriteAllText(Path.Combine(root, "media", "staging", "a.bin"), "a");
        File.WriteAllText(Path.Combine(root, "b.txt"), "b");
        QualificationWorkRoot.Delete(root, DeleteLikeWindows);
        Assert.False(Directory.Exists(root));
    }

    [Fact]
    public void NestedReadOnlyFilesAndDirectoriesDelete()
    {
        var root = Path.Combine(_base, "nested");
        foreach (var depth in Enumerable.Range(1, 6))
            ReadOnlyFile(Path.Combine(["nested", .. Enumerable.Range(1, depth).Select(i => $"d{i}"), $"f{depth}.jpg"]));
        // A hidden read-only file too: the default enumeration skips hidden entries.
        var hidden = ReadOnlyFile(Path.Combine("nested", "d1", ".hidden.jpg"));
        if (OperatingSystem.IsWindows()) File.SetAttributes(hidden, File.GetAttributes(hidden) | FileAttributes.Hidden);
        var directory = Path.Combine(root, "d1", "d2");
        File.SetAttributes(directory, File.GetAttributes(directory) | FileAttributes.ReadOnly);
        Assert.NotEmpty(ReadOnlyBeneath(root));
        QualificationWorkRoot.Delete(root, DeleteLikeWindows);
        Assert.False(Directory.Exists(root));
    }

    [Fact]
    public void OnlyTheReadOnlyAttributeIsCleared()
    {
        var root = Path.Combine(_base, "attributes");
        var hidden = ReadOnlyFile(Path.Combine("attributes", ".sealed.jpg"));
        if (OperatingSystem.IsWindows()) File.SetAttributes(hidden, File.GetAttributes(hidden) | FileAttributes.Hidden);
        var before = File.GetAttributes(hidden);
        Assert.True(before.HasFlag(FileAttributes.Hidden));
        QualificationWorkRoot.Delete(root, (path, _) =>
        {
            // At the moment of deletion: read-only cleared, every other attribute kept.
            Assert.Equal(before & ~FileAttributes.ReadOnly, File.GetAttributes(hidden));
        });
        Assert.True(File.Exists(hidden));
    }

    [Fact]
    public void AnUnexpectedDeletionFailureIsNotSwallowed()
    {
        var root = Path.Combine(_base, "failing");
        ReadOnlyFile(Path.Combine("failing", "evidence", "person-000001.jpg"));
        var thrown = Assert.Throws<IOException>(() =>
            QualificationWorkRoot.Delete(root, (_, _) => throw new IOException("The process cannot access the file because it is being used by another process.")));
        Assert.Contains("being used", thrown.Message, StringComparison.Ordinal);
        Assert.True(Directory.Exists(root));
    }

    [Fact]
    public void ARealLockedFileFailsTheCleanupOnWindows()
    {
        if (!OperatingSystem.IsWindows()) return; // an open file does not block unlink elsewhere
        var root = Path.Combine(_base, "locked");
        var path = ReadOnlyFile(Path.Combine("locked", "evidence", "person-000001.jpg"));
        using var held = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None);
        Assert.ThrowsAny<IOException>(() => QualificationWorkRoot.Delete(root));
        Assert.True(File.Exists(path));
    }

    [Fact]
    public void AWorkRootThatIsAFileIsRefusedAndAnAbsentOneIsNothing()
    {
        var file = Path.Combine(_base, "not-a-directory");
        File.WriteAllText(file, "x");
        Assert.Throws<IOException>(() => QualificationWorkRoot.Delete(file));
        Assert.Throws<IOException>(() => QualificationWorkRoot.Empty(file));
        Assert.True(File.Exists(file));
        QualificationWorkRoot.Delete(Path.Combine(_base, "absent"));
        Assert.Throws<DirectoryNotFoundException>(() => QualificationWorkRoot.Empty(Path.Combine(_base, "absent")));
    }

    [Fact]
    public void ALinkIsNeitherFollowedNorModified()
    {
        var outside = Path.Combine(_base, "outside");
        var target = ReadOnlyFile(Path.Combine("outside", "product-evidence.jpg"));
        var root = Path.Combine(_base, "linked");
        Directory.CreateDirectory(root);
        string link = Path.Combine(root, "link");
        try
        {
            Directory.CreateSymbolicLink(link, outside);
        }
        catch (Exception exception) when (OperatingSystem.IsWindows() && exception is IOException or UnauthorizedAccessException)
        {
            return; // symbolic links need a privilege this Windows account lacks
        }
        QualificationWorkRoot.Delete(root);
        Assert.False(Directory.Exists(root));
        Assert.True(File.Exists(target));
        Assert.True(File.GetAttributes(target).HasFlag(FileAttributes.ReadOnly));
        // A root that is itself a link is refused, and its target is untouched.
        var rootLink = Path.Combine(_base, "root-link");
        Directory.CreateSymbolicLink(rootLink, outside);
        Assert.Throws<IOException>(() => QualificationWorkRoot.Delete(rootLink));
        Assert.Throws<IOException>(() => QualificationWorkRoot.Empty(rootLink));
        Assert.True(File.GetAttributes(target).HasFlag(FileAttributes.ReadOnly));
        Directory.Delete(rootLink);
    }

    [Fact]
    public void EmptyClearsTheRootOfReadOnlyEvidenceAndKeepsIt()
    {
        var root = Path.Combine(_base, "per-sample");
        ReadOnlyFile(Path.Combine("per-sample", "job", "attempt-0001", "person-000001.jpg"));
        ReadOnlyFile(Path.Combine("per-sample", "top.jpg"));
        QualificationWorkRoot.Empty(root, entry =>
        {
            // As Windows deletes: a read-only entry, or one beneath a directory, is refused.
            var readOnly = entry is DirectoryInfo ? ReadOnlyBeneath(entry.FullName) : [];
            if (entry.Attributes.HasFlag(FileAttributes.ReadOnly) || readOnly.Count > 0)
                throw new UnauthorizedAccessException($"Access to the path '{entry.FullName}' is denied.");
            if (entry is DirectoryInfo directory) directory.Delete(recursive: true);
            else entry.Delete();
        });
        Assert.True(Directory.Exists(root));
        Assert.Empty(Directory.EnumerateFileSystemEntries(root));
        // And on the real OS delete.
        ReadOnlyFile(Path.Combine("per-sample", "job", "attempt-0002", "person-000002.jpg"));
        QualificationWorkRoot.Empty(root);
        Assert.True(Directory.Exists(root));
        Assert.Empty(Directory.EnumerateFileSystemEntries(root));
    }

    [Fact]
    public async Task SealedEvidenceStaysReadOnlyUntilItsOwnWorkRootIsCleanedUp()
    {
        // Normal product operation: the store seals evidence read-only, and cleaning up a
        // different qualification work root does not touch it.
        var productRoot = Path.Combine(_base, "product");
        var media = Path.Combine(productRoot, "media");
        var evidence = Path.Combine(productRoot, "evidence");
        var options = Options.Create(new MediaStorageOptions { RootPath = media, EvidenceRootPath = evidence });
        var mediaStore = new LocalMediaStore(options);
        var store = new AcceptedEvidenceStore(mediaStore, options);
        var bytes = Encoding.UTF8.GetBytes("immutable-evidence");
        var staged = await mediaStore.WriteAsync("staging/job/attempt-0001/thumbnails/person-000001.jpg", new MemoryStream(bytes), CancellationToken.None);
        var key = $"evidence/job/attempt-0001/thumbnails/person-000001-{Convert.ToHexStringLower(SHA256.HashData(bytes))}.jpg";
        var result = await store.SealAsync("staging/job/attempt-0001/thumbnails/person-000001.jpg", key, staged.SizeBytes, staged.Sha256, CancellationToken.None);
        Assert.Equal(AcceptedEvidenceSealStatus.Sealed, result.Status);
        var accepted = Path.Combine(evidence, key["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));
        Assert.True(File.GetAttributes(accepted).HasFlag(FileAttributes.ReadOnly));

        var otherRoot = Path.Combine(_base, "other-harness-root");
        ReadOnlyFile(Path.Combine("other-harness-root", "evidence", "x.jpg"));
        QualificationWorkRoot.Delete(otherRoot);
        Assert.False(Directory.Exists(otherRoot));
        Assert.True(File.GetAttributes(accepted).HasFlag(FileAttributes.ReadOnly));

        // Only the owning harness's own cleanup normalizes it, immediately before deleting.
        QualificationWorkRoot.Delete(productRoot, DeleteLikeWindows);
        Assert.False(Directory.Exists(productRoot));
    }

    [Theory]
    [InlineData("S1HandOffScaleTests.cs")]
    [InlineData("S1FinalizationEnvelopeTests.cs")]
    [InlineData("S1FinalizationRecoveryTests.cs")]
    public void TheHeavyB3HarnessesCleanUpOnlyThroughTheHelper(string harness)
    {
        var source = File.ReadAllText(Path.Combine(RepositoryRoot(), "tests", "Mavi.IntegrationTests", "Qualification", harness));
        Assert.DoesNotContain("Directory.Delete(", source, StringComparison.Ordinal);
        Assert.DoesNotContain("File.Delete(", source, StringComparison.Ordinal);
        Assert.Contains("QualificationWorkRoot.Delete(workRoot)", source, StringComparison.Ordinal);
    }

    [Fact]
    public void ProductCodeNeverUsesTheHelper()
    {
        var src = Path.Combine(RepositoryRoot(), "src");
        var users = Directory.EnumerateFiles(src, "*.cs", SearchOption.AllDirectories)
            .Where(path => !path.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}", StringComparison.Ordinal))
            .Where(path => File.ReadAllText(path).Contains("QualificationWorkRoot", StringComparison.Ordinal))
            .ToList();
        Assert.Empty(users);
    }

    private static string RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("repository root not found");
    }
}
