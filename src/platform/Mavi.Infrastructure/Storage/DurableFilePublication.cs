using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Mavi.Infrastructure.Storage;

internal static class DurableFilePublication
{
    private const int ErrorFileExists = 80;
    private const int ErrorAlreadyExists = 183;
    private const uint MoveFileWriteThrough = 0x8;

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
        using var handle = File.OpenHandle(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        RandomAccess.FlushToDisk(handle);
    }

#pragma warning disable SYSLIB1054
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
