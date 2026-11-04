from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .util import as_isbn, normalize

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class InvalidBook(Exception):
    pass


class DrmProtected(InvalidBook):
    pass


@dataclass
class Meta:
    title: str
    author: str | None
    identifier: str | None
    fmt: str
    isbn: str | None = None

    @property
    def display(self) -> str:
        return f"{self.title} — {self.author}" if self.author else self.title

    @property
    def apple_key(self) -> str:
        if self.isbn:
            return f"isbn:{self.isbn}"
        return f"ta:{normalize(self.title)}|{normalize(self.author)}"


def _parse_opf(data: bytes) -> Meta:
    root = ET.fromstring(data)
    metadata = root.find("opf:metadata", NS)
    if metadata is None:
        raise InvalidBook("OPF has no metadata element")

    def first(tag: str) -> str | None:
        node = metadata.find(f"dc:{tag}", NS)
        if node is None or not node.text:
            return None
        return node.text.strip() or None

    title = first("title")
    if not title:
        raise InvalidBook("OPF has no dc:title")

    creators = [c.text.strip() for c in metadata.findall("dc:creator", NS) if c.text and c.text.strip()]
    identifier = first("identifier")
    return Meta(
        title=title,
        author=", ".join(creators) or None,
        identifier=identifier,
        fmt="epub",
        isbn=as_isbn(identifier),
    )


def _opf_path_from_zip(zf: zipfile.ZipFile) -> str:
    try:
        container = zf.read("META-INF/container.xml")
    except KeyError as exc:
        raise InvalidBook("not an EPUB: missing META-INF/container.xml") from exc
    root = ET.fromstring(container)
    node = root.find(".//c:rootfile", NS)
    if node is None or not node.get("full-path"):
        raise InvalidBook("not an EPUB: container.xml names no rootfile")
    return node.get("full-path", "")


def read_epub(path: Path) -> Meta:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "META-INF/encryption.xml" in names:
            raise DrmProtected("EPUB is DRM encrypted")
        opf = _opf_path_from_zip(zf)
        return _parse_opf(zf.read(opf))


def read_epub_package(path: Path) -> Meta:
    """Apple Books keeps imported EPUBs as unzipped .epub package directories."""
    opfs = list(path.glob("**/*.opf"))
    if not opfs:
        raise InvalidBook(f"no OPF inside package {path.name}")
    return _parse_opf(opfs[0].read_bytes())


def read_pdf(path: Path) -> Meta:
    title = author = None
    try:
        head = path.open("rb").read()
        if b"/Encrypt" in head[:4096] or b"/Encrypt" in head[-4096:]:
            raise DrmProtected("PDF is encrypted")
        match = re.search(rb"/Title\s*\((.*?)\)", head, re.S)
        if match:
            title = _pdf_text(match.group(1))
        match = re.search(rb"/Author\s*\((.*?)\)", head, re.S)
        if match:
            author = _pdf_text(match.group(1))
    except DrmProtected:
        raise
    except OSError:
        pass
    return Meta(
        title=title or path.stem,
        author=author,
        identifier=None,
        fmt="pdf",
    )


def _pdf_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", "replace")
    text = text.replace("\\(", "(").replace("\\)", ")").strip()
    return text or None


def read_meta(path: Path) -> Meta:
    if path.is_dir():
        if path.suffix.lower() != ".epub":
            raise InvalidBook(f"unsupported package {path.name}")
        return read_epub_package(path)
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return read_epub(path)
    if suffix == ".pdf":
        return read_pdf(path)
    raise InvalidBook(f"unsupported format {suffix or '(none)'}")


def validate(path: Path) -> Meta:
    if path.stat().st_size == 0:
        raise InvalidBook(f"{path.name} is empty")
    meta = read_meta(path)
    if meta.fmt == "epub" and not path.is_dir():
        with zipfile.ZipFile(path) as zf:
            if "mimetype" not in zf.namelist():
                raise InvalidBook(f"{path.name} is not a valid EPUB (no mimetype entry)")
    return meta


COVER_ID = "booksync-cover"
COVER_FILE = "booksync-cover.jpg"
_META_COVER = re.compile(rb"<meta\s+[^>]*name=[\"']cover[\"'][^>]*/?>", re.I)


def cover_bytes(path: Path) -> bytes | None:
    """The image the EPUB declares as its cover, if it resolves."""
    if path.is_dir():
        opfs = list(path.glob("**/*.opf"))
        if not opfs:
            return None
        opf_path = opfs[0]
        try:
            root = ET.fromstring(opf_path.read_bytes())
        except (ET.ParseError, OSError):
            return None
        href = _cover_href(root)
        if not href:
            return None
        target = opf_path.parent / href
        return target.read_bytes() if target.exists() else None

    try:
        with zipfile.ZipFile(path) as zf:
            opf_path = _opf_path_from_zip(zf)
            root = ET.fromstring(zf.read(opf_path))
            href = _cover_href(root)
            if not href:
                return None
            base = str(PurePosixPath(opf_path).parent)
            candidate = f"{base}/{href}" if base not in ("", ".") else href
            for name in (candidate, href):
                if name in zf.namelist():
                    return zf.read(name)
    except (zipfile.BadZipFile, ET.ParseError, InvalidBook, KeyError):
        return None
    return None


def _cover_href(root: ET.Element) -> str | None:
    manifest = root.find("opf:manifest", NS)
    if manifest is None:
        return None
    items = {item.get("id"): item for item in manifest.findall("opf:item", NS)}
    for item in items.values():
        if "cover-image" in (item.get("properties") or "") and item.get("href"):
            return item.get("href")
    metadata = root.find("opf:metadata", NS)
    if metadata is not None:
        for meta in metadata.findall("opf:meta", NS):
            if (meta.get("name") or "").lower() == "cover":
                item = items.get(meta.get("content") or "")
                if item is not None and item.get("href"):
                    return item.get("href")
    return None



def has_duplicate_cover(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(COVER_FILE)]
    except (zipfile.BadZipFile, OSError):
        return False
    return len(names) != len(set(names))


def inject_cover(path: Path, image: bytes) -> bool:
    """Add a cover image and declare it in the OPF. Keeps the archive otherwise intact."""
    try:
        with zipfile.ZipFile(path) as zf:
            opf_path = _opf_path_from_zip(zf)
            opf = zf.read(opf_path)
            entries = [(info, zf.read(info.filename)) for info in zf.infolist()]
    except (zipfile.BadZipFile, ET.ParseError, InvalidBook, KeyError):
        return False

    opf_dir = str(PurePosixPath(opf_path).parent)
    href = COVER_FILE
    cover_path = f"{opf_dir}/{href}" if opf_dir not in ("", ".") else href

    item = (f'<item id="{COVER_ID}" href="{href}" '
            f'media-type="image/jpeg" properties="cover-image"/>').encode()
    if b"</manifest>" not in opf:
        return False
    opf = opf.replace(b"</manifest>", item + b"</manifest>", 1)
    opf = _META_COVER.sub(b"", opf)
    meta = f'<meta name="cover" content="{COVER_ID}"/>'.encode()
    if b"</metadata>" in opf:
        opf = opf.replace(b"</metadata>", meta + b"</metadata>", 1)

    tmp = path.with_suffix(".epub.tmp")
    try:
        with zipfile.ZipFile(tmp, "w") as zout:
            zout.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
            for info, data in entries:
                if info.filename in ("mimetype", cover_path):
                    continue
                payload = opf if info.filename == opf_path else data
                zout.writestr(info, payload, compress_type=info.compress_type)
            zout.writestr(cover_path, image, compress_type=zipfile.ZIP_DEFLATED)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True
