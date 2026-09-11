from __future__ import annotations

import ctypes
import os
from collections.abc import Callable, Iterator
from ctypes import wintypes
from pathlib import Path
from uuid import UUID, uuid4

from mavi_vision.storage.artifact_store import StagingArtifactError


# This backend deliberately uses native relative opens rooted at already-validated
# directory handles. Full path strings are used only to acquire the configured
# media-root handle; every descendant operation is handle-relative.
_IS_WINDOWS = os.name == "nt"

_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

_FILE_READ_DATA = 0x0001
_FILE_LIST_DIRECTORY = 0x0001
_FILE_WRITE_DATA = 0x0002
_FILE_ADD_FILE = 0x0002
_FILE_ADD_SUBDIRECTORY = 0x0004
_FILE_TRAVERSE = 0x0020
_FILE_DELETE_CHILD = 0x0040
_FILE_READ_ATTRIBUTES = 0x0080
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000

_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_SHARE_ALL = _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE

_FILE_OPEN = 0x00000001
_FILE_CREATE = 0x00000002
_FILE_OPEN_IF = 0x00000003

_FILE_DIRECTORY_FILE = 0x00000001
_FILE_WRITE_THROUGH = 0x00000002
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_OPEN_REPARSE_POINT = 0x00200000

_OBJ_CASE_INSENSITIVE = 0x00000040

_FILE_RENAME_INFO_CLASS = 3
_FILE_DISPOSITION_INFO_CLASS = 4
_FILE_NAMES_INFORMATION_CLASS = 12

_STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
_STATUS_OBJECT_PATH_NOT_FOUND = 0xC000003A
_STATUS_NO_SUCH_FILE = 0xC000000F
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035
_STATUS_NO_MORE_FILES = 0x80000006
_STATUS_BUFFER_OVERFLOW = 0x80000005
_MISSING_STATUSES = {
    _STATUS_OBJECT_NAME_NOT_FOUND,
    _STATUS_OBJECT_PATH_NOT_FOUND,
    _STATUS_NO_SUCH_FILE,
}

_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_DIR_ACCESS = (
    _FILE_LIST_DIRECTORY
    | _FILE_ADD_FILE
    | _FILE_ADD_SUBDIRECTORY
    | _FILE_TRAVERSE
    | _FILE_DELETE_CHILD
    | _FILE_READ_ATTRIBUTES
    | _SYNCHRONIZE
)


class _MissingChild(FileNotFoundError):
    pass


class _NameCollision(FileExistsError):
    pass


class _IO_STATUS_UNION(ctypes.Union):
    _fields_ = [
        ("Status", ctypes.c_long),
        ("Pointer", ctypes.c_void_p),
    ]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _IO_STATUS_UNION),
        ("Information", ctypes.c_size_t),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_RENAME_INFO(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", wintypes.BOOL),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]


class _FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


class _FILE_NAMES_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("FileIndex", wintypes.ULONG),
        ("FileNameLength", wintypes.ULONG),
        ("FileName", wintypes.WCHAR * 1),
    ]


if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _GetFileInformationByHandle = _kernel32.GetFileInformationByHandle
    _GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    _GetFileInformationByHandle.restype = wintypes.BOOL

    _WriteFile = _kernel32.WriteFile
    _WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _WriteFile.restype = wintypes.BOOL

    _FlushFileBuffers = _kernel32.FlushFileBuffers
    _FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _FlushFileBuffers.restype = wintypes.BOOL

    _SetFileInformationByHandle = _kernel32.SetFileInformationByHandle
    _SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _SetFileInformationByHandle.restype = wintypes.BOOL

    _NtCreateFile = _ntdll.NtCreateFile
    _NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    _NtCreateFile.restype = ctypes.c_long

    _NtQueryDirectoryFile = _ntdll.NtQueryDirectoryFile
    _NtQueryDirectoryFile.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_ubyte,
        ctypes.POINTER(_UNICODE_STRING),
        ctypes.c_ubyte,
    ]
    _NtQueryDirectoryFile.restype = ctypes.c_long


