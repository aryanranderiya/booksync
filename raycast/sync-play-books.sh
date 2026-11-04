#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Sync Play Books to Apple Books
# @raycast.mode compact
# @raycast.icon 📚
# @raycast.packageName Books
# @raycast.description Pull new Google Play Books uploads into Apple Books.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/bin/booksync" sync
