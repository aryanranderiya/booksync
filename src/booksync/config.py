from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _home() -> Path:
    return Path.home()


@dataclass
class Config:
    app_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("BOOKSYNC_HOME", _home() / "Library" / "Application Support" / "booksync")))
    archive_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("BOOKSYNC_ARCHIVE", _home() / "Books" / "PlayBooks")))
    settle: float = 1.5
    chrome_channel: str = "chrome"

    @property
    def db_path(self) -> Path:
        return self.app_dir / "state.db"

    @property
    def inbox_dir(self) -> Path:
        return self.app_dir / "inbox"

    @property
    def profile_dir(self) -> Path:
        return self.app_dir / "chrome-profile"

    @property
    def log_dir(self) -> Path:
        return self.app_dir / "logs"

    @property
    def debug_dir(self) -> Path:
        return self.app_dir / "debug"

    def ensure(self) -> None:
        for d in (self.app_dir, self.archive_dir, self.inbox_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


def load() -> Config:
    cfg = Config()
    cfg.ensure()
    return cfg
