# booksync

**Your Google Play Books uploads, in Apple Books, on your Mac.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)

---

You uploaded a pile of EPUBs and PDFs to Google Play Books. Apple Books can't see
them, and neither app offers a way to move them across. Right now your options are
clicking Export on 70 books one at a time, or giving up.

This closes that gap. One command checks your Play Books library, downloads whatever
is new, and adds it to Apple Books. Run it again next month and it only picks up the
books you added since.

```
$ booksync sync
session       arc, 131 cookies
library       74 book(s)
to fetch      2
  [1/2] The Mom Test
  [2/2] Rich Dad, Poor Dad
importing     2 book(s) in 1 batch(es)

2 imported · 0 already in books · 0 unexportable · 72 unchanged · 0 failed
```

## What you need

- A Mac
- Google Chrome installed
- Signed in to Google Play Books in **Arc** or Chrome
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)

## Install

```sh
git clone https://github.com/aryanranderiya/booksync.git
cd booksync
uv sync
```

That gives you `bin/booksync`. To get a plain `booksync` command instead:

```sh
uv tool install .
```

## First run

```sh
booksync shelf
```

This lists everything in your Play Books library and whether it is already synced.
It also tells you which browser it borrowed your login from.

The first run may ask for your macOS password. That is your Mac unlocking the key
that protects your browser's cookies. Choose **Always Allow** so it only asks once.

Then:

```sh
booksync sync --dry-run   # see what it would do
booksync sync             # do it
```

## Everyday use

```sh
booksync sync              # fetch anything new and add it to Apple Books
booksync shelf             # what's in Play Books, synced or not
booksync status            # how many are synced, when it last ran
booksync import ~/Downloads  # add loose EPUB/PDF files you already have
```

Handy extras:

```sh
booksync sync --only "mom test"   # one book
booksync sync --limit 5           # a few at a time
booksync sync --dry-run           # no changes, just the plan
booksync covers                   # find books with a missing cover
booksync covers --reimport        # fix them and swap them into Books
booksync doctor                   # check the setup
```

## What a sync actually does

1. Grabs your Google login from Arc (or Chrome) so it doesn't ask you to sign in.
2. Opens Play Books in a hidden browser window.
3. Skips every book it has already handled.
4. Opens each new book's menu, hits Export, and downloads the EPUB or PDF.
5. Checks the file is real and throws away store purchases, which are copy-protected.
6. Makes sure the book has a cover worth looking at.
7. Saves a copy to `~/Books/PlayBooks/` and adds it to Apple Books.

Running `booksync sync` twice does nothing the second time. Books are tracked by the
file itself and by ISBN, so you never end up with duplicates.

Books it can't export are remembered and skipped on later runs. `--retry-skipped`
tries them again.

## Is it safe?

It reads the Google cookies your own browser already has, unlocks them on your Mac,
and uses them to sign in to Google Play Books. Nothing is sent anywhere except to
Google, as you. There is no server, no account, no telemetry.

Your `~/Books/PlayBooks` folder is the master copy. If Apple Books ever gets confused,
you can rebuild from it with `booksync import ~/Books/PlayBooks`.

## What it can't do

- **Books you bought from the Play Store.** They're copy-protected and Apple Books
  won't open them. Only your own uploads work.
- **Highlights and notes.** They stay in Play Books.
- **Import without a window.** Apple Books has no quiet import, so it flashes a reader
  window while adding books. If Books was closed, booksync closes it again afterwards.

## Covers

Google gives some uploads a tiny grey placeholder instead of cover art. booksync spots
that and draws a clean typographic cover in New York, tinted per title, so the shelf in
Apple Books still looks like a shelf.

## Run it on a schedule (optional)

```sh
make agent        # every day at 09:15
make agent-remove
```

If you use [Raycast](https://raycast.com), add the `raycast/` folder under
Extensions → Script Commands. You get a one-keystroke sync and an inline status line.

## Troubleshooting

**"not signed in" / empty shelf**
Sign in at play.google.com in Arc or Chrome, then run `booksync session` to confirm.

**Keychain prompt every time**
Open Keychain Access, find "Arc Safe Storage", and set access to always allow.

**A book is missing**
`booksync shelf` marks it `skip`. Those are store purchases or files Google won't
export. `booksync sync --retry-skipped` forces another attempt.

**Apple Books shows a blank cover**
`booksync covers --reimport`.

## Development

```sh
uv sync
uv run pytest
```

Layout: `fetch.py` drives Play Books, `cookies.py` handles the browser login,
`epub.py` and `cover.py` deal with files, `apple.py` talks to Books, `state.py` keeps
track of what's done.

Pull requests welcome. This scrapes a Google web page, so selectors in `fetch.py` are
the part most likely to break when Google ships a redesign.

## License

[MIT](LICENSE)
