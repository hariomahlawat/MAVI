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

    public static void EnsureDirectoryHierarchy(string durabilityRootPath, string targetPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(durabilityRootPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(targetPath);

        var durabilityRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(durabilityRootPath));
        var target = Path.TrimEndingDirectorySeparator(Path.GetFullPath(targetPath));
        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;
        var rootPrefix = durabilityRoot + Path.DirectorySeparatorChar;
        if (!string.Equals(target, durabilityRoot, comparison) &&
            !target.StartsWith(rootPrefix, comparison))
            throw new ArgumentException("Evidence directory target must remain beneath the durability root.", nameof(targetPath));

        if (OperatingSystem.IsWindows())
        {
            Directory.CreateDirectory(target);
            return;
        }

        if (OperatingSystem.IsLinux())
        {
            EnsureLinuxDirectoryHierarchy(durabilityRoot, target);
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

            // The accepted destination is already durable at this point. Removing
            // the temporary hard-link name is housekeeping and must not turn a
            // successful publication into an ownership-ambiguous failure.
            try
            {
                File.Delete(temporaryPath);
                FlushDirectory(parentPath);
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
                // A later maintenance sweep may remove a leftover hidden temporary
                // name. The accepted destination remains the authoritative object.
            }

            return DurablePublicationOutcome.PublishedNew;
        }

        throw new PlatformNotSupportedException(
            "Durable accepted-evidence publication is supported only on Windows and Linux.");
    }

    private static void EnsureLinuxDirectoryHierarchy(
        string durabilityRoot,
        string target)
    {
        Directory.CreateDirectory(target);

        // Visibility is not proof of durability. A previous attempt may have
        // created a directory and then failed while synchronizing its parent
        // entry. Re-fsync the complete configured evidence-root chain on every
        // attempt so retries repair that state before publication can commit.
        var chain = new Stack<string>();
        var current = target;
        while (true)
        {
            chain.Push(current);
            if (string.Equals(current, durabilityRoot, StringComparison.Ordinal))
                break;

            current = Path.GetDirectoryName(current)
                ?? throw new DirectoryNotFoundException(
                    $"Evidence directory escaped its durability root: {target}");
        }

        var rootParent = Path.GetDirectoryName(durabilityRoot)
            ?? throw new DirectoryNotFoundException(
                $"Evidence durability root has no parent: {durabilityRoot}");
        FlushDirectory(rootParent);

        while (chain.Count > 0)
        {
            var directory = chain.Pop();
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
