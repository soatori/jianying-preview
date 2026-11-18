"""Puts the script directories on sys.path once for the whole test package."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "scripts" / "jy_crypto"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))