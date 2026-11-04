# booksync

Moves the books you uploaded to Google Play Books into Apple Books on your Mac.

Google Play Books has no API and neither does Apple Books, so this drives the real
Play Books web page with the Google session already signed in on this machine (Arc,
falling back to Chrome), downloads each upload, and hands the files to Books.

## Requirements

- macOS with Google Chrome installed
- A signed-in session at `play.google.com` in Arc or Chrome
- `uv` (`brew install uv`)

## Install

```sh
uv sync
```

The first run asks for keychain access to "Arc Safe Storage". Click **Always Allow**.
That key decrypts your own cookies locally; nothing leaves the machine except requests
to Google.

## Commands

```sh
booksync sync                 # fetch new uploads and import them
booksync sync --dry-run       # list what would be fetched
booksync sync --only "mom test"
booksync sync --limit 5
booksync shelf                # every book in Play Books and whether it is synced
booksync status               # counts and last run
booksync covers               # EPUBs missing a cover
booksync covers --reimport    # fix covers and replace those books in Books
booksync import <file|folder> # import local EPUB/PDF files
booksync adopt                # mark books already in Books as synced
booksync session              # check the browser session still works
booksync doctor               # check this machine is set up
```

`bin/booksync` is a wrapper, so it works without activating the virtualenv.

## How syncing works

`booksync sync` is idempotent and safe to run whenever.

1. Reads your Google cookies from Arc (or Chrome) and decrypts them locally.
2. Opens `play.google.com/books` in headless Chrome with that session.
3. Skips every book already recorded in the state database.
4. For each new book: opens the tile menu, clicks Export, picks EPUB or PDF, saves it.
5. Validates the file and drops DRM-protected store purchases.
6. Gives every EPUB a real cover if Google only has a placeholder.
7. Archives to `~/Books/PlayBooks/` and imports to Books in one batch.

Identity is the file hash, not the title, so re-downloading the same book never
creates a duplicate. Books already present in Apple Books are matched by ISBN, then by
title and author, so nothing is imported twice.

Books that cannot be exported (store purchases, DRM) are recorded once and skipped on
later runs. `--retry-skipped` tries them again.

## Where things live

```
~/Library/Application Support/booksync/state.db   what has been synced
~/Books/PlayBooks/                                canonical archive
~/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents   Apple Books copies
```

The archive is the source of truth. Apple Books is a copy, so if its library ever goes
wrong, point `booksync import` at the archive.

## Limits

- Uploads only. Books bought from the Play Store are DRM-encrypted and Apple Books
  cannot open them.
- Books opens a reader window when importing a file; it has no silent import API. The
  app quits itself afterwards if booksync started it, otherwise close the windows.
- Highlights and notes stay in Play Books.
- The Play Books page can change. If `shelf` returns nothing, the selectors in
  `src/booksync/fetch.py` need a look.

## Automation

```sh
make agent        # daily 09:15 sync via launchd
make agent-remove
```

Raycast commands are in `raycast/`. Add that folder in Raycast > Extensions > Script
Commands for a one-keystroke sync and an inline status item.
