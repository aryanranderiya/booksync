from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_UNSAFE = re.compile(r'[/\\\x00-\x1f<>:"|?*]+')


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def sanitize(name: str, fallback: str = "untitled", limit: int = 120) -> str:
    name = _UNSAFE.sub(" ", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    return name[:limit].strip() or fallback


def normalize(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def as_isbn(identifier: str | None) -> str | None:
    if not identifier:
        return None
    digits = re.sub(r"[^0-9Xx]", "", identifier).upper()
    if len(digits) == 10 or len(digits) == 13:
        return digits
    return None


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){suffix}"
        n += 1
    return candidate
