"""Write fences: nothing this project generates may land inside a draft.

Scratch output is confined to the repository's ``temp/``. Any destination that
resolves inside the JianYing drafts corpus, the JianYing install, or a draft's
own folder is refused outright -- milestone 1 is read-only with respect to
drafts, and the fence is what makes that enforceable rather than aspirational.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = REPO_ROOT / "temp"

_DEFAULT_DRAFT_ROOTS = (
    r"D:\JianyingPro\JianyingPro Drafts",
    r"C:\Users\11\AppData\Local\JianyingPro\JianyingPro Drafts",
)
_DEFAULT_INSTALL_ROOTS = (
    r"D:\Program Files\JianyingPro",
    r"C:\Program Files\JianyingPro",
)


class WriteFenceError(RuntimeError):
    pass


def _roots(env_var: str, defaults: tuple[str, ...]) -> list[Path]:
    override = os.environ.get(env_var, "").strip()
    values = [override] if override else list(defaults)
    return [Path(v).resolve() for v in values if v]


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


def assert_read_only_source(source: str | Path) -> Path:
    """Sources may be anywhere; we only ever open them for reading."""
    return Path(source)


def content_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scratch_dir(*parts: str) -> Path:
    path = TEMP_ROOT.joinpath(*parts)
    return assert_scratch_target(path / ".keep").parent
