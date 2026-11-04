from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from . import apple, cover, epub, fetch
from .config import Config, load
from .state import State
from .sync import Outcome, Report, flush_imports, ingest_dir, stage_file
from .util import human_bytes

DIM, BOLD = "\033[2m", "\033[1m"
GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"

def needs_cover(path: Path) -> bool:
    return not cover.usable(epub.cover_bytes(path))


ICONS = {
    "imported": ("+", GREEN),
    "already-in-books": ("=", DIM),
    "duplicate": ("=", DIM),
    "planned": ("·", DIM),
    "staged": ("↓", DIM),
    "unconfirmed": ("?", YELLOW),
    "failed": ("!", RED),
    "skipped": ("-", DIM),
}


def _plain() -> bool:
    return not sys.stdout.isatty()


def s(text: str, code: str) -> str:
    return text if _plain() else f"{code}{text}{RESET}"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def outcome_line(o: Outcome) -> None:
    icon, colour = ICONS.get(o.status, (" ", DIM))
    detail = s(f"   {o.detail}", DIM) if o.detail else ""
    say(f"  {s(icon, colour)} {o.title}{detail}")


# ---------------------------------------------------------------- commands

def cmd_sync(cfg: Config, args) -> int:
    state = State(cfg.db_path)
    run_id = state.start_run()
    report = Report()
    fetched = 0
    note = None

    try:
        keys = apple.library_keys()
        say(s(f"apple books   {len(keys)} keys", DIM))

        with fetch.Session(cfg, headless=not args.visible,
                           browsers=tuple(args.source)) as session:
            say(s(f"session       {session.source}, {session.cookie_count} cookies", DIM))
            items = session.items()
            say(f"library       {len(items)} book(s)")

            known = state.known_volumes()
            skipped = state.skipped_volumes()
            pending = [
                item for item in items
                if item.volume_id not in known
                and (args.retry_skipped or item.volume_id not in skipped)
            ]
            report.skipped_known = len(items) - len(pending)
            if args.only:
                needle = args.only.lower()
                pending = [i for i in pending if needle in i.title.lower()
                           or needle == i.volume_id]
            if args.limit:
                pending = pending[: args.limit]
            say(f"to fetch      {len(pending)}")

            if args.dry_run:
                for item in pending:
                    say(f"  · {item.title or item.volume_id}")
                say(s(f"would fetch {len(pending)} book(s)", DIM))
                return 0

            for index, item in enumerate(pending, 1):
                label = item.title or item.volume_id
                say(s(f"  [{index}/{len(pending)}] {label}", DIM))
                try:
                    path = session.export(item)
                except fetch.FetchError as exc:
                    if exc.kind in {"not-exportable", "drm"}:
                        state.skip_volume(item.volume_id, label, exc.kind)
                        report.add(Outcome(label, "skipped", str(exc)))
                    else:
                        report.add(Outcome(label, "failed", str(exc)))
                    continue
                fetched += 1
                if path.suffix.lower() == ".epub" and needs_cover(path):
                    cover.ensure(path, session.cover(item.volume_id))
                outcome = stage_file(cfg, state, path, source="playbooks",
                                     volume_id=item.volume_id, apple_keys=keys)
                if outcome.status == "failed" and outcome.kind in {"drm", "invalid"}:
                    state.skip_volume(item.volume_id, label, outcome.kind)
                report.add(outcome)

            staged = report.count("staged")
            if staged:
                say(f"importing     {staged} book(s) in {max(1, -(-staged // 10))} batch(es)")
                flush_imports(cfg, state, report)
    except fetch.FetchError as exc:
        say(s(str(exc), RED))
        note = str(exc)
        if exc.kind == "no-session":
            say(s("sign in at play.google.com in Arc or Chrome, then run again", DIM))
    finally:
        state.finish_run(run_id, fetched=fetched, imported=report.imported,
                         skipped=report.skipped_known, failed=report.failed, note=note)
        state.close()

    for outcome in report.outcomes:
        if outcome.status in {"failed", "unconfirmed"}:
            outcome_line(outcome)
    say()
    say(f"{s(str(report.imported), GREEN)} imported · "
        f"{report.count('already-in-books')} already in books · "
        f"{report.count('unconfirmed')} unconfirmed · "
        f"{report.count('skipped')} not exportable · "
        f"{report.skipped_known} unchanged · "
        f"{s(str(report.failed), RED) if report.failed else 0} failed")
    return 1 if report.failed else 0


