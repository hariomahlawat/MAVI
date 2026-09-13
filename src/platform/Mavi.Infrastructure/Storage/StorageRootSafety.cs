using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Fail-closed validation for authoritative storage roots. Configured roots must
/// be logically and physically disjoint and must not traverse existing
/// symbolic-link/reparse components.
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

            if (IsSameOrDescendant(first, second, comparison) ||
                IsSameOrDescendant(second, first, comparison))
                return false;

            var firstPhysical = ResolvePhysicalPath(first);
            var secondPhysical = ResolvePhysicalPath(second);
            return !IsSameOrDescendant(firstPhysical, secondPhysical, comparison) &&
                   !IsSameOrDescendant(secondPhysical, firstPhysical, comparison);
        }
        catch (Exception exception) when (
            exception is ArgumentException or
            InvalidOperationException or
            IOException or
            UnauthorizedAccessException or
            NotSupportedException or
            PlatformNotSupportedException)
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
                // Missing leaves are permitted; existing inaccessible components
                // fail through the attribute inspection below where applicable.
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

    private static string ResolvePhysicalPath(string path)
    {
        if (OperatingSystem.IsLinux())
            return ResolveLinuxPhysicalPath(path, File.ReadLines("/proc/self/mountinfo"));
        if (OperatingSystem.IsWindows())
            return ResolveWindowsPhysicalPath(path);

        throw new PlatformNotSupportedException(
            "Physical storage-root identity is supported only on Windows and Linux.");
    }

    internal static string ResolveLinuxPhysicalPath(
        string path,
        IEnumerable<string> mountInfoLines)
    {
        var normalized = NormalizeUnixPath(Path.GetFullPath(path));
        LinuxMount? best = null;

        foreach (var rawLine in mountInfoLines)
        {
            var separator = rawLine.IndexOf(" - ", StringComparison.Ordinal);
            if (separator <= 0)
                continue;

            var fields = rawLine[..separator].Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (fields.Length < 6)
                continue;

            var mount = new LinuxMount(
                fields[2],
                DecodeMountInfoPath(fields[3]),
                DecodeMountInfoPath(fields[4]));

            if (!IsUnixSameOrDescendant(normalized, mount.MountPoint))
                continue;

            if (best is null || mount.MountPoint.Length > best.Value.MountPoint.Length)
                best = mount;
        }

        if (best is null)
            throw new InvalidOperationException(
                $"Unable to resolve physical mount identity for storage root: {path}");

        var relative = normalized.Length == best.Value.MountPoint.Length
            ? string.Empty
            : normalized[(best.Value.MountPoint == "/" ? 1 : best.Value.MountPoint.Length + 1)..];

        return $"{best.Value.Device}:{CombineUnix(best.Value.Root, relative)}";
    }

    private static string ResolveWindowsPhysicalPath(string path)
    {
        var fullPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        var missingSegments = new Stack<string>();
        var existing = fullPath;

        while (!Directory.Exists(existing))
        {
            var parent = Path.GetDirectoryName(existing);
            if (string.IsNullOrEmpty(parent) ||
                string.Equals(parent, existing, StringComparison.OrdinalIgnoreCase))
                throw new DirectoryNotFoundException(
                    $"Unable to resolve an existing ancestor for storage root: {path}");

            missingSegments.Push(Path.GetFileName(existing));
            existing = parent;
        }

        using var handle = CreateFile(
            existing,
            0,
            FileShare.Read | FileShare.Write | FileShare.Delete,
            IntPtr.Zero,
            3,
            0x02000000,
            IntPtr.Zero);
        if (handle.IsInvalid)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        var physical = GetWindowsFinalPath(handle);
        while (missingSegments.Count > 0)
            physical = Path.Combine(physical, missingSegments.Pop());

        return Path.TrimEndingDirectorySeparator(physical);
    }

    private static string GetWindowsFinalPath(SafeFileHandle handle)
    {
        var buffer = new char[512];
        var length = GetFinalPathNameByHandle(
            handle,
            buffer,
            checked((uint)buffer.Length),
            0x2);
        if (length == 0)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        if (length >= buffer.Length)
        {
            buffer = new char[checked((int)length + 1)];
            length = GetFinalPathNameByHandle(
                handle,
                buffer,
                checked((uint)buffer.Length),
                0x2);
            if (length == 0 || length >= buffer.Length)
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        return new string(buffer, 0, checked((int)length));
    }

    private static string DecodeMountInfoPath(string value) =>
        value.Replace(@"\040", " ", StringComparison.Ordinal)
             .Replace(@"\011", "\t", StringComparison.Ordinal)
             .Replace(@"\012", "\n", StringComparison.Ordinal)
             .Replace(@"\134", @"\", StringComparison.Ordinal);

    private static string NormalizeUnixPath(string path)
    {
        var normalized = path.Replace('\\', '/');
        if (normalized.Length > 1)
            normalized = normalized.TrimEnd('/');
        return normalized.Length == 0 ? "/" : normalized;
    }

    private static string CombineUnix(string root, string relative)
    {
        var normalizedRoot = NormalizeUnixPath(root);
        if (string.IsNullOrEmpty(relative))
            return normalizedRoot;
        return normalizedRoot == "/"
            ? "/" + relative
            : normalizedRoot + "/" + relative;
    }

    private static bool IsUnixSameOrDescendant(string candidate, string root)
    {
        if (string.Equals(candidate, root, StringComparison.Ordinal))
            return true;
        if (root == "/")
            return candidate.StartsWith('/');
        return candidate.StartsWith(root + "/", StringComparison.Ordinal);
    }

    private static bool IsSameOrDescendant(
        string candidate,
        string root,
        StringComparison comparison)
    {
        if (string.Equals(candidate, root, comparison))
            return true;

        var separator = candidate.Contains('/') && !candidate.Contains('\\')
            ? '/'
            : Path.DirectorySeparatorChar;
        var rootPrefix = root.EndsWith(separator) ? root : root + separator;
        return candidate.StartsWith(rootPrefix, comparison);
    }

    private static StringComparison PathComparison =>
        OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;

    private readonly record struct LinuxMount(
        string Device,
        string Root,
        string MountPoint);

#pragma warning disable SYSLIB1054
    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        SetLastError = true,
        ExactSpelling = true)]
    private static extern SafeFileHandle CreateFile(
        string lpFileName,
        uint dwDesiredAccess,
        FileShare dwShareMode,
        IntPtr lpSecurityAttributes,
        uint dwCreationDisposition,
        uint dwFlagsAndAttributes,
        IntPtr hTemplateFile);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetFinalPathNameByHandleW",
        CharSet = CharSet.Unicode,
        SetLastError = true,
        ExactSpelling = true)]
    private static extern uint GetFinalPathNameByHandle(
        SafeFileHandle hFile,
        [Out] char[] lpszFilePath,
        uint cchFilePath,
        uint dwFlags);
#pragma warning restore SYSLIB1054
}
