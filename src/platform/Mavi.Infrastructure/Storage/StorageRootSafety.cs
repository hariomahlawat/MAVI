namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Fail-closed validation for authoritative storage roots. Configured roots must
/// be logically disjoint and must not traverse existing symbolic-link/reparse
/// components, otherwise worker-writable and platform-owned storage can alias.
/// </summary>
internal static class StorageRootSafety
{
    public static bool AreDisjointAndLinkFree(string firstPath, string secondPath)
    {
        try
        {
            var first = NormalizeAndValidateRoot(firstPath);
            var second = NormalizeAndValidateRoot(secondPath);
            var comparison = PathComparison;

            return !IsSameOrDescendant(first, second, comparison) &&
                   !IsSameOrDescendant(second, first, comparison);
        }
        catch (Exception exception) when (
            exception is ArgumentException or
            InvalidOperationException or
            IOException or
            UnauthorizedAccessException or
            NotSupportedException)
        {
            return false;
        }
    }

    public static string NormalizeAndValidateRoot(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Storage root is required.", nameof(path));

        var fullPath = Path.GetFullPath(path);
        EnsureNoLinkedExistingComponents(fullPath);
        return Path.TrimEndingDirectorySeparator(fullPath);
    }

    public static void EnsureNoLinkedExistingComponents(string path)
    {
        var current = new DirectoryInfo(Path.GetFullPath(path));
        while (current is not null)
        {
            string? linkTarget = null;
            try
            {
                linkTarget = current.LinkTarget;
            }
            catch (Exception exception) when (
                exception is FileNotFoundException or
                DirectoryNotFoundException or
                IOException or
                UnauthorizedAccessException or
                PlatformNotSupportedException)
            {
                // A missing leaf is permitted; an inaccessible existing component
                // is handled by the attribute read below when applicable.
            }

            if (linkTarget is not null)
                throw new InvalidOperationException(
                    $"Storage root may not traverse a symbolic-link or reparse component: {current.FullName}");

            if (current.Exists)
            {
                FileAttributes attributes;
                try
                {
                    attributes = current.Attributes;
                }
                catch (Exception exception) when (
                    exception is IOException or UnauthorizedAccessException)
                {
                    throw new InvalidOperationException(
                        $"Storage root component could not be inspected safely: {current.FullName}",
                        exception);
                }

                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException(
                        $"Storage root may not traverse a symbolic-link or reparse component: {current.FullName}");
            }

            current = current.Parent;
        }
    }

    private static bool IsSameOrDescendant(
        string candidate,
        string root,
        StringComparison comparison)
    {
        if (string.Equals(candidate, root, comparison))
            return true;

        var rootPrefix = Path.EndsInDirectorySeparator(root)
            ? root
            : root + Path.DirectorySeparatorChar;
        return candidate.StartsWith(rootPrefix, comparison);
    }

    private static StringComparison PathComparison =>
        OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;
}
