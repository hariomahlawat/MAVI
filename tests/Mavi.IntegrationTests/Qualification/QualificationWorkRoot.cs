namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Cleanup of a qualification-owned temporary work root (its media, staging and
/// accepted-evidence trees). Accepted evidence is sealed read-only by
/// <c>AcceptedEvidenceStore</c>; on Windows a read-only file cannot be deleted, so
/// a raw recursive delete of a root that holds sealed evidence throws
/// <see cref="UnauthorizedAccessException"/>. Immediately before deleting its own
/// root, the harness clears only the read-only attribute beneath it, keeping every
/// other attribute, and then deletes.
/// </summary>
/// <remarks>
/// Test infrastructure only; product code never calls it, and sealed evidence stays
/// read-only for as long as the product owns it. The walk never follows a link: a
/// symbolic link, junction or other reparse point is neither entered nor modified
/// (the recursive delete removes the link itself, not its target), and a root that is
/// itself a link is refused. Nothing is caught: an unexpected failure propagates.
/// </remarks>
public static class QualificationWorkRoot
{
    private static readonly EnumerationOptions Children = new()
    {
        RecurseSubdirectories = false,
        IgnoreInaccessible = false,
        AttributesToSkip = 0,
        ReturnSpecialDirectories = false,
    };

    /// <summary>Deletes <paramref name="root"/> and everything beneath it; absent is a no-op.</summary>
    public static void Delete(string root) => Delete(root, Directory.Delete);

    /// <summary>Deletes everything beneath <paramref name="root"/> and keeps the root.</summary>
    public static void Empty(string root)
    {
        var directory = OwnedRoot(root) ?? throw new DirectoryNotFoundException($"qualification work root {root} does not exist");
        ClearReadOnlyBeneath(directory);
        foreach (var entry in directory.EnumerateFileSystemInfos("*", Children))
        {
            if (entry is DirectoryInfo child && !IsLink(child)) child.Delete(recursive: true);
            else entry.Delete();
        }
    }

    /// <summary>The deletion seam, so a test can prove a failure is not swallowed.</summary>
    internal static void Delete(string root, Action<string, bool> deleteDirectory)
    {
        var directory = OwnedRoot(root);
        if (directory is null) return;
        ClearReadOnlyBeneath(directory);
        ClearReadOnly(directory);
        deleteDirectory(directory.FullName, true);
    }

    private static DirectoryInfo? OwnedRoot(string root)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(root);
        var directory = new DirectoryInfo(Path.GetFullPath(root));
        if (!directory.Exists)
        {
            // A dangling link is still a link; anything else absent is nothing to clean.
            if (directory.LinkTarget is not null) throw new IOException($"qualification work root {root} is a link, not an owned directory");
            if (File.Exists(directory.FullName)) throw new IOException($"qualification work root {root} is a file, not a directory");
            return null;
        }
        if (IsLink(directory)) throw new IOException($"qualification work root {root} is a link, not an owned directory");
        return directory;
    }

    private static void ClearReadOnlyBeneath(DirectoryInfo directory)
    {
        foreach (var entry in directory.EnumerateFileSystemInfos("*", Children))
        {
            if (IsLink(entry)) continue;
            ClearReadOnly(entry);
            if (entry is DirectoryInfo child) ClearReadOnlyBeneath(child);
        }
    }

    private static void ClearReadOnly(FileSystemInfo entry)
    {
        var attributes = entry.Attributes;
        if ((attributes & FileAttributes.ReadOnly) == 0) return;
        var cleared = attributes & ~FileAttributes.ReadOnly;
        entry.Attributes = cleared == 0 ? FileAttributes.Normal : cleared;
    }

    private static bool IsLink(FileSystemInfo entry) =>
        (entry.Attributes & FileAttributes.ReparsePoint) != 0 || entry.LinkTarget is not null;
}
