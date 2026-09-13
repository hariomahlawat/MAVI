using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Mavi.Infrastructure.Storage;

internal enum DurablePublicationOutcome
{
    PublishedNew,
    DestinationAlreadyExists,
}

internal static class DurableFilePublication
{
    private const int ErrorFileExists = 80;
    private const int ErrorAlreadyExists = 183;
    private const uint MoveFileWriteThrough = 0x8;
    private const int LinuxOpenReadOnly = 0;
    private const int LinuxOpenDirectory = 0x10000;
    private const int LinuxOpenCloseOnExec = 0x80000;

    public static void EnsureDirectoryHierarchy(string targetPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(targetPath);

        if (OperatingSystem.IsWindows())
        {
            Directory.CreateDirectory(targetPath);
            return;
        }

        if (OperatingSystem.IsLinux())
        {
            EnsureLinuxDirectoryHierarchy(targetPath);
            return;
        }

        throw new PlatformNotSupportedException(
            "Durable accepted-evidence directory creation is supported only on Windows and Linux.");
    }

    public static void EnsurePublishedDirectoryDurable(string parentPath)
    {
        if (OperatingSystem.IsLinux())
            FlushDirectory(parentPath);
    }

    public static void DeletePublished(string destinationPath, string parentPath)
    {
        if (!File.Exists(destinationPath))
            return;

        File.SetAttributes(destinationPath, FileAttributes.Normal);
        File.Delete(destinationPath);

        if (OperatingSystem.IsLinux())
            FlushDirectory(parentPath);
    }

    public static DurablePublicationOutcome Publish(
        string temporaryPath,
        string destinationPath,
        string parentPath)
    {
        if (OperatingSystem.IsWindows())
        {
            if (!MoveFileEx(temporaryPath, destinationPath, MoveFileWriteThrough))
            {
                var error = Marshal.GetLastWin32Error();
                if (error is ErrorFileExists or ErrorAlreadyExists)
                    return DurablePublicationOutcome.DestinationAlreadyExists;

                throw new IOException(
                    "Durable accepted-evidence publication failed.",
                    new Win32Exception(error));
            }

            return DurablePublicationOutcome.PublishedNew;
        }

        if (OperatingSystem.IsLinux())
        {
            var linkResult = Link(temporaryPath, destinationPath);
            if (linkResult != 0)
            {
                var error = Marshal.GetLastPInvokeError();
                if (error == 17) // EEXIST
                    return DurablePublicationOutcome.DestinationAlreadyExists;

                throw new IOException(
                    "Create-once accepted-evidence publication failed.",
                    new Win32Exception(error));
            }

            try
            {
                FlushDirectory(parentPath);
            }
            catch
            {
                // The destination belongs to this invocation. Remove it before
                // propagating the durability failure so it cannot be mistaken
                // for a pre-existing idempotent accepted object on retry.
                try
                {
                    File.Delete(destinationPath);
                    FlushDirectory(parentPath);
                }
                catch
                {
                    // Preserve the original durability failure. Any inability to
                    // compensate remains an operational fault and must not be
                    // converted into a successful seal.
                }

                throw;
            }

            File.Delete(temporaryPath);
            FlushDirectory(parentPath);
            return DurablePublicationOutcome.PublishedNew;
        }

        throw new PlatformNotSupportedException(
            "Durable accepted-evidence publication is supported only on Windows and Linux.");
    }

    private static void EnsureLinuxDirectoryHierarchy(string targetPath)
    {
        var target = Path.GetFullPath(targetPath);
        var missing = new Stack<string>();
        var current = target;

        while (!Directory.Exists(current))
        {
            missing.Push(current);
            var parent = Path.GetDirectoryName(current);
            if (string.IsNullOrEmpty(parent) ||
                string.Equals(parent, current, StringComparison.Ordinal))
            {
                throw new DirectoryNotFoundException(
                    $"Unable to resolve an existing ancestor for evidence directory: {targetPath}");
            }

            current = parent;
        }

        while (missing.Count > 0)
        {
            var directory = missing.Pop();
            Directory.CreateDirectory(directory);

            // Persist both the new directory inode and the parent entry that links
            // it into the namespace before any authoritative DB row can reference it.
            FlushDirectory(directory);
            var parent = Path.GetDirectoryName(directory)
                ?? throw new DirectoryNotFoundException(
                    $"Evidence directory has no parent: {directory}");
            FlushDirectory(parent);
        }
    }

    private static void FlushDirectory(string path)
    {
        var descriptor = Open(
            path,
            LinuxOpenReadOnly | LinuxOpenDirectory | LinuxOpenCloseOnExec);
        if (descriptor < 0)
            throw new IOException(
                "Unable to open accepted-evidence directory for durable synchronization.",
                new Win32Exception(Marshal.GetLastPInvokeError()));

        try
        {
            if (Fsync(descriptor) != 0)
                throw new IOException(
                    "Unable to durably synchronize accepted-evidence directory metadata.",
                    new Win32Exception(Marshal.GetLastPInvokeError()));
        }
        finally
        {
            _ = Close(descriptor);
        }
    }

#pragma warning disable SYSLIB1054
#pragma warning disable CA2101 // POSIX open(2) requires UTF-8; marshaling is explicit and intentional.
    [DllImport("libc", EntryPoint = "open", SetLastError = true)]
    private static extern int Open(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string pathname,
        int flags);
#pragma warning restore CA2101

#pragma warning disable CA2101 // POSIX link(2) requires UTF-8; marshaling is explicit and intentional.
    [DllImport("libc", EntryPoint = "link", SetLastError = true)]
    private static extern int Link(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string oldpath,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string newpath);
#pragma warning restore CA2101

    [DllImport("libc", EntryPoint = "fsync", SetLastError = true)]
    private static extern int Fsync(int descriptor);

    [DllImport("libc", EntryPoint = "close", SetLastError = true)]
    private static extern int Close(int descriptor);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "MoveFileExW",
        CharSet = CharSet.Unicode,
        SetLastError = true,
        ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(
        string lpExistingFileName,
        string lpNewFileName,
        uint dwFlags);
#pragma warning restore SYSLIB1054
}
