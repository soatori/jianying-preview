"""Runtime configuration for the previewer.

Every fidelity knob that still needs calibration against JianYing lives here so
`calibrate.py` can sweep it without touching model code.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

DEFAULT_PORT = 8765
DRAFT_CACHE_DIRNAME = ".jypreview"
USER_STATE_DIRNAME = ".jypreview"

DRIVE_LETTERS = ("C:", "D:", "E:", "F:")


def _candidate_drafts_roots() -> list[Path]:
    out: list[Path] = []
    for letter in DRIVE_LETTERS:
        root = Path(letter + os.sep)
        out.append(root / "JianyingPro" / "JianyingPro Drafts")
        out.append(root / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / "JianyingPro" / "JianyingPro Drafts")
        out.append(Path(local) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    return out


def _looks_like_draft_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    for child in path.iterdir():
        if not child.is_dir():
            continue
        if (child / "draft_content.json").is_file():
            return True
        timelines = child / "Timelines"
        if timelines.is_dir():
            for sub in timelines.iterdir():
                if sub.is_dir() and (sub / "draft_content.json").is_file():
                    return True
    return False


def detect_drafts_root() -> Path | None:
    for candidate in _candidate_drafts_roots():
        if _looks_like_draft_root(candidate):
            return candidate.resolve()
    return None


def detect_jianying_root(drafts_root: Path | None) -> Path | None:
    """The tree holding `User Data\\Cache\\{effect,artistEffect,ressdk_db}`."""
    roots: list[Path] = []
    if drafts_root is not None:
        roots.extend([drafts_root.parent, drafts_root.parent.parent, drafts_root.parent.parent.parent])
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "JianyingPro")
    for root in roots:
        if (root / "User Data" / "Cache").is_dir():
            return root.resolve()
    return None


def detect_install_root() -> Path | None:
    """Newest ``.../JianyingPro/<version>`` app directory (ships bundled fonts)."""
    candidates: list[Path] = []
    for letter in DRIVE_LETTERS:
        candidates.append(Path(letter + os.sep) / "Program Files" / "JianyingPro")
        candidates.append(Path(letter + os.sep) / "Program Files (x86)" / "JianyingPro")
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "JianyingPro")
    best: tuple[tuple[int, ...], Path] | None = None
    for root in candidates:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            parts = tuple(int(p) for p in entry.name.split(".") if p.isdigit())
            if len(parts) < 3:
                continue
            if best is None or parts > best[0]:
                best = (parts, entry)
    return best[1].resolve() if best else None


@dataclass
class Config:
    drafts_root: Path | None = None
    jianying_root: Path | None = None
    install_root: Path | None = None
    user_state_dir: Path = field(default_factory=lambda: Path.home() / USER_STATE_DIRNAME)
    port: int = DEFAULT_PORT
    host: str = "127.0.0.1"

    cache_location: str = "draft"
    cache_prune_mb: int = 400

    text_size_basis: str = "width"
    # em = font_size * canvas_width * text_scale_factor.  0.00625 == width/160, measured
    # against a real JianYing export (see references/calibration-and-oracle.md); the old
    # 0.01 rendered subtitles 1.6x too large.
    text_scale_factor: float = 0.00625
    transform_y_basis: str = "half"
    y_sign: str = "jianying_up"
    fit_mode: str = "contain_unrotated"
    line_spacing_divisor: float = 50.0
    letter_spacing_scale: float = 0.01

    allow_catalog_skew: bool = False
    max_nest_depth: int = 2
    default_fps: float = 30.0
    decrypt_timeout_s: float = 60.0
    watcher_poll_ms: int = 500

    def __post_init__(self) -> None:
        if self.drafts_root is None:
            self.drafts_root = detect_drafts_root()
        if self.jianying_root is None:
            self.jianying_root = detect_jianying_root(self.drafts_root)
        if self.install_root is None:
            self.install_root = detect_install_root()
        self.user_state_dir = Path(self.user_state_dir)
        self.user_state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def install_fonts(self) -> Path | None:
        if self.install_root is None:
            return None
        path = self.install_root / "Resources" / "Font"
        return path if path.is_dir() else None

    @property
    def effect_cache(self) -> Path | None:
        if self.jianying_root is None:
            return None
        path = self.jianying_root / "User Data" / "Cache"
        return path if path.is_dir() else None

    @property
    def state_dir(self) -> Path:
        return self.user_state_dir

    @property
    def corpus_index_path(self) -> Path:
        return self.user_state_dir / "corpus_index.json"

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("drafts_root", "jianying_root", "install_root", "user_state_dir"):
            data[key] = str(data[key]) if data[key] else None
        return data


def add_arguments(parser) -> None:
    parser.add_argument("--drafts-root", help="JianYing drafts folder (auto-detected when omitted)")
    parser.add_argument("--jianying-root", help="JianYing data root holding User Data/Cache")
    parser.add_argument("--state-dir", help="Process-level state dir (default: ~/.jypreview)")
    parser.add_argument("--cache", choices=("draft", "user"), help="Where derived caches live (default: draft)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    parser.add_argument("--text-basis", choices=("width", "height", "min_side"))
    parser.add_argument("--text-scale", type=float)
    parser.add_argument("--fit-mode", choices=("contain_unrotated", "contain_rotated"))
    parser.add_argument("--allow-catalog-skew", action="store_true",
                        help="use an effect_catalog built for another JianYing version")


def load(overrides=None) -> Config:
    values: dict = {}
    env_cache = os.environ.get("JY_PREVIEW_CACHE", "").strip().lower()
    if env_cache in ("draft", "user"):
        values["cache_location"] = env_cache
    env_root = os.environ.get("JY_PREVIEW_DRAFTS_ROOT", "").strip()
    if env_root:
        values["drafts_root"] = Path(env_root)
    env_state = os.environ.get("JY_PREVIEW_STATE_DIR", "").strip()
    if env_state:
        values["user_state_dir"] = Path(env_state)

    for name in ("drafts_root", "jianying_root", "state_dir", "port", "host", "cache",
                 "text_basis", "text_scale", "fit_mode", "allow_catalog_skew"):
        value = (overrides or {}).get(name)
        if value is None:
            continue
        if name == "cache":
            values["cache_location"] = value
        elif name == "state_dir":
            values["user_state_dir"] = Path(value)
        elif name == "text_basis":
            values["text_size_basis"] = value
        elif name == "text_scale":
            values["text_scale_factor"] = value
        else:
            values[name] = Path(value) if name.endswith("root") else value

    config = Config(**values)
    if config.drafts_root is None:
        raise SystemExit(json_error("drafts_root_not_found",
                                    "No JianYing drafts folder detected. Pass --drafts-root or set "
                                    "JY_PREVIEW_DRAFTS_ROOT.",
                                    probed=[str(p) for p in _candidate_drafts_roots()[:8]]))
    return config


def json_error(code: str, message: str, **detail) -> int:
    import json

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": False, "code": code, "reason": message, "data": detail}, ensure_ascii=False))
    return 1
