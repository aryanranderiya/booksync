from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import apple, epub
from .config import Config
from .state import Record, State, now
from .util import human_bytes, sanitize, sha256_file, unique_path

BATCH = 10


class Outcome:
    __slots__ = ("title", "status", "detail", "path", "kind")

    def __init__(self, title: str, status: str, detail: str = "", path=None, kind: str = ""):
        self.title = title
        self.status = status
        self.detail = detail
        self.path = path
        self.kind = kind

    def __repr__(self) -> str:
        return f"<Outcome {self.status} {self.title!r}>"


class Report:
    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []
        self.skipped_known = 0

    def add(self, outcome: Outcome) -> None:
        self.outcomes.append(outcome)

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def imported(self) -> int:
        return self.count("imported")

    @property
    def failed(self) -> int:
        return self.count("failed")


def stage_file(cfg: Config, state: State, path: Path, *, source: str,
               volume_id: str | None, apple_keys: set[str],
               dry_run: bool = False) -> Outcome:
    """Validate, archive and record a file. Does not talk to Books."""
    try:
        meta = epub.validate(path)
    except epub.DrmProtected as exc:
        path.unlink(missing_ok=True)
        return Outcome(title=path.stem, status="failed", detail=f"DRM protected: {exc}",
                       kind="drm")
    except epub.InvalidBook as exc:
        path.unlink(missing_ok=True)
        return Outcome(title=path.stem, status="failed", detail=str(exc), kind="invalid")

    sha = sha256_file(path)
    existing = state.known_sha(sha)
    if existing is not None and (existing["imported_at"] or existing["status"] == "stored"):
        return Outcome(title=meta.display, status="duplicate", detail="already synced")

    if dry_run:
        present = apple.is_present(meta, apple_keys)
        return Outcome(
            title=meta.display,
            status="already-in-books" if present else "planned",
            detail=f"{human_bytes(path.stat().st_size)} · {meta.fmt}",
        )

    stem = sanitize(f"{meta.author} - {meta.title}" if meta.author else meta.title)
    suffix = ".epub" if meta.fmt == "epub" else ".pdf"
    dest = unique_path(cfg.archive_dir, stem, suffix)
    try:
        if path.resolve() != dest.resolve():
            shutil.move(str(path), str(dest))
    except OSError as exc:
        return Outcome(title=meta.display, status="failed", detail=f"could not archive: {exc}")

    state.add(Record(
        sha256=sha, volume_id=volume_id, title=meta.title, author=meta.author,
        fmt=meta.fmt, bytes=dest.stat().st_size, archive_path=str(dest),
        apple_key=meta.apple_key, source=source, status="stored", downloaded_at=now(),
    ))

    if apple.is_present(meta, apple_keys):
        state.mark_imported(sha)
        return Outcome(title=meta.display, status="already-in-books",
                       detail="already in Apple Books", path=dest)

    return Outcome(title=meta.display, status="staged", detail=human_bytes(dest.stat().st_size),
                   path=dest)


def pending_imports(state: State) -> list:
    return state.conn.execute(
        "SELECT sha256, title, author, archive_path, apple_key FROM books "
        "WHERE imported_at IS NULL AND status = 'stored' ORDER BY rowid"
    ).fetchall()


def flush_imports(cfg: Config, state: State, report: Report | None = None) -> Report:
    """Hand every staged book to Books in batches, without stealing focus."""
    report = report or Report()
    rows = pending_imports(state)
    if not rows:
        return report

    paths = [Path(r["archive_path"]) for r in rows if Path(r["archive_path"]).exists()]
    if not paths:
        return report

    for start in range(0, len(paths), BATCH):
        chunk = paths[start:start + BATCH]
        apple.import_files(chunk)
        time.sleep(cfg.settle)

    keys = apple.library_keys()
    deadline = time.time() + 60
    while time.time() < deadline:
        if all(r["apple_key"] in keys for r in rows):
            break
        time.sleep(2)
        keys = apple.library_keys()

    for row in rows:
        title = f"{row['title']} — {row['author']}" if row["author"] else row["title"]
        key = row["apple_key"]
        if key and key in keys:
            state.mark_imported(row["sha256"])
            report.add(Outcome(title, "imported"))
        else:
            report.add(Outcome(title, "unconfirmed",
                               "handed to Books, not visible yet, will retry"))
    report.outcomes = [o for o in report.outcomes if o.status != "staged"]
    return report


def ingest_dir(cfg: Config, state: State, target: Path, *, dry_run: bool,
               apple_keys: set[str] | None = None) -> Report:
    report = Report()
    keys = apple_keys if apple_keys is not None else apple.library_keys()
    if target.is_file():
        files = [target]
    else:
        files = sorted(
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in {".epub", ".pdf"} and not p.name.startswith(".")
        )
    for path in files:
        report.add(stage_file(cfg, state, path, source="folder", volume_id=None,
                              apple_keys=keys, dry_run=dry_run))
    if not dry_run:
        flush_imports(cfg, state, report)
    return report
