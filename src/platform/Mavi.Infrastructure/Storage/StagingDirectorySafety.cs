using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Mavi.Infrastructure.Storage;

/// <summary>Outcome of opening a named child as a directory anchor.</summary>
internal enum StagingChildOpen
{
    Opened,
    Missing,
    /// <summary>The entry exists but is a file, a symbolic link, a junction or another reparse point.</summary>
    NotARealDirectory,
}

/// <summary>One entry of a staging directory, classified without following it.</summary>
/// <param name="Name">The entry name, or <see langword="null"/> when it is not valid UTF-8 (POSIX only).</param>
internal sealed record StagingChildEntry(string? Name, bool IsRealDirectory, DateTimeOffset LastWriteTimeUtc);

/// <summary>A staging path the janitor must not follow: a link, junction or non-directory where a directory belongs.</summary>
internal sealed class StagingPathEscapeException(string message) : IOException(message);

/// <summary>
/// A held directory handle through which every staging operation is performed relative to
/// the handle, never by re-resolving a path (S1.2 plan §6.5).
/// </summary>
/// <remarks>
/// <para>
/// This is the platform twin of the worker's staging discipline: POSIX
/// <c>rmtree(dir_fd=)</c> and Windows <c>_remove_attempt_tree_no_reparse</c>. Every child
/// is opened relative to its parent's handle without following links; a symbolic link,
/// junction or other reparse point is removed as an entry and never traversed; real
/// directories are emptied bottom-up and then removed. A concurrent rename of any
/// ancestor therefore cannot redirect a deletion outside the tree the janitor opened.
/// </para>
/// <para>
/// System.IO has no handle-relative operations, so the implementation binds the operating
/// system's own libraries (libc; ntdll/kernel32), exactly as <see cref="DurableFilePublication"/>
/// and <see cref="StorageRootSafety"/> already do. No package is added. Platforms without a
/// verified implementation fail closed: nothing is enumerated or deleted.
/// </para>
/// </remarks>
internal abstract class StagingDirectory : IDisposable
{
    /// <summary>Deepest nesting removed inside one attempt tree; deeper trees fail and are retried.</summary>
    public const int MaximumTreeDepth = 32;

    public static bool IsSupported =>
        OperatingSystem.IsWindows() || (OperatingSystem.IsLinux() && LinuxStagingDirectory.ArchitectureSupported);

    public static StagingDirectory OpenRoot(string path)
    {
        if (OperatingSystem.IsWindows())
            return WindowsStagingDirectory.OpenRoot(path);
        if (OperatingSystem.IsLinux() && LinuxStagingDirectory.ArchitectureSupported)
            return LinuxStagingDirectory.OpenRoot(path);
        throw new PlatformNotSupportedException(
            "Handle-relative staging reclamation is implemented for Linux x64/arm64 and Windows only.");
    }

    /// <summary>Opens <paramref name="name"/> as a real directory anchor, refusing links and reparse points.</summary>
    public abstract StagingChildOpen TryOpenChildDirectory(string name, out StagingDirectory? child);

    /// <summary>Lists and classifies every entry without following any of them.</summary>
    public abstract IReadOnlyList<StagingChildEntry> ListChildren();

    public abstract DateTimeOffset LastWriteTimeUtc { get; }

    /// <summary>
    /// Removes the real directory <paramref name="name"/> and everything under it.
    /// Returns the regular-file bytes freed, or <see langword="null"/> when the entry is already gone.
    /// </summary>
    /// <exception cref="StagingPathEscapeException">The entry is not a real directory; nothing is removed.</exception>
    public abstract long? RemoveChildTree(string name);

    /// <summary>Removes <paramref name="name"/> only if it is an empty real directory.</summary>
    public abstract bool TryRemoveEmptyChildDirectory(string name);

    public abstract void Dispose();

    protected static void EnsureDepth(int depth)
    {
        if (depth > MaximumTreeDepth)
            throw new IOException($"Staging tree is nested deeper than {MaximumTreeDepth} levels.");
    }
}