def cmd_shelf(cfg: Config, args) -> int:
    try:
        with fetch.Session(cfg, headless=not args.visible,
                           browsers=tuple(args.source)) as session:
            say(s(f"session: {session.source} ({session.cookie_count} cookies)", DIM))
            items = session.items()
            state = State(cfg.db_path)
            known = state.known_volumes()
            skipped = state.skipped_volumes()
            state.close()
            for item in items:
                if item.volume_id in known:
                    mark = s("synced", GREEN)
                elif item.volume_id in skipped:
                    mark = s("skip  ", DIM)
                else:
                    mark = s("new   ", YELLOW)
                say(f"  {mark} {item.title or item.volume_id}")
            say(f"\n{len(items)} book(s)")
    except fetch.FetchError as exc:
        say(s(str(exc), RED))
        return 1
    return 0


def cmd_import(cfg: Config, args) -> int:
    target = Path(args.path).expanduser()
    if not target.exists():
        say(s(f"no such path: {target}", RED))
        return 1
    state = State(cfg.db_path)
    try:
        report = ingest_dir(cfg, state, target, dry_run=args.dry_run)
    finally:
        state.close()
    for outcome in report.outcomes:
        outcome_line(outcome)
    say()
    if args.dry_run:
        say(s(f"dry run: {report.count('planned')} would import · "
              f"{report.count('already-in-books')} already present · "
              f"{report.count('duplicate')} duplicate", DIM))
    else:
        say(f"{s(str(report.imported), GREEN)} imported · "
            f"{report.count('already-in-books')} already present · "
            f"{report.count('duplicate')} duplicate · "
            f"{s(str(report.failed), RED) if report.failed else 0} failed")
    return 1 if report.failed else 0


def cmd_session(cfg: Config, args) -> int:
    try:
        info = fetch.verify_session(cfg, browsers=tuple(args.source))
    except fetch.FetchError as exc:
        say(s(str(exc), RED))
        say(s("open play.google.com in Arc or Chrome, sign in, then run this again", DIM))
        return 1
    say(f"  browser   {info['source']}")
    say(f"  cookies   {info['cookies']}")
    say(f"  library   {info['books']} book(s)")
    return 0


def cmd_covers(cfg: Config, args) -> int:
    state = State(cfg.db_path)
    rows = [dict(r) for r in state.conn.execute(
        "SELECT * FROM books WHERE volume_id IS NOT NULL AND archive_path IS NOT NULL")]
    state.close()

    epubs = [(row, Path(row["archive_path"])) for row in rows]
    epubs = [(row, path) for row, path in epubs
             if path.exists() and path.suffix.lower() == ".epub"]

    installed: dict[str, object] = {}
    for book in apple.scan():
        for key in book.keys:
            installed[key] = book

    archive_missing = [(r, p) for r, p in epubs if needs_cover(p)]
    installed_missing = []
    for row, path in epubs:
        try:
            key = epub.read_meta(path).apple_key
        except epub.InvalidBook:
            continue
        book = installed.get(key)
        if book is not None and needs_cover(book.path):
            installed_missing.append((row, path, book))

    if not archive_missing and not installed_missing:
        say("every epub has a usable cover in the archive and in Apple Books")
        return 0

    if archive_missing:
        say(f"{len(archive_missing)} epub(s) with no cover in the archive")
        for row, _ in archive_missing:
            say(f"  · {row['title']}")
    if installed_missing:
        say(f"{len(installed_missing)} epub(s) showing no cover in Apple Books")
        for row, _, _ in installed_missing:
            say(f"  · {row['title']}")

    if not args.reimport:
        say(s("run with --reimport to fix them", DIM))
        return 0

    fixed: dict[Path, str] = {p: r["title"] for r, p, _ in installed_missing}
    if archive_missing:
        with fetch.Session(cfg, headless=not args.visible,
                           browsers=tuple(args.source)) as session:
            for row, path in archive_missing:
                if cover.ensure(path, session.cover(row["volume_id"])):
                    fixed[path] = row["title"]
                    say(f"  + cover {row['title']}")
                else:
                    say(f"  ! {row['title']}   no cover available")
    if not fixed:
        return 1

    for path in fixed:
        try:
            key = epub.read_meta(path).apple_key
        except epub.InvalidBook:
            continue
        book = installed.get(key)
        if book is not None:
            shutil.rmtree(book.path, ignore_errors=True)
    time.sleep(2)

    apple.import_files(list(fixed))
    deadline = time.time() + 45
    done = 0
    while time.time() < deadline:
        installed = {}
        for book in apple.scan():
            for key in book.keys:
                installed[key] = book
        done = 0
        for path in fixed:
            try:
                book = installed.get(epub.read_meta(path).apple_key)
            except epub.InvalidBook:
                continue
            if book is not None and not needs_cover(book.path):
                done += 1
        if done == len(fixed):
            break
        time.sleep(2)
    say(f"{done}/{len(fixed)} re-imported with a cover")
    return 0 if done == len(fixed) else 1


