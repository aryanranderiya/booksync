from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import cookies as cookiejar
from .config import Config
from .util import sanitize

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SHELF_URL = "https://play.google.com/books?source=uploads"
TILE = "[id^='title-']"
CARD = "gpb-volume-card"
MENU_ITEM = ".cdk-overlay-container button.mat-mdc-menu-item"
DIALOG_BUTTON = ".cdk-overlay-container button"
EXPORT_RE = re.compile(r"export\s+as\s+(epub|pdf)", re.I)


class FetchError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


@dataclass
class ShelfItem:
    volume_id: str
    title: str


@dataclass
class Fetched:
    path: Path
    volume_id: str


class Session:
    """Drives Play Books in Chrome using the Google session already on this Mac."""

    def __init__(self, cfg: Config, *, headless: bool = True,
                 browsers: tuple[str, ...] = ("arc", "chrome")):
        self.cfg = cfg
        self.headless = headless
        self.browsers = browsers
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.source = None
        self.cookie_count = 0

    def __enter__(self) -> "Session":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        from playwright.sync_api import sync_playwright

        try:
            self.source, jar = cookiejar.load(self.browsers)
        except cookiejar.CookieError as exc:
            raise FetchError(str(exc), "no-session") from exc
        self.cookie_count = len(jar)

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            channel="chrome",
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            locale="en-US", viewport={"width": 1400, "height": 950}, accept_downloads=True
        )
        try:
            self._context.add_cookies(cookiejar.to_playwright(jar))
        except Exception as exc:
            raise FetchError(f"could not install cookies: {exc}", "no-session") from exc

        self.page = self._context.new_page()
        self._downloads: list = []
        self._content_urls: list[str] = []
        self._context.on("download", lambda d: self._downloads.append(d))
        self.page.on("request", self._on_request)
        self.page.goto(SHELF_URL, wait_until="domcontentloaded", timeout=60_000)
        if "accounts.google.com" in self.page.url:
            raise FetchError(
                f"{self.source} is not signed in to Google, or the session expired", "no-session"
            )
        try:
            self.page.wait_for_selector(TILE, state="attached", timeout=30_000)
        except Exception as exc:
            if self.page.get_by_text("Upload files").count():
                return
            raise FetchError("Play Books library did not render", "no-session") from exc
        self._load_all()

    def close(self) -> None:
        for closer in (self._browser, self._pw):
            try:
                if closer is not None:
                    closer.close() if closer is self._browser else closer.stop()
            except Exception:
                pass

    def _load_all(self, rounds: int = 12) -> None:
        previous = 0
        for _ in range(rounds):
            count = self.page.locator(TILE).count()
            if count == previous:
                break
            previous = count
            self.page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.8)
        self.page.evaluate("() => window.scrollTo(0, 0)")

    def items(self) -> list[ShelfItem]:
        raw = self.page.evaluate(
            f"""() => [...document.querySelectorAll("{TILE}")].map(e => ({{
                    id: e.id.replace('title-', ''),
                    text: (e.textContent || '').trim()
            }}))"""
        )
        seen: dict[str, ShelfItem] = {}
        for entry in raw:
            title = re.sub(r"^for\s+", "", entry["text"]).strip()
            if entry["id"] and entry["id"] not in seen:
                seen[entry["id"]] = ShelfItem(volume_id=entry["id"], title=title)
        return list(seen.values())

    def _on_request(self, request) -> None:
        url = request.url
        if "books.googleusercontent.com/books/content" in url:
            self._content_urls.append(url)

    def _on_shelf(self) -> bool:
        return self.page.url.startswith("https://play.google.com/books") and "reader" not in self.page.url

    def _reload_shelf(self) -> None:
        self.page.goto(SHELF_URL, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_selector(TILE, state="attached", timeout=30_000)
        self._load_all()

    def _await_download(self, timeout: float):
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            if self._downloads:
                return self._downloads[0]
            url = self.page.url
            if "googleusercontent.com" in url or url.startswith("chrome-error://"):
                raise FetchError("Google refused the file for this book", "not-exportable")
            self.page.wait_for_timeout(250)
        raise FetchError("no file arrived", "not-exportable")

    def export(self, item: ShelfItem, timeout: float = 90_000) -> Path:
        page = self.page
        if not self._on_shelf():
            self._reload_shelf()

        card = page.locator(f"{CARD}:has([id='title-{item.volume_id}'])").first
        if card.count() == 0:
            raise FetchError("not on the shelf any more")

        card.scroll_into_view_if_needed(timeout=10_000)
        card.hover()
        card.get_by_role("button", name="More Options").click(timeout=15_000)

        menu = page.locator(MENU_ITEM)
        try:
            menu.first.wait_for(timeout=10_000)
        except Exception as exc:
            raise FetchError("book menu did not open") from exc

        export_item = menu.filter(has_text=re.compile(r"^\s*export\s*$", re.I)).first
        if export_item.count() == 0:
            page.keyboard.press("Escape")
            raise FetchError("no export option for this book", "not-exportable")
        export_item.click()

        choice = page.locator(DIALOG_BUTTON).filter(has_text=EXPORT_RE).first
        try:
            choice.wait_for(timeout=15_000)
        except Exception as exc:
            page.keyboard.press("Escape")
            raise FetchError("export dialog did not offer a download") from exc

        label = (choice.inner_text() or "").strip()
        self._downloads.clear()
        self._content_urls.clear()
        choice.click()
        try:
            download = self._await_download(timeout)
        except FetchError:
            if not self._content_urls:
                raise
            return self._save_direct(item, label)

        suggested = download.suggested_filename or f"{item.volume_id}.bin"
        if suggested.lower().endswith(".acsm"):
            raise FetchError("Adobe DRM file, Apple Books cannot open it", "drm")

        suffix = Path(suggested).suffix.lower()
        if suffix not in {".epub", ".pdf"}:
            suffix = ".epub" if "epub" in label.lower() else ".pdf"
        stem = sanitize(Path(suggested).stem, item.volume_id)
        target = self._target(stem, suffix, item.volume_id)
        download.save_as(str(target))
        return target

    def _save_direct(self, item: ShelfItem, label: str) -> Path:
        """Fallback for responses Chrome rejects but the HTTP client accepts.

        Google sometimes sends duplicated Content-Disposition headers, which Chrome
        refuses to render. The body is still a perfectly good EPUB or PDF.
        """
        url = self._content_urls[-1]
        response = self._context.request.get(url, timeout=180_000)
        if response.status != 200:
            raise FetchError(f"export returned HTTP {response.status}", "not-exportable")
        body = response.body()
        if not body:
            raise FetchError("export returned an empty file", "not-exportable")
        if body[:4] == b"%PDF":
            suffix = ".pdf"
        elif body[:2] == b"PK":
            suffix = ".epub"
        elif "epub" in label.lower():
            suffix = ".epub"
        elif "pdf" in label.lower():
            suffix = ".pdf"
        else:
            raise FetchError("export returned an unknown file type", "not-exportable")
        target = self._target(sanitize(item.title, item.volume_id), suffix, item.volume_id)
        target.write_bytes(body)
        return target

    def cover(self, volume_id: str) -> bytes | None:
        """The same cover Play Books shows, at usable resolution."""
        url = (f"https://books.google.com/books/content?id={volume_id}"
               "&printsec=frontcover&img=1&zoom=1&w=1200")
        try:
            response = self._context.request.get(url, timeout=45_000)
        except Exception:
            return None
        if response.status != 200:
            return None
        body = response.body()
        if len(body) < 1500 or not response.headers.get("content-type", "").startswith("image/"):
            return None
        return body

    def _target(self, stem: str, suffix: str, volume_id: str) -> Path:
        target = self.cfg.inbox_dir / f"{stem}{suffix}"
        if target.exists():
            target = target.with_name(f"{stem}-{volume_id}{suffix}")
        return target


def verify_session(cfg: Config, browsers: tuple[str, ...] = ("arc", "chrome")) -> dict:
    with Session(cfg, browsers=browsers) as session:
        return {
            "source": session.source,
            "cookies": session.cookie_count,
            "books": len(session.items()),
        }
