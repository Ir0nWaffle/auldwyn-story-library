"""
Shared on-disk layout, used by both the Discord bot (writer) and the
library API (reader). Both point at the same DATA_DIR -- a Docker named
volume in production, so the two containers agree on paths without
talking to each other directly.

    DATA_DIR/
      catalog.json      <- list of Story dicts, the single source of truth
      covers/            <- one PNG per story
      books/             <- .epub and .kepub.epub files, content-hash named

Writes are atomic (write to a temp file, then os.replace) so the API
container never reads a half-written catalog.json, even without an
explicit lock -- there's exactly one writer (the bot) by design.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Story

DATA_DIR = Path(os.environ.get("LIBRARY_DATA_DIR", "/data"))
COVERS_DIR = DATA_DIR / "covers"
BOOKS_DIR = DATA_DIR / "books"
CATALOG_FILE = DATA_DIR / "catalog.json"


def ensure_dirs() -> None:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)


def load_catalog() -> list[Story]:
    if not CATALOG_FILE.exists():
        return []
    data = json.loads(CATALOG_FILE.read_text())
    return [Story.from_dict(d) for d in data]


def save_catalog(stories: list[Story]) -> None:
    ensure_dirs()
    tmp = CATALOG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([s.to_dict() for s in stories], indent=2))
    os.replace(tmp, CATALOG_FILE)


def upsert_story(story: Story) -> None:
    """Insert, or replace-in-place if `story.id` already exists (an edit)."""
    stories = load_catalog()
    for i, existing in enumerate(stories):
        if existing.id == story.id:
            stories[i] = story
            save_catalog(stories)
            return
    stories.append(story)
    save_catalog(stories)


def get_story(story_id: str) -> Story | None:
    for s in load_catalog():
        if s.id == story_id:
            return s
    return None


def delete_story(story_id: str) -> bool:
    """Removes a catalog entry and its cover/epub/kepub/azw3 files.

    Used to retire an entry whose originating Discord thread has been
    deleted outright (as opposed to a message within it, which just
    triggers a reassembly) -- see the portrait bot's
    on_thread_delete/on_raw_thread_delete handlers. Without this, a
    delete-and-repost (rather than an in-place edit) leaves the old
    thread's entry behind forever as an orphan, duplicating whatever
    the new post creates (found for real 2026-08-19, cleaned up by hand
    before this function existed).

    Returns True if something was actually removed, False if `story_id`
    wasn't in the catalog to begin with (already retired, or never made
    it in -- e.g. every message in the thread was short enough to count
    as a comment).
    """
    stories = load_catalog()
    match = next((s for s in stories if s.id == story_id), None)
    if match is None:
        return False

    remaining = [s for s in stories if s.id != story_id]
    save_catalog(remaining)

    for filename, directory in (
        (match.cover_file, COVERS_DIR),
        (match.thumb_file, COVERS_DIR),
        (match.epub_file, BOOKS_DIR),
        (match.kepub_file, BOOKS_DIR),
        (match.azw3_file, BOOKS_DIR),
    ):
        if filename:
            (directory / filename).unlink(missing_ok=True)

    return True
