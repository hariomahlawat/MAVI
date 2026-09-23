using System.Diagnostics;
using Mavi.Infrastructure.Storage;

namespace Mavi.IntegrationTests;

/// <summary>
/// Handle-relative, link-safe staging deletion (S1.2 plan §6.5, J6–J8, J11). No database:
/// these run on Linux and Windows in the Task 14 read-security workflow.
/// </summary>
public sealed class StagingDirectorySafetyTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-staging-safety-{Guid.NewGuid():N}");
    private readonly string _outside = Path.Combine(Path.GetTempPath(), $"mavi-staging-outside-{Guid.NewGuid():N}");

    public StagingDirectorySafetyTests()
    {
        Directory.CreateDirectory(Path.Combine(_root, "staging", "job"));
        Directory.CreateDirectory(_outside);
        File.WriteAllBytes(Path.Combine(_outside, "sentinel.bin"), [9, 9, 9]);
    }

    public void Dispose()
    {
        // Remove links first so cleanup can never reach through one.
        foreach (var directory in new[] { _root, _outside })
        {
            if (!Directory.Exists(directory))
                continue;
            foreach (var entry in Directory.EnumerateFileSystemEntries(directory, "*", new EnumerationOptions
                     {
                         RecurseSubdirectories = true,
                         AttributesToSkip = 0,
                     }).OrderByDescending(path => path.Length))
            {
                var info = new FileInfo(entry);
                if (info.Attributes.HasFlag(FileAttributes.ReparsePoint))
                {
                    if (info.Attributes.HasFlag(FileAttributes.Directory))
                        Directory.Delete(entry);
                    else
                        File.Delete(entry);
                }
            }

            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void RealAttemptTreeIsRemovedBottomUpAndFreedBytesCounted()
    {
        var attempt = Path.Combine(_root, "staging", "job", "attempt-0001");
        Directory.CreateDirectory(Path.Combine(attempt, "evidence"));
        Directory.CreateDirectory(Path.Combine(attempt, "trajectories", "deep", "deeper"));
        File.WriteAllBytes(Path.Combine(attempt, "evidence", "a.jpg"), new byte[100]);
        File.WriteAllBytes(Path.Combine(attempt, "trajectories", "deep", "deeper", "t.msgpack"), new byte[23]);

        using var job = OpenJob();
        var freed = job.RemoveChildTree("attempt-0001");

        Assert.Equal(123, freed);
        Assert.False(Directory.Exists(attempt));
        Assert.True(Directory.Exists(Path.Combine(_root, "staging", "job")));
    }

    [Fact]
    public void MissingAttemptIsANoOp()
    {
        using var job = OpenJob();

        Assert.Null(job.RemoveChildTree("attempt-0009"));
        Assert.Equal(StagingChildOpen.Missing, job.TryOpenChildDirectory("attempt-0009", out var child));
        Assert.Null(child);
    }

    [Fact]
    public void LinkedAttemptDirectoryIsRefusedAndItsTargetPreserved()
    {
        var link = Path.Combine(_root, "staging", "job", "attempt-0001");
        CreateDirectoryLink(link, _outside);

        using var job = OpenJob();
        Assert.Equal(StagingChildOpen.NotARealDirectory, job.TryOpenChildDirectory("attempt-0001", out _));
        Assert.Throws<StagingPathEscapeException>(() => job.RemoveChildTree("attempt-0001"));
        var entry = Assert.Single(job.ListChildren());
        Assert.False(entry.IsRealDirectory);

        Assert.True(File.Exists(Path.Combine(_outside, "sentinel.bin")));
        Assert.True(new DirectoryInfo(link).Attributes.HasFlag(FileAttributes.ReparsePoint));
    }

    [Fact]
    public void LinkedJobDirectoryIsRefusedAsAnAnchor()
    {
        var link = Path.Combine(_root, "staging", "linked-job");
        CreateDirectoryLink(link, _outside);

        using var root = StagingDirectory.OpenRoot(_root);
        Assert.Equal(StagingChildOpen.Opened, root.TryOpenChildDirectory("staging", out var staging));
        using (staging!)
        {
            Assert.Equal(StagingChildOpen.NotARealDirectory, staging!.TryOpenChildDirectory("linked-job", out _));
            Assert.False(staging.TryRemoveEmptyChildDirectory("linked-job"));
        }

        Assert.True(File.Exists(Path.Combine(_outside, "sentinel.bin")));
    }

    [Fact]
    public void NestedLinkInsideAttemptIsDeletedAsAnEntryAndNeverFollowed()
    {
        var attempt = Path.Combine(_root, "staging", "job", "attempt-0001");
        Directory.CreateDirectory(Path.Combine(attempt, "evidence"));
        File.WriteAllBytes(Path.Combine(attempt, "evidence", "a.jpg"), new byte[5]);
        CreateDirectoryLink(Path.Combine(attempt, "evidence", "escape"), _outside);

        using var job = OpenJob();
        var freed = job.RemoveChildTree("attempt-0001");

        Assert.Equal(5, freed);
        Assert.False(Directory.Exists(attempt));
        Assert.True(File.Exists(Path.Combine(_outside, "sentinel.bin")));
        Assert.Single(Directory.GetFiles(_outside));
    }

    [Fact]
    public void FileSymlinkInsideAttemptIsDeletedWithoutTouchingItsTarget()
    {
        if (!OperatingSystem.IsLinux())
            return; // Windows file symbolic links need a privilege CI runners lack; junctions cover Windows.

        var attempt = Path.Combine(_root, "staging", "job", "attempt-0001");
        Directory.CreateDirectory(attempt);
        File.CreateSymbolicLink(Path.Combine(attempt, "crop.jpg"), Path.Combine(_outside, "sentinel.bin"));

        using var job = OpenJob();
        Assert.Equal(0, job.RemoveChildTree("attempt-0001"));

        Assert.False(Directory.Exists(attempt));
        Assert.Equal([9, 9, 9], File.ReadAllBytes(Path.Combine(_outside, "sentinel.bin")));
    }

    [Fact]
    public void EmptyJobDirectoryIsRemovedOnlyWhenEmpty()
    {
        var job = Path.Combine(_root, "staging", "job");
        File.WriteAllBytes(Path.Combine(job, "keep.txt"), [1]);

        using var root = StagingDirectory.OpenRoot(_root);
        Assert.Equal(StagingChildOpen.Opened, root.TryOpenChildDirectory("staging", out var staging));
        using (staging!)
        {
            Assert.False(staging!.TryRemoveEmptyChildDirectory("job"));
            Assert.True(Directory.Exists(job));

            File.Delete(Path.Combine(job, "keep.txt"));
            Assert.True(staging.TryRemoveEmptyChildDirectory("job"));
            Assert.False(Directory.Exists(job));
            Assert.False(staging.TryRemoveEmptyChildDirectory("job"));
        }
    }

    [Fact]
    public void TreesDeeperThanTheBoundFailInsteadOfRecursingWithoutLimit()
    {
        var path = Path.Combine(_root, "staging", "job", "attempt-0001");
        for (var level = 0; level <= StagingDirectory.MaximumTreeDepth + 1; level++)
            path = Path.Combine(path, "d");
        Directory.CreateDirectory(path);

        using var job = OpenJob();

        Assert.ThrowsAny<IOException>(() => job.RemoveChildTree("attempt-0001"));
        Assert.True(Directory.Exists(Path.Combine(_root, "staging", "job", "attempt-0001")));
    }

    [Fact]
    public void ListingClassifiesEntriesAndStaysInsideTheOpenedDirectory()
    {
        var job = Path.Combine(_root, "staging", "job");
        Directory.CreateDirectory(Path.Combine(job, "attempt-0001"));
        File.WriteAllBytes(Path.Combine(job, "note.txt"), [1]);
        File.WriteAllBytes(Path.Combine(_root, "outside-staging.bin"), [1]);

        using var opened = OpenJob();
        var entries = opened.ListChildren().OrderBy(entry => entry.Name, StringComparer.Ordinal).ToList();

        Assert.Equal(["attempt-0001", "note.txt"], entries.Select(entry => entry.Name));
        Assert.True(entries[0].IsRealDirectory);
        Assert.False(entries[1].IsRealDirectory);
        Assert.True(File.Exists(Path.Combine(_root, "outside-staging.bin")));
    }

    private StagingDirectory OpenJob()
    {
        var root = StagingDirectory.OpenRoot(_root);
        try
        {
            Assert.Equal(StagingChildOpen.Opened, root.TryOpenChildDirectory("staging", out var staging));
            using (staging!)
            {
                Assert.Equal(StagingChildOpen.Opened, staging!.TryOpenChildDirectory("job", out var job));
                return job!;
            }
        }
        finally
        {
            root.Dispose();
        }
    }

    /// <summary>A POSIX symbolic link, or an NTFS junction (no privilege needed) on Windows.</summary>
    internal static void CreateDirectoryLink(string link, string target)
    {
        if (!OperatingSystem.IsWindows())
        {
            Directory.CreateSymbolicLink(link, target);
            return;
        }

        using var process = Process.Start(new ProcessStartInfo("cmd", ["/c", "mklink", "/J", link, target])
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        })!;
        process.WaitForExit();
        Assert.True(process.ExitCode == 0,
            $"Failed to create an NTFS junction: {process.StandardOutput.ReadToEnd()} {process.StandardError.ReadToEnd()}");
    }
}
