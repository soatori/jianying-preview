"""Write fences: nothing this project generates may land inside a draft.

Scratch output is confined to the repository's ``temp/``. Any destination that
resolves inside the JianYing drafts corpus, the JianYing install, or a draft's
own folder is refused outright -- milestone 1 is read-only with respect to
drafts, and the fence is what makes that enforceable rather than aspirational.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = REPO_ROOT / "temp"

def _default_draft_roots() -> list[str]:
    """Derive rather than hardcode: this machine keeps the corpus behind a junction."""
    roots = [r"D:\JianyingPro\JianyingPro Drafts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(str(Path(local) / "JianyingPro" / "JianyingPro Drafts"))
    return roots


_DEFAULT_DRAFT_ROOTS = tuple(_default_draft_roots())


def _default_install_roots() -> list[str]:
    """静态两根永远在册，检测到的根再并进来。

    栅栏不能因为检测失败而变窄：``jy_paths`` 不可用时这里照样给出 D/C 两根。
    """
    roots = [r"D:\Program Files\JianyingPro", r"C:\Program Files\JianyingPro"]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import jy_paths

        roots.extend(str(p) for p in jy_paths.guard_roots())
    except Exception:                                 # noqa: BLE001
        pass
    return roots


_DEFAULT_INSTALL_ROOTS = tuple(_default_install_roots())


class WriteFenceError(RuntimeError):
    pass


def _roots(env_var: str, defaults: tuple[str, ...]) -> list[Path]:
    """Resolved, order-preserving unique roots.

    The override is ``os.pathsep``-separated, so one run can cover every draft
    root the machine actually has. ``resolve()`` before deduplication is what
    keeps a junction or a symlinked profile from presenting the same corpus as
    two roots and making callers walk it twice.
    """
    override = os.environ.get(env_var, "").strip()
    values = [v.strip() for v in override.split(os.pathsep)] if override else list(defaults)
    return list(dict.fromkeys(Path(v).resolve() for v in values if v))


def draft_roots() -> list[Path]:
    return _roots("JY_DRAFT_ROOTS", _DEFAULT_DRAFT_ROOTS)


def install_roots() -> list[Path]:
    return _roots("JY_INSTALL_ROOTS", _DEFAULT_INSTALL_ROOTS)


def _under(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return root
    return None


def assert_scratch_target(target: str | Path) -> Path:
    """Return the resolved target, or raise if it is outside temp/ or inside a draft."""
    path = Path(target).resolve()
    hit = _under(path, draft_roots())
    if hit is not None:
        raise WriteFenceError(f"refusing to write inside the draft corpus ({hit}): {path}")
    hit = _under(path, install_roots())
    if hit is not None:
        raise WriteFenceError(f"refusing to write inside the JianYing install ({hit}): {path}")
    try:
        path.relative_to(TEMP_ROOT.resolve())
    except ValueError:
        raise WriteFenceError(f"scratch output must live under {TEMP_ROOT}: {path}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def content_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scratch_dir(*parts: str) -> Path:
    path = TEMP_ROOT.joinpath(*parts)
    return assert_scratch_target(path / ".keep").parent