/// <summary>Linux: <c>openat</c>/<c>statx</c>/<c>getdents64</c>/<c>unlinkat</c> relative to a held descriptor.</summary>
internal sealed class LinuxStagingDirectory : StagingDirectory
{
    // Open flags are architecture-specific on Linux; a wrong O_NOFOLLOW would silently
    // follow links, so only the two verified ABIs are supported.
    private static readonly (int Directory, int NoFollow)? ArchitectureFlags = RuntimeInformation.ProcessArchitecture switch
    {
        Architecture.X64 => (0x10000, 0x20000),
        Architecture.Arm64 => (0x4000, 0x8000),
        _ => null,
    };

    private const int OpenReadOnly = 0;
    private const int OpenNonBlocking = 0x800;
    private const int OpenCloseOnExec = 0x80000;
    private const int AtSymlinkNoFollow = 0x100;
    private const int AtRemoveDirectory = 0x200;
    private const int AtEmptyPath = 0x1000;
    private const uint StatxType = 0x1;
    private const uint StatxMtime = 0x40;
    private const uint StatxSize = 0x200;
    private const int StatxBufferBytes = 256;
    private const ushort FileTypeMask = 0xF000;
    private const ushort FileTypeDirectory = 0x4000;
    private const ushort FileTypeRegular = 0x8000;
    private const int ErrorNoEntry = 2;
    private const int ErrorNotDirectory = 20;
    private const int ErrorNotEmpty = 39;
    private const int ErrorLoop = 40;
    private const int DirectoryBufferBytes = 32 * 1024;

    private static readonly byte[] EmptyPath = [0];
    private int _descriptor;

    private LinuxStagingDirectory(int descriptor) => _descriptor = descriptor;

    /// <summary>
    /// A verified open-flag ABI and a libc that exports <c>statx</c> (glibc 2.28) and
    /// <c>getdents64</c> (glibc 2.30). Without them the janitor reports itself unsupported
    /// (1411) instead of failing every cycle.
    /// </summary>
    public static bool ArchitectureSupported =>
        ArchitectureFlags is not null && LibraryExportsAvailable.Value && FlagsVerified.Value;

    /// <summary>
    /// Proves the open flags on the running kernel rather than trusting header knowledge:
    /// a symbolic link and a regular file must both be refused as directory anchors, and a
    /// real directory must open. Any other outcome, or no writable temporary directory,
    /// reports the platform unsupported (1411) and nothing is ever deleted.
    /// </summary>
    private static readonly Lazy<bool> FlagsVerified = new(VerifyFlags);

    private static readonly Lazy<bool> LibraryExportsAvailable = new(() =>
        NativeLibrary.TryLoad("libc", typeof(LinuxStagingDirectory).Assembly, null, out var library) &&
        NativeLibrary.TryGetExport(library, "statx", out _) &&
        NativeLibrary.TryGetExport(library, "getdents64", out _) &&
        NativeLibrary.TryGetExport(library, "openat", out _) &&
        NativeLibrary.TryGetExport(library, "unlinkat", out _));

