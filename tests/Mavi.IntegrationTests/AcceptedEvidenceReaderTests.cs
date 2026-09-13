using Mavi.Application.Abstractions.Storage;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AcceptedEvidenceReaderTests
{
    [Fact]
    public async Task OpensCanonicalAcceptedEvidenceAsSeekableReadOnlyStream()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        const string key = "evidence/job/attempt-0001/thumbnails/person-000001.jpg";
        var bytes = new byte[] { 1, 2, 3, 4, 5 };
        Task14TestData.WriteEvidence(factory, key, bytes);

        var reader = factory.Services.GetRequiredService<IAcceptedEvidenceReader>();
        await using var stream = await reader.OpenReadAsync(key, CancellationToken.None);

        Assert.True(stream.CanRead);
        Assert.True(stream.CanSeek);
        Assert.False(stream.CanWrite);
        Assert.Equal(bytes.Length, stream.Length);
    }

    [Theory]
    [InlineData("../outside.jpg")]
    [InlineData("evidence/../outside.jpg")]
    [InlineData("evidence\outside.jpg")]
    [InlineData("C:/evidence/outside.jpg")]
    [InlineData("staging/job/file.jpg")]
    public async Task RejectsNonCanonicalEvidenceKeys(string key)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var reader = factory.Services.GetRequiredService<IAcceptedEvidenceReader>();

        await Assert.ThrowsAsync<ArgumentException>(
            () => reader.OpenReadAsync(key, CancellationToken.None));
    }

    [Fact]
    public async Task RejectsSymlinkLeafInsteadOfFollowingIt()
    {
        if (!OperatingSystem.IsLinux() && !OperatingSystem.IsWindows())
            return;

        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var target = Path.Combine(factory.EvidenceRoot, "target.jpg");
        Directory.CreateDirectory(factory.EvidenceRoot);
        await File.WriteAllBytesAsync(target, new byte[] { 7, 8, 9 });

        var linkDirectory = Path.Combine(factory.EvidenceRoot, "job", "attempt-0001", "thumbnails");
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

        var reader = factory.Services.GetRequiredService<IAcceptedEvidenceReader>();

        await Assert.ThrowsAsync<IOException>(
            () => reader.OpenReadAsync(
                "evidence/job/attempt-0001/thumbnails/person-000001.jpg",
                CancellationToken.None));
    }
}