class _WindowsHandle:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def close(self) -> None:
        if self.value:
            if _IS_WINDOWS:
                _CloseHandle(wintypes.HANDLE(self.value))
            self.value = 0

    def __enter__(self) -> "_WindowsHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _status_code(status: int) -> int:
    return ctypes.c_ulong(status).value


def _raise_last_error(code: str) -> None:
    error = ctypes.get_last_error()
    raise StagingArtifactError(code) from OSError(error, os.strerror(error))


def _unicode_object_attributes(
    parent: _WindowsHandle,
    name: str,
) -> tuple[ctypes.Array, _UNICODE_STRING, _OBJECT_ATTRIBUTES]:
    buffer = ctypes.create_unicode_buffer(name)
    name_bytes = name.encode("utf-16-le")
    unicode_name = _UNICODE_STRING(
        Length=len(name_bytes),
        MaximumLength=len(name_bytes) + 2,
        Buffer=ctypes.cast(buffer, wintypes.LPWSTR),
    )
    attributes = _OBJECT_ATTRIBUTES(
        Length=ctypes.sizeof(_OBJECT_ATTRIBUTES),
        RootDirectory=wintypes.HANDLE(parent.value),
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    return buffer, unicode_name, attributes


def _nt_create_relative(
    parent: _WindowsHandle,
    name: str,
    *,
    desired_access: int,
    disposition: int,
    options: int,
) -> _WindowsHandle:
    if not _IS_WINDOWS:
        raise StagingArtifactError("secure_staging_unavailable")

    handle = wintypes.HANDLE()
    io_status = _IO_STATUS_BLOCK()
    # Keep both the UTF-16 buffer and UNICODE_STRING alive for the syscall.
    buffer, unicode_name, attributes = _unicode_object_attributes(parent, name)
    del buffer, unicode_name

    status = _NtCreateFile(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0,
        _SHARE_ALL,
        disposition,
        options,
        None,
        0,
    )
    code = _status_code(status)
    if status < 0:
        if code in _MISSING_STATUSES:
            raise _MissingChild(name)
        if code == _STATUS_OBJECT_NAME_COLLISION:
            raise _NameCollision(name)
        raise OSError(f"NtCreateFile({name!r}) failed with NTSTATUS 0x{code:08X}")
    return _WindowsHandle(int(handle.value))


def _file_information(handle: _WindowsHandle) -> _BY_HANDLE_FILE_INFORMATION:
    if not _IS_WINDOWS:
        raise StagingArtifactError("secure_staging_unavailable")
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _GetFileInformationByHandle(
        wintypes.HANDLE(handle.value),
        ctypes.byref(info),
    ):
        _raise_last_error("staging_write_failed")
    return info


def _file_attributes(handle: _WindowsHandle) -> int:
    return int(_file_information(handle).dwFileAttributes)


def _is_reparse(handle: _WindowsHandle) -> bool:
    return bool(_file_attributes(handle) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_directory(handle: _WindowsHandle) -> bool:
    return bool(_file_attributes(handle) & _FILE_ATTRIBUTE_DIRECTORY)


def _directory_identity(handle: _WindowsHandle) -> tuple[int, int]:
    info = _file_information(handle)
    file_index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
    return int(info.dwVolumeSerialNumber), file_index


def _open_directory_no_reparse(path: Path) -> _WindowsHandle:
    if not _IS_WINDOWS:
        raise StagingArtifactError("secure_staging_unavailable")

    raw = _CreateFileW(
        str(path),
        _DIR_ACCESS,
        _SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    value = int(raw) if raw else 0
    if value in {0, _INVALID_HANDLE_VALUE}:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            raise StagingArtifactError("media_root_missing") from FileNotFoundError(
                error,
                os.strerror(error),
                str(path),
            )
        raise StagingArtifactError("staging_write_failed") from OSError(
            error,
            os.strerror(error),
            str(path),
        )

    handle = _WindowsHandle(value)
    try:
        if _is_reparse(handle) or not _is_directory(handle):
            raise StagingArtifactError("staging_path_escape")
        return handle
    except Exception:
        handle.close()
        raise


def _open_child_directory_no_reparse(
    parent: _WindowsHandle,
    name: str,
    *,
    create: bool,
) -> _WindowsHandle:
    try:
        handle = _nt_create_relative(
            parent,
            name,
            desired_access=_DIR_ACCESS,
            disposition=_FILE_OPEN_IF if create else _FILE_OPEN,
            options=(
                _FILE_DIRECTORY_FILE
                | _FILE_OPEN_REPARSE_POINT
                | _FILE_SYNCHRONOUS_IO_NONALERT
            ),
        )
    except _MissingChild:
        raise
    except OSError as exc:
        raise StagingArtifactError(
            "staging_write_failed" if create else "staging_path_race"
        ) from exc

    try:
        if _is_reparse(handle) or not _is_directory(handle):
            raise StagingArtifactError("staging_path_escape")
        return handle
    except Exception:
        handle.close()
        raise


def _create_exclusive_child_file(
    parent: _WindowsHandle,
    name: str,
) -> _WindowsHandle:
    try:
        handle = _nt_create_relative(
            parent,
            name,
            desired_access=(
                _FILE_WRITE_DATA
                | _FILE_READ_ATTRIBUTES
                | _DELETE
                | _SYNCHRONIZE
            ),
            disposition=_FILE_CREATE,
            options=(
                _FILE_NON_DIRECTORY_FILE
                | _FILE_OPEN_REPARSE_POINT
                | _FILE_SYNCHRONOUS_IO_NONALERT
                | _FILE_WRITE_THROUGH
            ),
        )
    except (_MissingChild, _NameCollision, OSError) as exc:
        raise StagingArtifactError("staging_write_failed") from exc

    try:
        if _is_reparse(handle) or _is_directory(handle):
            raise StagingArtifactError("staging_path_escape")
        return handle
    except Exception:
        handle.close()
        raise


def _open_child_for_inspection(
    parent: _WindowsHandle,
    name: str,
    *,
    delete_access: bool = False,
) -> _WindowsHandle:
    desired = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    if delete_access:
        desired |= _DELETE | _FILE_READ_DATA
    return _nt_create_relative(
        parent,
        name,
        desired_access=desired,
        disposition=_FILE_OPEN,
        options=_FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT,
    )


def _reject_unsafe_destination(parent: _WindowsHandle, name: str) -> None:
    try:
        handle = _open_child_for_inspection(parent, name)
    except _MissingChild:
        return
    except OSError as exc:
        raise StagingArtifactError("staging_write_failed") from exc

    with handle:
        if _is_reparse(handle) or _is_directory(handle):
            raise StagingArtifactError("staging_path_escape")


def _write_all(handle: _WindowsHandle, content: bytes) -> None:
    if not _IS_WINDOWS:
        raise StagingArtifactError("secure_staging_unavailable")

    view = memoryview(content)
    offset = 0
    while offset < len(view):
        chunk = bytes(view[offset : offset + 1024 * 1024])
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not _WriteFile(
            wintypes.HANDLE(handle.value),
            buffer,
            len(chunk),
            ctypes.byref(written),
            None,
        ):
            _raise_last_error("staging_write_failed")
        if written.value != len(chunk):
            raise StagingArtifactError("staging_write_failed")
        offset += written.value

    if not _FlushFileBuffers(wintypes.HANDLE(handle.value)):
        _raise_last_error("staging_write_failed")


def _replace_child_file(
    parent: _WindowsHandle,
    temporary: _WindowsHandle,
    destination_name: str,
) -> None:
    encoded_name = destination_name.encode("utf-16-le")
    name_offset = _FILE_RENAME_INFO.FileName.offset
    size = name_offset + len(encoded_name)
    buffer = ctypes.create_string_buffer(size)
    info = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFO)).contents
    info.ReplaceIfExists = True
    info.RootDirectory = wintypes.HANDLE(parent.value)
    info.FileNameLength = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + name_offset,
        encoded_name,
        len(encoded_name),
    )

    if not _SetFileInformationByHandle(
        wintypes.HANDLE(temporary.value),
        _FILE_RENAME_INFO_CLASS,
        buffer,
        size,
    ):
        _raise_last_error("staging_write_failed")


