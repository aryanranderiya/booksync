# booksync

Moves the books you uploaded to Google Play Books into Apple Books, on your Mac.

Play Books has no API and Apple Books has no API, so this drives the real Play Books
web app in Chrome using the Google session you already have in Arc (or Chrome), then
hands the downloaded files to Books in batches.

Nothing is uploaded anywhere. The only network traffic is to Google, as you.

## Setup

```sh
cd ~/Projects/playbooks-sync
uv sync
```

First run may show a macOS keychain prompt for "Arc Safe Storage". Click **Always Allow**
so future runs are silent. That key is what decrypts your own arc cookies locally.

## Use

```sh
bin/booksync shelf            # what is in your Play Books library and what is synced
bin/booksync sync             # fetch new uploads and import them
bin/booksync sync --dry-run   # show what would be fetched
bin/booksync sync --only "mom test"   # one book
bin/booksync status
bin/booksync session          # is the browser session still valid
bin/booksync import ~/Downloads/some-folder
```

`sync` is idempotent. Identity is the file hash, not the title, so reruns skip
everything already archived. Books already in Apple Books are matched by ISBN, falling
back to title plus author, so nothing is imported twice.

## What it does

1. Reads your Google cookies from Arc (falls back to Chrome) and decrypts them locally.
2. Opens `play.google.com/books` in headless Chrome with that session.
3. For each book it has not seen before: opens the tile menu, clicks Export, picks
   EPUB or PDF, and saves the file.
4. Validates the file. DRM-protected store purchases are detected and dropped.
5. Archives the good ones to `~/Books/PlayBooks/` and imports them to Books in
   batches of ten, with `open -g`, so nothing steals focus or opens a window.

Books that cannot be exported (store purchases, DRM) are recorded once and skipped on
later runs. `--retry-skipped` tries them again.

## Covers

Every EPUB is checked for a cover image that actually resolves and is worth showing.
Google returns a 128x184 grey placeholder for uploads it never made art for, so those
get a typographic cover drawn locally at 1200x1800 in New York, one accent colour per
title. `booksync covers` lists anything missing; `booksync covers --reimport` fixes the
archive and replaces the copy in Books.

## Limits

- Uploads only. Bought books are DRM-encrypted and Apple Books will not open them.
- Highlights and notes stay in Play Books.
- The Play Books web UI can change. If `shelf` comes back empty or `sync` reports
  "no export option", the selectors in `src/booksync/fetch.py` need a look.
- Imported books sync to iPhone and iPad through iCloud Drive if Books is enabled there.

## Layout

```
~/Library/Application Support/booksync/state.db    what has been synced
~/Books/PlayBooks/                                 canonical archive, source of truth
```

Apple Books is a copy. If its library ever breaks, point `import` at the archive.

## Automation

```sh
make agent        # daily 09:15 sync via launchd
make agent-remove
```

Raycast commands live in `raycast/`. Add that folder in Raycast > Extensions > Script
Commands and you get "Sync Play Books to Apple Books" plus an inline status item.
