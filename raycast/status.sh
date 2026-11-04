#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Play Books Sync Status
# @raycast.mode inline
# @raycast.refreshTime 1h
# @raycast.icon 📚
# @raycast.packageName Books
# @raycast.description How many books are synced and when it last ran.

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
"$ROOT/bin/booksync" status --oneline