def cmd_status(cfg: Config, args) -> int:
    state = State(cfg.db_path)
    summary = state.summary()
    state.close()
    last = summary["last_run"]
    if getattr(args, "oneline", False):
        when = last["finished_at"][:16].replace("T", " ") if last else "never run"
        say(f"{summary['imported']} synced · last run {when}")
        return 0
    books = apple.scan()
    say(s("booksync", BOLD))
    say(f"  archive      {cfg.archive_dir}")
    say(f"  tracked      {summary['total']} book(s), {summary['imported']} imported")
    say(f"  apple books  {len(books)} visible in {apple.library_dir()}")
    if summary["failed"]:
        say(s(f"  failures     {summary['failed']}", YELLOW))
    last = summary["last_run"]
    if last is not None:
        say(f"  last run     {last['finished_at'] or 'incomplete'} "
            f"({last['imported']} imported, {last['failed']} failed)")
    else:
        say("  last run     never")
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    checks = [
        ("chrome", fetch.CHROME.exists(), str(fetch.CHROME)),
        ("books app", apple.installed(), "/System/Applications/Books.app"),
    ]
    cloud = apple.cloud_sync_enabled()
    checks.append(("icloud books", cloud,
                   "on, imports reach iPhone and iPad" if cloud
                   else "off, enable iCloud Drive > Books or imports stay local"))
    books = apple.scan()
    checks.append(("books library", True, f"{len(books)} book(s) readable"))
    checks.append(("archive", cfg.archive_dir.exists(), str(cfg.archive_dir)))
    _, _, free = shutil.disk_usage(cfg.archive_dir)
    checks.append(("disk space", free > 2 * 1024**3, f"{human_bytes(free)} free"))

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        say(f"  {s('ok', GREEN) if ok else s('!!', YELLOW)}  {name.ljust(width)}  {s(detail, DIM)}")
    return 0 if all(ok for _, ok, _ in checks) else 1


# ---------------------------------------------------------------- entrypoint

def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="booksync",
        description="Move your Google Play Books uploads into Apple Books.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def net_args(p):
        p.add_argument("--from", dest="source", nargs="+", default=["arc", "chrome"],
                       choices=["arc", "chrome"], help="browser to borrow the session from")
        p.add_argument("--visible", action="store_true", help="show the browser window")

    sync = sub.add_parser("sync", help="fetch new uploads and import them")
    sync.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    sync.add_argument("--limit", type=int, help="fetch at most N books")
    sync.add_argument("--only", help="only books whose title contains this text")
    sync.add_argument("--retry-skipped", action="store_true",
                      help="try books that were not exportable last time")
    net_args(sync)
    sync.set_defaults(func=cmd_sync)

    shelf = sub.add_parser("shelf", help="list your Play Books library and what is synced")
    net_args(shelf)
    shelf.set_defaults(func=cmd_shelf)

    imp = sub.add_parser("import", help="import a file or folder from disk")
    imp.add_argument("path")
    imp.add_argument("--dry-run", action="store_true")
    imp.set_defaults(func=cmd_import)

    session = sub.add_parser("session", help="check that your browser session works")
    net_args(session)
    session.set_defaults(func=cmd_session)

    status = sub.add_parser("status", help="counts and last run")
    status.add_argument("--oneline", action="store_true")
    status.set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="check this machine is set up").set_defaults(func=cmd_doctor)

    covers = sub.add_parser("covers", help="find and fix EPUBs with no cover")
    covers.add_argument("--reimport", action="store_true",
                        help="fetch the missing covers and re-import those books")
    net_args(covers)
    covers.set_defaults(func=cmd_covers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(load(), args)


if __name__ == "__main__":
    raise SystemExit(main())
