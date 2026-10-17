"""IP-5 W1: the trusted scorer's working tree and virtual environment must not be writable by other accounts.

Plan rev 4 §4.6 ("Trusted scorer environment") and §4.13 W1. A trusted-host (T-host) execution refuses a tree that any
account other than the scorer account(s), ``Administrators`` and ``SYSTEM`` (Windows) or the owner and ``root``
(POSIX) can modify (``trusted_tree_writable_by_others``): such an account could plant a ``.pth`` file or replace a
module that the scorer then executes.

Scope: T-host executions only. Repository verification (``tools/verify_repo.py``) and CI never call this check (a CI
runner or a developer checkout is not a trusted scorer environment), so it cannot affect them.

What is checked, for every root and every entry below it (links are not followed into; a link's target is checked
itself):

* Windows: the owner and every allow ACE of the DACL that is not inherit-only. The owner must be an allowed principal
  (an owner can always rewrite the DACL); an ACE granting any modifying right (write/append data, add file or
  subdirectory, delete, delete child, write attributes or extended attributes, write DAC, take ownership, generic
  write or all) must name an allowed principal (``OWNER RIGHTS`` counts as the owner). Deny ACEs are ignored (they are
  never needed for a pass), a NULL DACL refuses, and an allow ACE type this check does not parse refuses.
  Principals are compared by SID, so the result does not depend on the display language.
* POSIX: the owner must be ``root`` or a scorer account; group- and other-write bits refuse; an extended POSIX ACL
  (``system.posix_acl_access``) refuses.

Known limits (stated, not hidden): the ancestors of a root are not checked (the T-host layout places the trusted
trees in scorer-owned locations; that is part of the T-host qualification, IP-3); the check is a point-in-time
snapshot (the T-host runs it at start-up under the scorer account).

Standard library only (``ctypes`` on Windows).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from pathlib import Path

from .credibility import _fail

DEFAULT_SCORER_ACCOUNTS = ("mavi-scorer",)
SYSTEM_SID, ADMINISTRATORS_SID, OWNER_RIGHTS_SID = "S-1-5-18", "S-1-5-32-544", "S-1-3-4"

# Windows access-mask bits that modify an object or its children.
_WRITE_MASK = (0x0002 | 0x0004 | 0x0010 | 0x0040 | 0x0100  # write/add-file, append/add-subdir, EA, delete child, attrs
               | 0x00010000 | 0x00040000 | 0x00080000  # DELETE, WRITE_DAC, WRITE_OWNER
               | 0x10000000 | 0x40000000 | 0x02000000)  # GENERIC_ALL, GENERIC_WRITE, MAXIMUM_ALLOWED
_ALLOW_TYPES = (0x00, 0x09)  # ACCESS_ALLOWED_ACE_TYPE, ACCESS_ALLOWED_CALLBACK_ACE_TYPE (mask at 4, SID at 8)
_DENY_TYPES = (0x01, 0x06, 0x0A, 0x0C)
_INHERIT_ONLY = 0x08


def check_trusted_tree(roots: Iterable[Path], *, scorer_accounts: Iterable[str] = DEFAULT_SCORER_ACCOUNTS) -> int:
    """Refuse (``trusted_tree_writable_by_others:<path>:<principal>``) any entry of the given trees that an account
    outside the allow-list can modify. ``scorer_accounts`` are account names or (Windows) SID strings / (POSIX)
    numeric uids; an account that does not resolve refuses (``trusted_tree_account_unknown``); a missing root refuses
    (``trusted_tree_absent``). Returns the number of entries checked."""
    roots = [Path(r) for r in roots]
    checker = _WindowsChecker(scorer_accounts) if os.name == "nt" else _PosixChecker(scorer_accounts)
    checked = 0
    for root in roots:
        if not root.exists():
            raise _fail("trusted_tree_absent", str(root))
        for path in _entries(root):
            checker.check(path)
            checked += 1
    return checked


def _entries(root: Path):
    """The root and every entry below it, without descending through symbolic links or junctions."""
    yield root
    if _is_link(root) or not root.is_dir():
        return
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs) + sorted(files):
            yield Path(directory) / name
        dirs[:] = sorted(d for d in dirs if not _is_link(Path(directory) / d))


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


class _PosixChecker:
    def __init__(self, accounts: Iterable[str]):
        import pwd
        self.uids = {0}
        for account in accounts:
            if str(account).isdigit():
                self.uids.add(int(account))
                continue
            try:
                self.uids.add(pwd.getpwnam(account).pw_uid)
            except KeyError:
                raise _fail("trusted_tree_account_unknown", str(account)) from None

    def check(self, path: Path) -> None:
        info = os.stat(path)  # a link's target (the link itself carries no permissions)
        if info.st_uid not in self.uids:
            raise _fail("trusted_tree_writable_by_others", f"{path}:uid={info.st_uid}")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise _fail("trusted_tree_writable_by_others", f"{path}:mode={stat.filemode(info.st_mode)}")
        try:
            names = os.listxattr(path)
        except (AttributeError, OSError):
            names = []
        if "system.posix_acl_access" in names:
            raise _fail("trusted_tree_writable_by_others", f"{path}:posix-acl")


class _WindowsChecker:
    def __init__(self, accounts: Iterable[str]):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
        self.advapi32.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p)]
        self.advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi32.GetAce.restype = wintypes.BOOL
        self.advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        self.advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self.advapi32.LookupAccountNameW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_int)]
        self.advapi32.LookupAccountNameW.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p
        self.allowed = {SYSTEM_SID, ADMINISTRATORS_SID}
        for account in accounts:
            account = str(account)
            self.allowed.add(account.upper() if account.upper().startswith("S-1-") else self._lookup(account))

    def _sid_string(self, sid) -> str:
        text = self.wintypes.LPWSTR()
        if not self.advapi32.ConvertSidToStringSidW(sid, self.ctypes.byref(text)):
            raise _fail("trusted_tree_writable_by_others", f"unreadable SID:{self.ctypes.get_last_error()}")
        try:
            return text.value.upper()
        finally:
            self.kernel32.LocalFree(text)

    def _lookup(self, account: str) -> str:
        ctypes, wintypes = self.ctypes, self.wintypes
        sid_size, domain_size, use = wintypes.DWORD(0), wintypes.DWORD(0), ctypes.c_int()
        self.advapi32.LookupAccountNameW(None, account, None, ctypes.byref(sid_size), None, ctypes.byref(domain_size),
                                         ctypes.byref(use))
        if sid_size.value == 0:
            raise _fail("trusted_tree_account_unknown", account)
        sid = ctypes.create_string_buffer(sid_size.value)
        domain = ctypes.create_unicode_buffer(domain_size.value + 1)
        if not self.advapi32.LookupAccountNameW(None, account, sid, ctypes.byref(sid_size), domain,
                                                ctypes.byref(domain_size), ctypes.byref(use)):
            raise _fail("trusted_tree_account_unknown", account)
        return self._sid_string(sid)

    def check(self, path: Path) -> None:
        ctypes = self.ctypes
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        # SE_FILE_OBJECT = 1; OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION = 0x1 | 0x4
        error = self.advapi32.GetNamedSecurityInfoW(str(path), 1, 0x5, ctypes.byref(owner), None, ctypes.byref(dacl),
                                                    None, ctypes.byref(descriptor))
        if error != 0:
            raise _fail("trusted_tree_writable_by_others", f"{path}:security-unreadable:{error}")
        try:
            owner_sid = self._sid_string(owner)
            if owner_sid not in self.allowed:
                raise _fail("trusted_tree_writable_by_others", f"{path}:owner={owner_sid}")
            if not dacl.value:
                raise _fail("trusted_tree_writable_by_others", f"{path}:null-dacl")
            ace_count = ctypes.c_uint16.from_address(dacl.value + 4).value  # ACL: rev, sbz1, size(2), count(2)
            for index in range(ace_count):
                ace = ctypes.c_void_p()
                if not self.advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                    raise _fail("trusted_tree_writable_by_others", f"{path}:ace-unreadable:{index}")
                ace_type = ctypes.c_uint8.from_address(ace.value).value
                ace_flags = ctypes.c_uint8.from_address(ace.value + 1).value
                if ace_flags & _INHERIT_ONLY or ace_type in _DENY_TYPES:
                    continue
                if ace_type not in _ALLOW_TYPES:
                    raise _fail("trusted_tree_writable_by_others", f"{path}:unsupported-ace-type={ace_type}")
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                if not mask & _WRITE_MASK:
                    continue
                principal = self._sid_string(ctypes.c_void_p(ace.value + 8))
                if principal == OWNER_RIGHTS_SID or principal in self.allowed:
                    continue
                raise _fail("trusted_tree_writable_by_others", f"{path}:{principal}:mask=0x{mask:08x}")
        finally:
            self.kernel32.LocalFree(descriptor)
