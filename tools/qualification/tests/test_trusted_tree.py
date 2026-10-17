"""IP-5 W1: the trusted scorer working tree and virtual environment refuse write access by other accounts.

Plan rev 4 §4.6 "Trusted scorer environment" and §4.13 W1. The check is a helper for trusted-host (T-host) executions
only; repository verification and CI never call it. Every test works on a scratch directory created here: no real
checkout, virtual environment or ACL is touched.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from model_selection import trusted_tree as tt
from model_selection.credibility import CredibilityError

WINDOWS = os.name == "nt"
SYSTEM, ADMINISTRATORS, AUTHENTICATED_USERS, EVERYONE = "S-1-5-18", "S-1-5-32-544", "S-1-5-11", "S-1-1-0"


def refused(prefix, function, *args, **kwargs):
    with pytest.raises(CredibilityError) as error:
        function(*args, **kwargs)
    assert str(error.value).startswith(prefix), str(error.value)
    return str(error.value)


def current_sid() -> str:
    out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    return out.strip().rsplit(",", 1)[-1].strip('"')


def icacls(path: Path, *args: str) -> None:
    subprocess.run(["icacls", str(path), *args], capture_output=True, text=True, check=True)


def scratch_tree(tmp_path: Path) -> Path:
    """A small tree shaped like a checkout plus venv, writable only by the allowed principals."""
    root = tmp_path / "trusted"
    (root / ".venv" / "Lib" / "site-packages").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "tools" / "scorer.py").write_text("x = 1\n")
    (root / ".venv" / "Lib" / "site-packages" / "allowed.pth").write_text("\n")
    if WINDOWS:
        me = current_sid()
        icacls(root, "/inheritance:r", "/grant:r", f"*{SYSTEM}:(OI)(CI)F", f"*{ADMINISTRATORS}:(OI)(CI)F",
               f"*{me}:(OI)(CI)F")
        for path in root.rglob("*"):
            icacls(path, "/reset")  # inherit only the root's protected DACL
    else:
        for path in [root, *root.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
    return root


def allowed() -> tuple[str, ...]:
    return (current_sid(),) if WINDOWS else (str(os.getuid()),)


def test_w1_a_tree_writable_only_by_the_scorer_administrators_and_system_is_accepted(tmp_path):
    root = scratch_tree(tmp_path)
    assert tt.check_trusted_tree([root], scorer_accounts=allowed()) >= 5


@pytest.mark.skipif(not WINDOWS, reason="Windows DACL shape of this host (Authenticated Users:(M))")
def test_w1_this_hosts_authenticated_users_modify_shape_is_refused(tmp_path):
    root = scratch_tree(tmp_path)
    icacls(root / ".venv" / "Lib" / "site-packages", "/grant", f"*{AUTHENTICATED_USERS}:(OI)(CI)M")
    message = refused("trusted_tree_writable_by_others", tt.check_trusted_tree, [root], scorer_accounts=allowed())
    assert AUTHENTICATED_USERS in message and "site-packages" in message


@pytest.mark.skipif(not WINDOWS, reason="Windows DACL")
@pytest.mark.parametrize("grant", [f"*{EVERYONE}:(W)", f"*{AUTHENTICATED_USERS}:(AD)", f"*{EVERYONE}:(WDAC)",
                                   f"*{EVERYONE}:(DE)"])
def test_w1_a_single_file_writable_by_another_account_is_refused(tmp_path, grant):
    root = scratch_tree(tmp_path)
    icacls(root / "tools" / "scorer.py", "/grant", grant)
    refused("trusted_tree_writable_by_others", tt.check_trusted_tree, [root], scorer_accounts=allowed())


@pytest.mark.skipif(not WINDOWS, reason="Windows DACL")
def test_w1_read_and_execute_for_others_is_accepted(tmp_path):
    root = scratch_tree(tmp_path)
    icacls(root, "/grant", f"*{AUTHENTICATED_USERS}:(OI)(CI)RX")
    assert tt.check_trusted_tree([root], scorer_accounts=allowed()) >= 5


@pytest.mark.skipif(WINDOWS, reason="POSIX mode bits")
@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777])
def test_w1_group_or_other_write_is_refused_on_posix(tmp_path, mode):
    root = scratch_tree(tmp_path)
    (root / ".venv" / "Lib" / "site-packages").chmod(mode)
    refused("trusted_tree_writable_by_others", tt.check_trusted_tree, [root], scorer_accounts=allowed())


def test_w1_an_owner_outside_the_allow_list_is_refused(tmp_path):
    if not WINDOWS and os.getuid() == 0:
        pytest.skip("running as root: a root-owned tree is always allowed on POSIX")
    root = scratch_tree(tmp_path)
    other = ("S-1-5-21-1-2-3-4242",) if WINDOWS else (str(os.getuid() + 4242),)
    refused("trusted_tree_writable_by_others", tt.check_trusted_tree, [root], scorer_accounts=other)


def test_w1_an_unknown_scorer_account_is_refused(tmp_path):
    root = scratch_tree(tmp_path)
    refused("trusted_tree_account_unknown", tt.check_trusted_tree, [root],
            scorer_accounts=("mavi-scorer-does-not-exist-4242",))


def test_w1_a_missing_root_is_refused(tmp_path):
    refused("trusted_tree_absent", tt.check_trusted_tree, [tmp_path / "absent"], scorer_accounts=allowed())


@pytest.mark.skipif(WINDOWS, reason="POSIX symlink semantics")
def test_w1_a_symlink_to_a_writable_target_is_refused_and_not_descended(tmp_path):
    root = scratch_tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o777)
    (root / "tools" / "link").symlink_to(outside, target_is_directory=True)
    refused("trusted_tree_writable_by_others", tt.check_trusted_tree, [root], scorer_accounts=allowed())
    outside.chmod(stat.S_IRWXU)
    assert tt.check_trusted_tree([root], scorer_accounts=allowed()) >= 5


def test_w1_is_not_reachable_from_repository_verification_or_ci():
    """Scope: W1 is a trusted-host check; verify_repo and the CI workflows never call it."""
    repo = Path(__file__).resolve().parents[3]
    for rel in ("tools/verify_repo.py", ".github/workflows/quality-gate.yml"):
        assert "trusted_tree" not in (repo / rel).read_text(encoding="utf-8"), rel
