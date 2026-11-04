import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import make_test_epub  # noqa: E402
from booksync import epub  # noqa: E402
from booksync.state import Record, State  # noqa: E402
from booksync.util import as_isbn, normalize, sanitize  # noqa: E402


@pytest.fixture
def sample(tmp_path):
    return make_test_epub.build(tmp_path / "book.epub")


def test_reads_title_author_isbn(sample):
    meta = epub.read_epub(sample)
    assert meta.title == "A Test Book"
    assert meta.author == "Test Author"
    assert meta.isbn == "9780000000001"
    assert meta.apple_key == "isbn:9780000000001"


def test_validate_rejects_non_epub(tmp_path):
    junk = tmp_path / "junk.epub"
    junk.write_bytes(b"not a zip")
    import zipfile
    with pytest.raises((epub.InvalidBook, zipfile.BadZipFile)):
        epub.validate(junk)


def test_validate_rejects_empty(tmp_path):
    empty = tmp_path / "empty.epub"
    empty.write_bytes(b"")
    with pytest.raises(epub.InvalidBook):
        epub.validate(empty)


def test_drm_detected(tmp_path):
    import zipfile
    path = tmp_path / "drm.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", make_test_epub.CONTAINER)
        zf.writestr("META-INF/encryption.xml", "<encryption/>")
        zf.writestr("OEBPS/content.opf", make_test_epub.OPF.format(
            title="T", author="A", identifier="1"))
    with pytest.raises(epub.DrmProtected):
        epub.read_epub(path)


def test_package_dir_roundtrip(tmp_path, sample):
    import zipfile
    target = tmp_path / "pkg.epub"
    target.mkdir()
    with zipfile.ZipFile(sample) as zf:
        zf.extractall(target)
    meta = epub.read_epub_package(target)
    assert meta.title == "A Test Book"


def test_key_falls_back_to_title_author(tmp_path):
    path = make_test_epub.build(tmp_path / "noisbn.epub", identifier="urn:uuid:abc")
    meta = epub.read_epub(path)
    assert meta.isbn is None
    assert meta.apple_key == "ta:a test book|test author"


def test_state_roundtrip(tmp_path):
    state = State(tmp_path / "state.db")
    rec = Record(sha256="abc", title="T", author="A", fmt="epub", bytes=1,
                 archive_path="/x", apple_key="isbn:1", source="test", status="stored")
    state.add(rec)
    assert state.known_sha("abc")["title"] == "T"
    state.mark_imported("abc")
    assert "isbn:1" in state.imported_keys()
    state.add(rec)  # idempotent on sha256
    assert state.summary()["total"] == 1
    state.close()


def test_util_helpers():
    assert sanitize('a/b:c*"d"') == "a b c d"
    assert normalize("The Cold Start Problem") == "the cold start problem"
    assert as_isbn("urn:isbn:978-0-06-296975-0") == "9780062969750"
    assert as_isbn("urn:uuid:1234") is None


def test_generated_cover_is_usable():
    from booksync import cover
    data = cover.make("A Test Book", "Test Author")
    assert cover.usable(data)


def test_placeholder_cover_is_rejected():
    from booksync import cover
    from PIL import Image
    import io
    grey = Image.new("RGB", (128, 184), (152, 160, 167))
    buffer = io.BytesIO()
    grey.save(buffer, "JPEG")
    assert not cover.usable(buffer.getvalue())


def test_inject_cover_roundtrip(tmp_path, sample):
    from booksync import cover
    data = cover.make("A Test Book", "Test Author")
    assert epub.inject_cover(sample, data)
    assert cover.usable(epub.cover_bytes(sample))
    assert not epub.has_duplicate_cover(sample)
    assert epub.read_epub(sample).title == "A Test Book"
