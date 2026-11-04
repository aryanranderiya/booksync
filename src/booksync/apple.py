from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import epub
from .util import normalize

CLOUD_DIR = Path.home() / "Library/Mobile Documents/iCloud~com~apple~iBooks/Documents"
LOCAL_DIR = Path.home() / "Library/Containers/com.apple.BKAgentService/Data/Documents/iBooks/Books"
BOOKS_APP = Path("/System/Applications/Books.app")


@dataclass
class AppleBook:
    title: str
    author: str | None
    path: Path
    keys: frozenset[str]


def library_dir() -> Path | None:
    for candidate in (CLOUD_DIR, LOCAL_DIR):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def cloud_sync_enabled() -> bool:
    try:
        return CLOUD_DIR.exists()
    except OSError:
        return False


def installed() -> bool:
    return BOOKS_APP.exists()


def running() -> bool:
    return subprocess.run(["pgrep", "-x", "Books"], capture_output=True).returncode == 0


def quit_app() -> None:
    subprocess.run(["osascript", "-e", 'tell application "Books" to quit'],
                   capture_output=True)


def keys_for(title: str | None, author: str | None, isbn: str | None) -> frozenset[str]:
    keys = {f"ta:{normalize(title)}|{normalize(author)}"}
    if isbn:
        keys.add(f"isbn:{isbn}")
    return frozenset(keys)


def scan() -> list[AppleBook]:
    """Read the Apple Books library without touching its SQLite store.

    Imported books live in iCloud Drive as unzipped `.epub` packages, or as PDFs.
    Reading their own metadata is enough to dedupe against Play Books.
    """
    root = library_dir()
    if root is None:
        return []
    out: list[AppleBook] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir() and entry.suffix.lower() == ".epub":
                meta = epub.read_epub_package(entry)
            elif entry.is_file() and entry.suffix.lower() in {".pdf", ".epub"}:
                meta = epub.read_meta(entry)
            else:
                continue
        except (epub.InvalidBook, OSError, ValueError):
            continue
        out.append(AppleBook(title=meta.title, author=meta.author, path=entry,
                             keys=keys_for(meta.title, meta.author, meta.isbn)))
    return out


def library_keys() -> set[str]:
    keys: set[str] = set()
    for book in scan():
        keys |= book.keys
    return keys


def is_present(meta: epub.Meta, keys: set[str]) -> bool:
    return not keys.isdisjoint(keys_for(meta.title, meta.author, meta.isbn))


def import_file(path: Path, settle: float = 1.5) -> bool:
    """Hand a file to Books. `open -a` is the only supported programmatic import."""
    result = subprocess.run(["open", "-a", "Books", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    time.sleep(settle)
    return True


def import_files(paths: list[Path]) -> bool:
    """Import a batch in one shot, in the background, without taking focus."""
    if not paths:
        return True
    result = subprocess.run(
        ["open", "-g", "-a", "Books", *[str(p) for p in paths]],
        capture_output=True, text=True,
    )
    return result.returncode == 0
