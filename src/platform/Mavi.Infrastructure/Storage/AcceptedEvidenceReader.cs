using System.ComponentModel;
using System.Runtime.InteropServices;
using Mavi.Application.Abstractions.Storage;
using Microsoft.Extensions.Options;
using Microsoft.Win32.SafeHandles;

namespace Mavi.Infrastructure.Storage;

public sealed class AcceptedEvidenceReader : IAcceptedEvidenceReader
{
    private const int MaximumStorageKeyLength = 512;
    private const string AcceptedPrefix = "evidence/";
    private readonly string _rootPath;
    private readonly string _rootPrefix;
    private readonly StringComparison _comparison = OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase
        : StringComparison.Ordinal;

    public AcceptedEvidenceReader(IOptions<MediaStorageOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.Value.RootPath))
            throw new InvalidOperationException("MediaStorage:RootPath is required.");
        if (string.IsNullOrWhiteSpace(options.Value.EvidenceRootPath))
            throw new InvalidOperationException("MediaStorage:EvidenceRootPath is required.");
        if (!StorageRootSafety.AreDisjointAndLinkFree(
                options.Value.RootPath,
                options.Value.EvidenceRootPath))
            throw new InvalidOperationException(
                "MediaStorage roots must be physically disjoint and link-free.");

        _rootPath = StorageRootSafety.NormalizeAndValidateRoot(options.Value.EvidenceRootPath);
        _rootPrefix = Path.EndsInDirectorySeparator(_rootPath)
            ? _rootPath
            : _rootPath + Path.DirectorySeparatorChar;
    }

    public Task<Stream> OpenReadAsync(
        string acceptedStorageKey,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var expectedPath = ResolvePath(acceptedStorageKey);

        StorageRootSafety.EnsureNoLinkedExistingComponents(
            Path.GetDirectoryName(expectedPath)!);

        var stream = new FileStream(
            expectedPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 81_920,
            FileOptions.Asynchronous | FileOptions.RandomAccess);

        try
        {
            EnsureOpenedLeafMatchesExpectedPath(stream, expectedPath);
            return Task.FromResult<Stream>(stream);
        }
        catch
        {
            stream.Dispose();
            throw;
        }
    }

    private string ResolvePath(string storageKey)
    {
        if (string.IsNullOrWhiteSpace(storageKey) ||
            storageKey.Length > MaximumStorageKeyLength ||
            !storageKey.StartsWith(AcceptedPrefix, StringComparison.Ordinal) ||
            storageKey.Contains('\\') ||
            storageKey.Contains(':') ||
            storageKey.Split('/').Any(segment => segment is "" or "." or ".."))
        {
            throw new ArgumentException(
                "Accepted evidence key must be a safe evidence/ relative key.",
                nameof(storageKey));
        }

        var relative = storageKey[AcceptedPrefix.Length..]
            .Replace('/', Path.DirectorySeparatorChar);
        var path = Path.GetFullPath(Path.Combine(_rootPath, relative));
        if (!path.StartsWith(_rootPrefix, _comparison))
            throw new ArgumentException(
                "Accepted evidence key resolves outside the evidence root.",
                nameof(storageKey));
        return path;
    }

    private static void EnsureOpenedLeafMatchesExpectedPath(
        FileStream stream,
        string expectedPath)
    {
        var actualPath = GetOpenedPath(stream);
        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;
        if (!string.Equals(
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(actualPath)),
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(expectedPath)),
                comparison))
        {
            throw new IOException(
                "Accepted evidence leaf resolves through a symbolic link or reparse point.");
        }
    }

    private static string GetOpenedPath(FileStream stream)
    {
        if (OperatingSystem.IsLinux())
        {
            var descriptor = stream.SafeFileHandle.DangerousGetHandle().ToInt64();
            var target = File.ResolveLinkTarget(
                $"/proc/self/fd/{descriptor}",
                returnFinalTarget: true)
                ?? throw new IOException(
                    "Unable to resolve the opened accepted-evidence identity.");
            return target.FullName;
        }

        if (OperatingSystem.IsWindows())
            return GetWindowsOpenedPath(stream.SafeFileHandle);

        throw new PlatformNotSupportedException(
            "Secure accepted-evidence reads are supported only on Windows and Linux.");
    }

    private static string GetWindowsOpenedPath(SafeFileHandle handle)
    {
        var buffer = new char[512];
        var length = GetFinalPathNameByHandle(
            handle,
            buffer,
            checked((uint)buffer.Length),
            0);
        if (length == 0)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        if (length >= buffer.Length)
        {
            buffer = new char[checked((int)length + 1)];
            length = GetFinalPathNameByHandle(
                handle,
                buffer,
                checked((uint)buffer.Length),
                0);
            if (length == 0 || length >= buffer.Length)
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        var path = new string(buffer, 0, checked((int)length));
        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
            path = @"\\" + path[8..];
        else if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
            path = path[4..];

        return Path.GetFullPath(path);
    }

#pragma warning disable SYSLIB1054
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