def _mark_delete(handle: _WindowsHandle, *, error_code: str) -> None:
    info = _FILE_DISPOSITION_INFO(DeleteFile=True)
    if not _SetFileInformationByHandle(
        wintypes.HANDLE(handle.value),
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        _raise_last_error(error_code)


def _directory_entries(handle: _WindowsHandle) -> Iterator[str]:
    if not _IS_WINDOWS:
        raise StagingArtifactError("secure_staging_unavailable")

    restart = True
    while True:
        buffer = ctypes.create_string_buffer(64 * 1024)
        io_status = _IO_STATUS_BLOCK()
        status = _NtQueryDirectoryFile(
            wintypes.HANDLE(handle.value),
            None,
            None,
            None,
            ctypes.byref(io_status),
            buffer,
            len(buffer),
            _FILE_NAMES_INFORMATION_CLASS,
            0,
            None,
            1 if restart else 0,
        )
        restart = False
        code = _status_code(status)
        if code == _STATUS_NO_MORE_FILES:
            return
        if status < 0 and code != _STATUS_BUFFER_OVERFLOW:
            raise StagingArtifactError("staging_cleanup_failed") from OSError(
                f"NtQueryDirectoryFile failed with NTSTATUS 0x{code:08X}"
            )

        returned = int(io_status.Information)
        offset = 0
        while offset < returned:
            address = ctypes.addressof(buffer) + offset
            entry = ctypes.cast(
                address,
                ctypes.POINTER(_FILE_NAMES_INFORMATION),
            ).contents
            name = ctypes.wstring_at(
                address + _FILE_NAMES_INFORMATION.FileName.offset,
                int(entry.FileNameLength) // ctypes.sizeof(wintypes.WCHAR),
            )
            if name not in {".", ".."}:
                yield name
            if entry.NextEntryOffset == 0:
                break
            offset += int(entry.NextEntryOffset)

        if status >= 0 and returned == 0:
            return


def _open_child_for_cleanup(
    parent: _WindowsHandle,
    name: str,
) -> _WindowsHandle:
    try:
        return _nt_create_relative(
            parent,
            name,
            desired_access=(
                _FILE_READ_DATA
                | _FILE_READ_ATTRIBUTES
                | _DELETE
                | _SYNCHRONIZE
            ),
            disposition=_FILE_OPEN,
            options=_FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT,
        )
    except _MissingChild:
        raise
    except OSError as exc:
        raise StagingArtifactError("staging_cleanup_failed") from exc


def _remove_tree_contents(directory: _WindowsHandle) -> None:
    names = list(_directory_entries(directory))
    for name in names:
        try:
            child = _open_child_for_cleanup(directory, name)
        except _MissingChild:
            continue

        with child:
            attributes = _file_attributes(child)
            is_reparse = bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
            is_directory = bool(attributes & _FILE_ATTRIBUTE_DIRECTORY)
            if is_directory and not is_reparse:
                _remove_tree_contents(child)
            _mark_delete(child, error_code="staging_cleanup_failed")


def _remove_attempt_tree_no_reparse(
    parent: _WindowsHandle,
    name: str,
) -> None:
    try:
        attempt = _open_child_for_cleanup(parent, name)
    except _MissingChild:
        return

    with attempt:
        attributes = _file_attributes(attempt)
        if (
            attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or not attributes & _FILE_ATTRIBUTE_DIRECTORY
        ):
            raise StagingArtifactError("staging_path_escape")
        _remove_tree_contents(attempt)
        _mark_delete(attempt, error_code="staging_cleanup_failed")


class WindowsStagingBackend:
    """Native Windows staging using handle-relative no-reparse operations."""

    def __init__(self, media_root: Path, job_id: UUID, attempt_name: str) -> None:
        if not _IS_WINDOWS:
            raise StagingArtifactError("secure_staging_unavailable")
        self._media_root = media_root
        self._job_id = job_id
        self._attempt_name = attempt_name

    def write_bytes(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        authorize_publish: Callable[[], None] | None,
    ) -> None:
        parent, handles = self._open_parent_chain(parts[:-1], create=True)
        destination_name = parts[-1]
        temp_name = f".{destination_name}.{uuid4().hex}.tmp"
        temporary: _WindowsHandle | None = None
        published = False

        try:
            _reject_unsafe_destination(parent, destination_name)
            expected_parent = _directory_identity(parent)

            temporary = _create_exclusive_child_file(parent, temp_name)
            _write_all(temporary, content)
            _reject_unsafe_destination(parent, destination_name)

            # Revalidate the logical ancestry before handing authority to the
            # lease guard, then make authorization the final check before rename.
            self._assert_logical_parent_identity(parts[:-1], expected_parent)
            if authorize_publish is not None:
                authorize_publish()

            _replace_child_file(parent, temporary, destination_name)
            published = True

            try:
                self._assert_logical_parent_identity(parts[:-1], expected_parent)
            except StagingArtifactError:
                _mark_delete(temporary, error_code="staging_write_failed")
                published = False
                raise
        except Exception:
            if temporary is not None and not published:
                try:
                    _mark_delete(temporary, error_code="staging_write_failed")
                except StagingArtifactError:
                    pass
            raise
        finally:
            if temporary is not None:
                temporary.close()
            self._close_handles(handles)

    def cleanup(self) -> None:
        root = _open_directory_no_reparse(self._media_root)
        staging: _WindowsHandle | None = None
        job: _WindowsHandle | None = None
        try:
            try:
                staging = _open_child_directory_no_reparse(
                    root,
                    "staging",
                    create=False,
                )
            except _MissingChild:
                return

            try:
                job = _open_child_directory_no_reparse(
                    staging,
                    str(self._job_id),
                    create=False,
                )
            except _MissingChild:
                return

            _remove_attempt_tree_no_reparse(job, self._attempt_name)
        except StagingArtifactError:
            raise
        except Exception as exc:
            raise StagingArtifactError("staging_cleanup_failed") from exc
        finally:
            if job is not None:
                job.close()
            if staging is not None:
                staging.close()
            root.close()

    def _open_parent_chain(
        self,
        relative_parts: tuple[str, ...],
        *,
        create: bool,
    ) -> tuple[_WindowsHandle, list[_WindowsHandle]]:
        root = _open_directory_no_reparse(self._media_root)
        handles = [root]
        current = root
        try:
            for part in (
                "staging",
                str(self._job_id),
                self._attempt_name,
                *relative_parts,
            ):
                try:
                    child = _open_child_directory_no_reparse(
                        current,
                        part,
                        create=create,
                    )
                except _MissingChild as exc:
                    raise StagingArtifactError("staging_path_race") from exc
                handles.append(child)
                current = child
            return current, handles
        except Exception:
            self._close_handles(handles)
            raise

    def _assert_logical_parent_identity(
        self,
        relative_parts: tuple[str, ...],
        expected_parent: tuple[int, int],
    ) -> None:
        handles: list[_WindowsHandle] = []
        try:
            parent, handles = self._open_parent_chain(
                relative_parts,
                create=False,
            )
            if _directory_identity(parent) != expected_parent:
                raise StagingArtifactError("staging_path_race")
        except StagingArtifactError as exc:
            if exc.code == "staging_path_escape":
                raise
            raise StagingArtifactError("staging_path_race") from exc
        finally:
            self._close_handles(handles)

    @staticmethod
    def _close_handles(handles: list[_WindowsHandle]) -> None:
        for handle in reversed(handles):
            handle.close()
