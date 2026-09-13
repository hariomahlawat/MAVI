namespace Mavi.Infrastructure.Storage;

internal static class StoragePathSecurity
{
    public static bool AreRootsDisjoint(string firstPath, string secondPath)
    {
        if (string.IsNullOrWhiteSpace(firstPath) || string.IsNullOrWhiteSpace(secondPath))
            return false;

        var first = ResolvePhysicalDirectory(firstPath);
        var second = ResolvePhysicalDirectory(secondPath);
        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;
        var firstPrefix = WithTrailingSeparator(first);
        var secondPrefix = WithTrailingSeparator(second);

        return !string.Equals(first, second, comparison) &&
               !second.StartsWith(firstPrefix, comparison) &&
               !first.StartsWith(secondPrefix, comparison);
    }

    public static string ResolvePhysicalDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Storage root path is required.", nameof(path));

        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath)
            ?? throw new ArgumentException("Storage root path is invalid.", nameof(path));
        var relative = fullPath[root.Length..];
        var segments = relative.Split(
            [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
            StringSplitOptions.RemoveEmptyEntries);

        var current = root;
        foreach (var segment in segments)
        {
            var candidate = Path.Combine(current, segment);
            var directory = new DirectoryInfo(candidate);
            if (directory.Exists && directory.LinkTarget is not null)
            {
                var resolved = directory.ResolveLinkTarget(returnFinalTarget: true)
                    ?? throw new IOException($"Unable to resolve storage-root link '{candidate}'.");
                current = Path.GetFullPath(resolved.FullName);
            }
            else
            {
                current = candidate;
            }
        }

        return TrimTrailingSeparators(Path.GetFullPath(current));
    }

    private static string WithTrailingSeparator(string path) =>
        Path.EndsInDirectorySeparator(path)
            ? path
            : path + Path.DirectorySeparatorChar;

    private static string TrimTrailingSeparators(string path)
    {
        var root = Path.GetPathRoot(path) ?? string.Empty;
        if (string.Equals(path, root, OperatingSystem.IsWindows()
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal))
            return path;

        return path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }
}
