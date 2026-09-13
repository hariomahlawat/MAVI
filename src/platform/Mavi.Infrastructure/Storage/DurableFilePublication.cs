using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Mavi.Infrastructure.Storage;

internal static partial class DurableFilePublication
{
    private const int ErrorFileExists = 80;
    private const int ErrorAlreadyExists = 183;
    private const uint MoveFileWriteThrough = 0x8;
    private const int LinuxOpenReadOnly = 0;
    private const int LinuxOpenDirectory = 0x10000;
    private const int LinuxOpenCloseOnExec = 0x80000;

    public static void Publish(string temporaryPath, string destinationPath, string parentPath)
    {
        if (OperatingSystem.IsWindows())
        {
            if (!MoveFileEx(temporaryPath, destinationPath, MoveFileWriteThrough))
            {
                var error = Marshal.GetLastWin32Error();
                if (error is ErrorFileExists or ErrorAlreadyExists)
                    throw new IOException("Accepted evidence already exists.");

                throw new IOException(
                    "Durable accepted-evidence publication failed.",
                    new Win32Exception(error));
            }

            return;
        }

        if (OperatingSystem.IsLinux())
        {
            File.Move(temporaryPath, destinationPath, overwrite: false);
            FlushDirectory(parentPath);
            return;
        }

        throw new PlatformNotSupportedException(
            "Durable accepted-evidence publication is supported only on Windows and Linux.");
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
    [LibraryImport(
        "libc",
        EntryPoint = "open",
        StringMarshalling = StringMarshalling.Utf8,
        SetLastError = true)]
    private static partial int Open(string pathname, int flags);

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
