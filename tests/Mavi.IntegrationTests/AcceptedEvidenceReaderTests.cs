using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class AcceptedEvidenceReaderTests : IDisposable
{
    private readonly string _baseRoot = Path.Combine(
        Path.GetTempPath(),
        "mavi-task14-reader-" + Guid.NewGuid().ToString("N"));
    private readonly string _mediaRoot;
    private readonly string _evidenceRoot;

    public AcceptedEvidenceReaderTests()
    {
        _mediaRoot = Path.Combine(_baseRoot, "media");
        _evidenceRoot = Path.Combine(_baseRoot, "evidence");
        Directory.CreateDirectory(_mediaRoot);
        Directory.CreateDirectory(_evidenceRoot);
    }

    [Fact]
    public async Task OpensCanonicalAcceptedEvidenceAsSeekableReadOnlyStream()
    {
        const string key = "evidence/job/attempt-0001/thumbnails/person-000001.jpg";
        var bytes = new byte[] { 1, 2, 3, 4, 5 };
        WriteEvidence(key, bytes);

        var reader = CreateReader();
        await using var stream = await reader.OpenReadAsync(key, CancellationToken.None);

        Assert.True(stream.CanRead);
        Assert.True(stream.CanSeek);
        Assert.False(stream.CanWrite);
        Assert.Equal(bytes.Length, stream.Length);
    }

    [Theory]
    [InlineData("../outside.jpg")]
    [InlineData("evidence/../outside.jpg")]
    [InlineData(@"evidence\outside.jpg")]
    [InlineData("C:/evidence/outside.jpg")]
    [InlineData("staging/job/file.jpg")]
    [InlineData("evidence//file.jpg")]
    public async Task RejectsNonCanonicalEvidenceKeys(string key)
    {
        var reader = CreateReader();

        await Assert.ThrowsAsync<ArgumentException>(
            () => reader.OpenReadAsync(key, CancellationToken.None));
    }

    [Fact]
    public async Task RejectsSymlinkLeafInsteadOfFollowingIt()
    {
        if (!OperatingSystem.IsLinux() && !OperatingSystem.IsWindows())
            return;

        var target = Path.Combine(_evidenceRoot, "target.jpg");
        await File.WriteAllBytesAsync(target, new byte[] { 7, 8, 9 });

        var linkDirectory = Path.Combine(_evidenceRoot, "job", "attempt-0001", "thumbnails");
        Directory.CreateDirectory(linkDirectory);
        var link = Path.Combine(linkDirectory, "person-000001.jpg");
        try
        {
            File.CreateSymbolicLink(link, target);
        }
        catch (Exception exception) when (
            exception is UnauthorizedAccessException or
            IOException or
            PlatformNotSupportedException)
        {
            // Some Windows CI hosts do not grant symbolic-link creation.
            return;
        }

        var reader = CreateReader();

        await Assert.ThrowsAsync<IOException>(
            () => reader.OpenReadAsync(
                "evidence/job/attempt-0001/thumbnails/person-000001.jpg",
                CancellationToken.None));
    }

    [Fact]
    public void RejectsOverlappingStorageRoots()
    {
        var nestedEvidence = Path.Combine(_mediaRoot, "evidence");
        Directory.CreateDirectory(nestedEvidence);

        Assert.Throws<InvalidOperationException>(() =>
            new AcceptedEvidenceReader(Options.Create(new MediaStorageOptions
            {
                RootPath = _mediaRoot,
                EvidenceRootPath = nestedEvidence,
            })));
    }

    [Fact]
    public async Task RejectsLinkedParentComponent()
    {
        if (!OperatingSystem.IsLinux() && !OperatingSystem.IsWindows())
            return;

        var external = Path.Combine(_baseRoot, "external");
        Directory.CreateDirectory(external);
        await File.WriteAllBytesAsync(Path.Combine(external, "file.jpg"), new byte[] { 1 });

        var jobLink = Path.Combine(_evidenceRoot, "job");
        try
        {
            Directory.CreateSymbolicLink(jobLink, external);
        }
        catch (Exception exception) when (
            exception is UnauthorizedAccessException or
            IOException or
            PlatformNotSupportedException)
        {
            return;
        }

        var reader = CreateReader();
        await Assert.ThrowsAnyAsync<IOException>(
            () => reader.OpenReadAsync("evidence/job/file.jpg", CancellationToken.None));
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_baseRoot))
                Directory.Delete(_baseRoot, recursive: true);
        }
        catch (IOException)
        {
            // Best-effort test cleanup.
        }
        catch (UnauthorizedAccessException)
        {
            // Best-effort test cleanup.
        }
    }

    private AcceptedEvidenceReader CreateReader() =>
        new(Options.Create(new MediaStorageOptions
        {
            RootPath = _mediaRoot,
            EvidenceRootPath = _evidenceRoot,
        }));

    private void WriteEvidence(string storageKey, byte[] bytes)
    {
        const string prefix = "evidence/";
        var relative = storageKey[prefix.Length..]
            .Replace('/', Path.DirectorySeparatorChar);
        var path = Path.Combine(_evidenceRoot, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
    }
}
