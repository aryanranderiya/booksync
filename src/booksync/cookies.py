"""Reuse the Google session already open in Arc or Chrome.

Chromium encrypts cookie values with a key derived from a password held in the
login keychain. Reading it triggers one macOS permission prompt per browser,
which the user can make permanent with "Always Allow".
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

BROWSERS = {
    "arc": ("Arc", "~/Library/Application Support/Arc/User Data"),
    "chrome": ("Chrome", "~/Library/Application Support/Google/Chrome"),
}

GOOGLE_HOST = "google."


class CookieError(Exception):
    pass


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str
    secure: bool
    http_only: bool
    expires: float
    same_site: str | None


def _secret(service: str) -> str:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise CookieError(f"keychain prompt for {service} timed out") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise CookieError(f"no keychain entry named {service}")
    return result.stdout.strip()


def _derive(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", secret.encode(), b"saltysalt", 1003, 16)


def _decrypt(blob: bytes, key: bytes, host: str, version: int) -> str:
    if not blob:
        return ""
    if blob[:3] not in (b"v10", b"v11"):
        return blob.decode("utf-8", "replace")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = decryptor.update(blob[3:]) + decryptor.finalize()
    pad = plain[-1] if plain else 0
    if 0 < pad <= 16:
        plain = plain[:-pad]
    if version >= 24 and len(plain) > 32:
        digest, value = plain[:32], plain[32:]
        if digest != hashlib.sha256(host.encode()).digest():
            raise CookieError(f"cookie host hash mismatch for {host}")
        return value.decode("utf-8", "replace")
    return plain.decode("utf-8", "replace")


def _profile_dirs(base: Path) -> list[Path]:
    if not base.exists():
        return []
    dirs = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child.name == "Default" or child.name.startswith("Profile")):
            if (child / "Cookies").exists():
                dirs.append(child)
    return dirs


def _load_profile(profile: Path, key: bytes) -> tuple[int, list[Cookie]]:
    tmp = Path(tempfile.mkdtemp(prefix="booksync-cookies-"))
    try:
        db = tmp / "Cookies"
        shutil.copy2(profile / "Cookies", db)
        for suffix in ("-wal", "-shm"):
            extra = profile / f"Cookies{suffix}"
            if extra.exists():
                shutil.copy2(extra, tmp / f"Cookies{suffix}")
        conn = sqlite3.connect(db)
        try:
            version = int(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        except Exception:
            version = 0
        rows = conn.execute(
            "SELECT host_key, name, value, encrypted_value, path, is_secure, is_httponly,"
            " expires_utc, samesite FROM cookies"
        ).fetchall()
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    cookies: list[Cookie] = []
    for host, name, value, encrypted, path, secure, http_only, expires_utc, same_site in rows:
        if GOOGLE_HOST not in host and not host.endswith("google.com"):
            continue
        try:
            plain = _decrypt(encrypted, key, host, version) if encrypted else value
        except CookieError:
            continue
        if not plain:
            continue
        cookies.append(Cookie(
            name=name, value=plain, domain=host, path=path or "/",
            secure=bool(secure), http_only=bool(http_only),
            expires=(expires_utc / 1_000_000 - 11_644_473_600) if expires_utc else -1,
            same_site={0: "None", 1: "Lax", 2: "Strict", -1: None}.get(same_site or -1),
        ))
    return version, cookies


def load(browsers: tuple[str, ...] = ("arc", "chrome")) -> tuple[str, list[Cookie]]:
    """Return the browser name and its Google cookies, preferring the richest profile."""
    errors: list[str] = []
    for name in browsers:
        label, relative = BROWSERS[name]
        base = Path(relative).expanduser()
        profiles = _profile_dirs(base)
        if not profiles:
            errors.append(f"{label}: no profile found in {base}")
            continue
        try:
            key = _derive(_secret(f"{label} Safe Storage"))
        except CookieError as exc:
            errors.append(str(exc))
            continue

        best: list[Cookie] = []
        for profile in profiles:
            try:
                _, cookies = _load_profile(profile, key)
            except Exception as exc:
                errors.append(f"{profile.name}: {exc}")
                continue
            if len(cookies) > len(best):
                best = cookies
        if best:
            return name, best
        errors.append(f"{label}: profiles have no Google cookies")

    raise CookieError("no usable browser session. " + "; ".join(errors))


def to_playwright(cookies: list[Cookie]) -> list[dict]:
    out = []
    for c in cookies:
        item = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "secure": c.secure,
            "httpOnly": c.http_only,
            "expires": c.expires,
        }
        if c.same_site and not (c.same_site == "None" and not c.secure):
            item["sameSite"] = c.same_site
        out.append(item)
    return out