    private static bool VerifyFlags()
    {
        if (ArchitectureFlags is null || !LibraryExportsAvailable.Value)
            return false;
        var probe = Path.Combine(Path.GetTempPath(), $"mavi-staging-flag-probe-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(Path.Combine(probe, "directory"));
            File.WriteAllBytes(Path.Combine(probe, "file"), []);
            File.CreateSymbolicLink(Path.Combine(probe, "link"), Path.Combine(probe, "directory"));

            var root = Open(NativeName(probe), DirectoryFlags);
            if (root < 0)
                return false;
            try
            {
                return OpenChild(root, NativeName("directory"), out var directory) == StagingChildOpen.Opened &&
                       Close(directory) == 0 &&
                       OpenChild(root, NativeName("link"), out _) == StagingChildOpen.NotARealDirectory &&
                       OpenChild(root, NativeName("file"), out _) == StagingChildOpen.NotARealDirectory;
            }
            finally
            {
                _ = Close(root);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
        finally
        {
            try
            {
                if (Directory.Exists(probe))
                {
                    File.Delete(Path.Combine(probe, "link"));
                    Directory.Delete(probe, recursive: true);
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // A leftover empty probe directory under the temp path is harmless.
            }
        }
    }

    private static int DirectoryFlags =>
        OpenReadOnly | OpenNonBlocking | OpenCloseOnExec | ArchitectureFlags!.Value.Directory | ArchitectureFlags.Value.NoFollow;

    public static new LinuxStagingDirectory OpenRoot(string path)
    {
        var descriptor = Open(NativeName(path), DirectoryFlags);
        if (descriptor < 0)
        {
            var error = Marshal.GetLastPInvokeError();
            if (error is ErrorLoop or ErrorNotDirectory)
                throw new StagingPathEscapeException("The media root is not a real directory.");
            throw new IOException("Unable to open the media root for staging reclamation.", new Win32Exception(error));
        }

        return new LinuxStagingDirectory(descriptor);
    }

    public override DateTimeOffset LastWriteTimeUtc
    {
        get
        {
            var buffer = new byte[StatxBufferBytes];
            if (Statx(_descriptor, EmptyPath, AtEmptyPath, StatxMtime, buffer) != 0)
                throw LastError("Unable to read a staging directory's metadata.");
            return ModificationTime(buffer);
        }
    }

    public override StagingChildOpen TryOpenChildDirectory(string name, out StagingDirectory? child)
    {
        var result = OpenChild(_descriptor, NativeName(name), out var descriptor);
        child = result == StagingChildOpen.Opened ? new LinuxStagingDirectory(descriptor) : null;
        return result;
    }

    public override IReadOnlyList<StagingChildEntry> ListChildren()
    {
        var entries = new List<StagingChildEntry>();
        var buffer = new byte[StatxBufferBytes];
        foreach (var name in ReadNames(_descriptor))
        {
            if (Statx(_descriptor, name, AtSymlinkNoFollow, StatxType | StatxMtime, buffer) != 0)
            {
                if (Marshal.GetLastPInvokeError() == ErrorNoEntry)
                    continue;
                throw LastError("Unable to classify a staging entry.");
            }

            entries.Add(new StagingChildEntry(
                DecodeName(name),
                (Mode(buffer) & FileTypeMask) == FileTypeDirectory,
                ModificationTime(buffer)));
        }

        return entries;
    }

    public override long? RemoveChildTree(string name)
    {
        var native = NativeName(name);
        switch (OpenChild(_descriptor, native, out var descriptor))
        {
            case StagingChildOpen.Missing:
                return null;
            case StagingChildOpen.NotARealDirectory:
                throw new StagingPathEscapeException("A staging attempt entry is not a real directory.");
        }

        long freed;
        try
        {
            freed = RemoveContents(descriptor, depth: 1);
        }
        finally
        {
            _ = Close(descriptor);
        }

        if (UnlinkAt(_descriptor, native, AtRemoveDirectory) != 0 && Marshal.GetLastPInvokeError() != ErrorNoEntry)
            throw LastError("Unable to remove a staging attempt directory.");
        return freed;
    }

    public override bool TryRemoveEmptyChildDirectory(string name)
    {
        var native = NativeName(name);
        var buffer = new byte[StatxBufferBytes];
        if (Statx(_descriptor, native, AtSymlinkNoFollow, StatxType, buffer) != 0)
        {
            if (Marshal.GetLastPInvokeError() == ErrorNoEntry)
                return false;
            throw LastError("Unable to classify a staging job directory.");
        }

        if ((Mode(buffer) & FileTypeMask) != FileTypeDirectory)
            return false;
        if (UnlinkAt(_descriptor, native, AtRemoveDirectory) == 0)
            return true;
        var error = Marshal.GetLastPInvokeError();
        if (error is ErrorNoEntry or ErrorNotEmpty or ErrorNotDirectory)
            return false;
        throw new IOException("Unable to remove an empty staging job directory.", new Win32Exception(error));
    }

    public override void Dispose()
    {
        var descriptor = Interlocked.Exchange(ref _descriptor, -1);
        if (descriptor >= 0)
            _ = Close(descriptor);
    }

    private static long RemoveContents(int directory, int depth)
    {
        EnsureDepth(depth);
        long freed = 0;
        var buffer = new byte[StatxBufferBytes];
        foreach (var name in ReadNames(directory))
        {
            if (Statx(directory, name, AtSymlinkNoFollow, StatxType | StatxSize, buffer) != 0)
            {
                if (Marshal.GetLastPInvokeError() == ErrorNoEntry)
                    continue;
                throw LastError("Unable to classify a staging entry.");
            }

            var type = Mode(buffer) & FileTypeMask;
            if (type == FileTypeDirectory)
            {
                switch (OpenChild(directory, name, out var child))
                {
                    case StagingChildOpen.Missing:
                        continue;
                    case StagingChildOpen.NotARealDirectory:
                        // Replaced by a link or file after classification: remove the entry itself.
                        UnlinkEntry(directory, name, removeDirectory: false);
                        continue;
                }

                try
                {
                    freed += RemoveContents(child, depth + 1);
                }
                finally
                {
                    _ = Close(child);
                }

                UnlinkEntry(directory, name, removeDirectory: true);
                continue;
            }

            // Files, symbolic links, FIFOs and sockets: unlinkat removes the entry and never follows it.
            if (type == FileTypeRegular)
                freed += (long)BitConverter.ToUInt64(buffer, 40);
            UnlinkEntry(directory, name, removeDirectory: false);
        }

        return freed;
    }

    private static void UnlinkEntry(int directory, byte[] name, bool removeDirectory)
    {
        if (UnlinkAt(directory, name, removeDirectory ? AtRemoveDirectory : 0) != 0 &&
            Marshal.GetLastPInvokeError() != ErrorNoEntry)
            throw LastError("Unable to remove a staging entry.");
    }

    private static StagingChildOpen OpenChild(int parent, byte[] name, out int descriptor)
    {
        descriptor = OpenAt(parent, name, DirectoryFlags);
        if (descriptor >= 0)
            return StagingChildOpen.Opened;
        var error = Marshal.GetLastPInvokeError();
        return error switch
        {
            ErrorNoEntry => StagingChildOpen.Missing,
            ErrorLoop or ErrorNotDirectory => StagingChildOpen.NotARealDirectory,
            _ => throw new IOException("Unable to open a staging directory.", new Win32Exception(error)),
        };
    }

    private static List<byte[]> ReadNames(int directory)
    {
        // A duplicate descriptor keeps this listing's read position independent of any
        // other listing of the same directory; openat on the original stays valid.
        var names = new List<byte[]>();
        var listing = OpenAt(directory, [(byte)'.', 0], DirectoryFlags);
        if (listing < 0)
        {
            // The held directory was removed concurrently (the worker's own cleanup or
            // another janitor): "." no longer resolves and there is nothing left to list.
            if (Marshal.GetLastPInvokeError() == ErrorNoEntry)
                return names;
            throw LastError("Unable to list a staging directory.");
        }
        try
        {
            var buffer = new byte[DirectoryBufferBytes];
            while (true)
            {
                var read = (long)GetDents64(listing, buffer, (nuint)buffer.Length);
                if (read < 0)
                {
                    // Reading a directory that has since been removed reports ENOENT.
                    if (Marshal.GetLastPInvokeError() == ErrorNoEntry)
                        return names;
                    throw LastError("Unable to list a staging directory.");
                }
                if (read == 0)
                    return names;

                // struct linux_dirent64: d_ino u64, d_off s64, d_reclen u16, d_type u8, d_name[].
                for (var offset = 0; offset < read;)
                {
                    var length = BitConverter.ToUInt16(buffer, offset + 16);
                    var start = offset + 19;
                    var end = Array.IndexOf(buffer, (byte)0, start, offset + length - start);
                    var nameLength = (end < 0 ? offset + length : end) - start;
                    if (!(nameLength == 1 && buffer[start] == '.') &&
                        !(nameLength == 2 && buffer[start] == '.' && buffer[start + 1] == '.'))
                    {
                        var name = new byte[nameLength + 1];
                        Buffer.BlockCopy(buffer, start, name, 0, nameLength);
                        names.Add(name);
                    }

                    offset += length;
                }
            }
        }
        finally
        {
            _ = Close(listing);
        }
    }

    private static ushort Mode(byte[] statx) => BitConverter.ToUInt16(statx, 28);

    private static DateTimeOffset ModificationTime(byte[] statx) =>
        DateTimeOffset.FromUnixTimeSeconds(BitConverter.ToInt64(statx, 112))
            .AddTicks(BitConverter.ToUInt32(statx, 120) / 100);

    private static byte[] NativeName(string name)
    {
        var bytes = new byte[Encoding.UTF8.GetByteCount(name) + 1];
        Encoding.UTF8.GetBytes(name, bytes);
        if (Array.IndexOf(bytes, (byte)0, 0, bytes.Length - 1) >= 0)
            throw new ArgumentException("A staging name may not contain NUL.", nameof(name));
        return bytes;
    }

    private static readonly UTF8Encoding StrictUtf8 = new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    private static string? DecodeName(byte[] nullTerminated)
    {
        try
        {
            return StrictUtf8.GetString(nullTerminated, 0, nullTerminated.Length - 1);
        }
        catch (DecoderFallbackException)
        {
            return null;
        }
    }

    private static IOException LastError(string message) =>
        new(message, new Win32Exception(Marshal.GetLastPInvokeError()));

#pragma warning disable SYSLIB1054 // Matches DurableFilePublication: plain DllImport, no unsafe code generation.
    [DllImport("libc", EntryPoint = "open", SetLastError = true)]
    private static extern int Open(byte[] path, int flags);

    [DllImport("libc", EntryPoint = "openat", SetLastError = true)]
    private static extern int OpenAt(int directory, byte[] path, int flags);

    [DllImport("libc", EntryPoint = "unlinkat", SetLastError = true)]
    private static extern int UnlinkAt(int directory, byte[] path, int flags);

    [DllImport("libc", EntryPoint = "statx", SetLastError = true)]
    private static extern int Statx(int directory, byte[] path, int flags, uint mask, byte[] buffer);

    [DllImport("libc", EntryPoint = "getdents64", SetLastError = true)]
    private static extern nint GetDents64(int descriptor, byte[] buffer, nuint count);

    [DllImport("libc", EntryPoint = "close", SetLastError = true)]
    private static extern int Close(int descriptor);
#pragma warning restore SYSLIB1054
}

/// <summary>Windows: <c>NtCreateFile</c> relative to a held handle, reparse points opened, never followed.</summary>
internal sealed class WindowsStagingDirectory : StagingDirectory
{
    private const uint FileListDirectory = 0x0001;
    private const uint FileReadData = 0x0001;
    private const uint FileTraverse = 0x0020;
    private const uint FileReadAttributes = 0x0080;
    private const uint Delete = 0x00010000;
    private const uint Synchronize = 0x00100000;
    // Anchors never request FILE_DELETE_CHILD (see the worker's _DIR_ACCESS): each child is
    // deleted through DELETE access on its own handle.
    private const uint AnchorAccess = FileListDirectory | FileTraverse | FileReadAttributes | Synchronize;
    private const uint CleanupAccess = FileReadData | FileReadAttributes | Delete | Synchronize;
    private const uint ShareAll = 0x7;
    private const uint FileOpen = 0x1;
    private const uint FileSynchronousIoNonAlert = 0x20;
    private const uint FileOpenReparsePoint = 0x00200000;
    private const uint ObjCaseInsensitive = 0x40;
    private const uint OpenExisting = 3;
    private const uint FlagBackupSemantics = 0x02000000;
    private const uint FlagOpenReparsePoint = 0x00200000;
    private const uint AttributeDirectory = 0x10;
    private const uint AttributeReparsePoint = 0x400;
    private const int FileNamesInformationClass = 12;
    private const int FileDispositionInformationClass = 13;
    private const int StatusNoMoreFiles = unchecked((int)0x80000006);
    private const int StatusBufferOverflow = unchecked((int)0x80000005);
    private const int StatusDirectoryNotEmpty = unchecked((int)0xC0000101);
    private static readonly int[] MissingStatuses =
    [
        unchecked((int)0xC0000034), // STATUS_OBJECT_NAME_NOT_FOUND
        unchecked((int)0xC000003A), // STATUS_OBJECT_PATH_NOT_FOUND
        unchecked((int)0xC000000F), // STATUS_NO_SUCH_FILE
        unchecked((int)0xC0000056), // STATUS_DELETE_PENDING
    ];
    private const int DirectoryBufferBytes = 64 * 1024;

    private readonly SafeFileHandle _handle;

    private WindowsStagingDirectory(SafeFileHandle handle) => _handle = handle;

    public static new WindowsStagingDirectory OpenRoot(string path)
    {
        var handle = CreateFile(path, AnchorAccess, ShareAll, IntPtr.Zero, OpenExisting,
            FlagBackupSemantics | FlagOpenReparsePoint, IntPtr.Zero);
        if (handle.IsInvalid)
            throw new IOException("Unable to open the media root for staging reclamation.",
                new Win32Exception(Marshal.GetLastPInvokeError()));
        var information = Information(handle);
        if (!IsRealDirectory(information.FileAttributes))
        {
            handle.Dispose();
            throw new StagingPathEscapeException("The media root is not a real directory.");
        }

        return new WindowsStagingDirectory(handle);
    }

    public override DateTimeOffset LastWriteTimeUtc => Information(_handle).LastWriteTime.ToUtc();

    public override StagingChildOpen TryOpenChildDirectory(string name, out StagingDirectory? child)
    {
        child = null;
        var handle = OpenRelative(_handle, name, AnchorAccess);
        if (handle is null)
            return StagingChildOpen.Missing;
        if (!IsRealDirectory(Information(handle).FileAttributes))
        {
            handle.Dispose();
            return StagingChildOpen.NotARealDirectory;
        }

        child = new WindowsStagingDirectory(handle);
        return StagingChildOpen.Opened;
    }

    public override IReadOnlyList<StagingChildEntry> ListChildren()
    {
        var entries = new List<StagingChildEntry>();
        foreach (var name in ReadNames(_handle))
        {
            using var child = OpenRelative(_handle, name, FileReadAttributes | Synchronize);
            if (child is null)
                continue;
            var information = Information(child);
            entries.Add(new StagingChildEntry(name, IsRealDirectory(information.FileAttributes), information.LastWriteTime.ToUtc()));
        }

        return entries;
    }

    public override long? RemoveChildTree(string name)
    {
        using var attempt = OpenRelative(_handle, name, CleanupAccess);
        if (attempt is null)
            return null;
        if (!IsRealDirectory(Information(attempt).FileAttributes))
            throw new StagingPathEscapeException("A staging attempt entry is not a real directory.");

        var freed = RemoveContents(attempt, depth: 1);
        MarkDelete(attempt, tolerateNotEmpty: false);
        return freed;
    }

    public override bool TryRemoveEmptyChildDirectory(string name)
    {
        using var directory = OpenRelative(_handle, name, CleanupAccess);
        if (directory is null || !IsRealDirectory(Information(directory).FileAttributes))
            return false;
        return MarkDelete(directory, tolerateNotEmpty: true);
    }

    public override void Dispose() => _handle.Dispose();

    private static long RemoveContents(SafeFileHandle directory, int depth)
    {
        EnsureDepth(depth);
        long freed = 0;
        foreach (var name in ReadNames(directory))
        {
            using var child = OpenRelative(directory, name, CleanupAccess);
            if (child is null)
                continue;
            var information = Information(child);
            var attributes = information.FileAttributes;
            if (IsRealDirectory(attributes))
                freed += RemoveContents(child, depth + 1);
            else if ((attributes & (AttributeDirectory | AttributeReparsePoint)) == 0)
                freed += ((long)information.FileSizeHigh << 32) | information.FileSizeLow;

            // A junction or symbolic link was opened as the reparse point itself, so this
            // deletes the entry and never its target.
            MarkDelete(child, tolerateNotEmpty: false);
        }

        return freed;
    }

    private static bool IsRealDirectory(uint attributes) =>
        (attributes & AttributeDirectory) != 0 && (attributes & AttributeReparsePoint) == 0;

    private static bool MarkDelete(SafeFileHandle handle, bool tolerateNotEmpty)
    {
        byte delete = 1;
        var status = NtSetInformationFile(handle, out _, ref delete, 1, FileDispositionInformationClass);
        if (status >= 0)
            return true;
        if (tolerateNotEmpty && status == StatusDirectoryNotEmpty)
            return false;
        throw new IOException($"Unable to delete a staging entry (NTSTATUS 0x{status:X8}).");
    }

    private static SafeFileHandle? OpenRelative(SafeFileHandle parent, string name, uint access)
    {
        if (name.Length == 0 || name.Contains('\0', StringComparison.Ordinal) || name.Length * 2 > ushort.MaxValue - 2)
            throw new ArgumentException("A staging name is not a valid relative component.", nameof(name));

        var nameBuffer = Marshal.StringToHGlobalUni(name);
        var unicode = Marshal.AllocHGlobal(Marshal.SizeOf<UnicodeString>());
        var added = false;
        try
        {
            Marshal.StructureToPtr(
                new UnicodeString { Length = (ushort)(name.Length * 2), MaximumLength = (ushort)(name.Length * 2 + 2), Buffer = nameBuffer },
                unicode,
                fDeleteOld: false);
            parent.DangerousAddRef(ref added);
            var attributes = new ObjectAttributes
            {
                Length = Marshal.SizeOf<ObjectAttributes>(),
                RootDirectory = parent.DangerousGetHandle(),
                ObjectName = unicode,
                Attributes = ObjCaseInsensitive,
            };
            var status = NtCreateFile(out var raw, access, ref attributes, out _, IntPtr.Zero, 0, ShareAll, FileOpen,
                FileOpenReparsePoint | FileSynchronousIoNonAlert, IntPtr.Zero, 0);
            if (status >= 0)
                return new SafeFileHandle(raw, ownsHandle: true);
            if (Array.IndexOf(MissingStatuses, status) >= 0)
                return null;
            throw new IOException($"Unable to open a staging entry (NTSTATUS 0x{status:X8}).");
        }
        finally
        {
            if (added)
                parent.DangerousRelease();
            Marshal.FreeHGlobal(unicode);
            Marshal.FreeHGlobal(nameBuffer);
        }
    }

    private static List<string> ReadNames(SafeFileHandle directory)
    {
        var names = new List<string>();
        var buffer = Marshal.AllocHGlobal(DirectoryBufferBytes);
        try
        {
            var restart = true;
            while (true)
            {
                var status = NtQueryDirectoryFile(directory, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, out var io, buffer,
                    DirectoryBufferBytes, FileNamesInformationClass, returnSingleEntry: false, IntPtr.Zero, restart);
                restart = false;
                if (status == StatusNoMoreFiles)
                    return names;
                if (status < 0 && status != StatusBufferOverflow)
                    throw new IOException($"Unable to list a staging directory (NTSTATUS 0x{status:X8}).");

                var returned = (long)io.Information;
                if (returned == 0)
                    return names;

                // FILE_NAMES_INFORMATION: NextEntryOffset u32, FileIndex u32, FileNameLength u32, FileName[].
                for (var offset = 0L; offset < returned;)
                {
                    var entry = buffer + (nint)offset;
                    var next = Marshal.ReadInt32(entry, 0);
                    var nameBytes = Marshal.ReadInt32(entry, 8);
                    var name = Marshal.PtrToStringUni(entry + 12, nameBytes / 2);
                    if (name is not "." and not "..")
                        names.Add(name);
                    if (next == 0)
                        break;
                    offset += next;
                }
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static ByHandleFileInformation Information(SafeFileHandle handle)
    {
        if (!GetFileInformationByHandle(handle, out var information))
            throw new IOException("Unable to read staging entry metadata.", new Win32Exception(Marshal.GetLastPInvokeError()));
        return information;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct UnicodeString
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ObjectAttributes
    {
        public int Length;
        public IntPtr RootDirectory;
        public IntPtr ObjectName;
        public uint Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoStatusBlock
    {
        public IntPtr Status;
        public UIntPtr Information;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint Low;
        public uint High;

        public readonly DateTimeOffset ToUtc() =>
            new(DateTime.FromFileTimeUtc(((long)High << 32) | Low), TimeSpan.Zero);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public FileTime CreationTime;
        public FileTime LastAccessTime;
        public FileTime LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

#pragma warning disable SYSLIB1054 // Matches StorageRootSafety: plain DllImport, no unsafe code generation.
    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtCreateFile(
        out IntPtr fileHandle,
        uint desiredAccess,
        ref ObjectAttributes objectAttributes,
        out IoStatusBlock ioStatusBlock,
        IntPtr allocationSize,
        uint fileAttributes,
        uint shareAccess,
        uint createDisposition,
        uint createOptions,
        IntPtr eaBuffer,
        uint eaLength);

    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtQueryDirectoryFile(
        SafeFileHandle fileHandle,
        IntPtr eventHandle,
        IntPtr apcRoutine,
        IntPtr apcContext,
        out IoStatusBlock ioStatusBlock,
        IntPtr fileInformation,
        uint length,
        int fileInformationClass,
        [MarshalAs(UnmanagedType.U1)] bool returnSingleEntry,
        IntPtr fileName,
        [MarshalAs(UnmanagedType.U1)] bool restartScan);

    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtSetInformationFile(
        SafeFileHandle fileHandle,
        out IoStatusBlock ioStatusBlock,
        ref byte fileInformation,
        uint length,
        int fileInformationClass);

    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out ByHandleFileInformation information);
#pragma warning restore SYSLIB1054
}
