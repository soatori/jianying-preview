"""The only module allowed to reach into the jianying-editor skill.

Importing `jianying_project` is safe: it imports `jy_draft_crypto` but the DLL is
only loaded when `JyDraftCrypto()` is constructed. This module never constructs
one outside the decrypt worker subprocess.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SKILLS_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[3],
    Path.home() / ".agents" / "skills",
    Path.home() / ".qoder-cn" / "skills",
    Path.cwd() / ".agents" / "skills",
    Path.cwd() / ".qoder" / "skills",
)

EDITOR_SKILL_NAMES = ("jianying-editor-skill", "jianying-editor")


def find_editor_scripts_dir() -> Path:
    explicit = os.environ.get("JY_EDITOR_SKILL_SCRIPTS", "").strip()
    if explicit:
        path = Path(explicit)
        if (path / "jianying_project.py").is_file():
            return path.resolve()
        raise RuntimeError(f"JY_EDITOR_SKILL_SCRIPTS has no jianying_project.py: {explicit}")

    for skills_dir in SKILLS_DIR_CANDIDATES:
        for name in EDITOR_SKILL_NAMES:
            scripts = skills_dir / name / "scripts"
            if (scripts / "jianying_project.py").is_file():
                return scripts.resolve()
    raise RuntimeError(
        "jianying-editor skill not found. Install it next to this skill or set "
        "JY_EDITOR_SKILL_SCRIPTS to its scripts/ directory."
    )


SCRIPTS_DIR = find_editor_scripts_dir()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from jianying_project import JianyingProject, ProjectError  # noqa: E402
from jy_draft_crypto import JyDraftCrypto, find_jianying_dll, parse_plain_json  # noqa: E402

__all__ = ["JianyingProject", "JyDraftCrypto", "ProjectError", "find_jianying_dll", "parse_plain_json",
           "SCRIPTS_DIR", "assert_no_dll_here", "videoeditor_dll_path"]


def videoeditor_dll_path() -> str | None:
    try:
        return find_jianying_dll()
    except Exception:
        return None


def _loaded_modules() -> set[str]:
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.GetCurrentProcess()
    array = (ctypes.c_void_p * 1024)()
    needed = ctypes.c_ulong()
    if not psapi.EnumProcessModulesEx(handle, ctypes.byref(array), ctypes.sizeof(array),
                                      ctypes.byref(needed), 0x03):
        return set()
    names = set()
    for index in range(int(needed.value / ctypes.sizeof(ctypes.c_void_p))):
        buffer = ctypes.create_unicode_buffer(260)
        if psapi.GetModuleFileNameExW(handle, array[index], buffer, 260):
            names.add(os.path.normcase(buffer.value))
    return names


def assert_no_dll_here() -> None:
    """Fail loudly if this long-lived process ever mapped videoeditor.dll."""
    loaded = _loaded_modules()
    offenders = [name for name in loaded if os.path.basename(name).lower() == "videoeditor.dll"]
    if offenders:
        raise RuntimeError(
            f"videoeditor.dll is loaded in the server process ({offenders[0]}). Decryption must run "
            "in the short-lived jypreview.decrypt.worker subprocess."
        )
