"""The single entry point that turns a Discord post (or an edit to one)
into a catalog entry: cover -> EPUB -> KEPUB -> catalog.json update.

Called from two places: the real bot's on_message/on_raw_message_edit
handlers, and discord_bot/simulate.py (which calls it directly against
local sample text, no Discord connection needed, for testing/demo)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import storage
from .cover_gen import make_cover
from .epub_builder import build_epub
from .kepub import to_kepub
from .models import Story


def ingest_story(
    story_id: str,
    title: str,
    author: str,
    text: str,
    updated_iso: str,
    summary: str | None = None,
    image_bytes: bytes | None = None,
) -> Story:
    storage.ensure_dirs()

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    existing = storage.get_story(story_id)
    if existing and existing.content_hash == content_hash:
        # Unchanged text on a re-save/edit event -- nothing to rebuild.
        return existing

    if summary is None:
        first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
        summary = (first_line[:157] + "...") if len(first_line) > 160 else first_line

    cover_bytes = make_cover(title, author, image_bytes)
    cover_filename = f"{story_id}-{content_hash}.png"
    (storage.COVERS_DIR / cover_filename).write_bytes(cover_bytes)

    epub_filename = f"{story_id}-{content_hash}.epub"
    epub_path = storage.BOOKS_DIR / epub_filename
    build_epub(
        story_id=story_id,
        title=title,
        author=author,
        summary=summary,
        updated_iso=updated_iso,
        text=text,
        cover_png_bytes=cover_bytes,
        out_path=epub_path,
    )

    kepub_path = to_kepub(epub_path, storage.BOOKS_DIR)

    story = Story(
        id=story_id,
        title=title,
        author=author,
        summary=summary,
        updated=updated_iso,
        content_hash=content_hash,
        has_custom_cover=image_bytes is not None,
        cover_file=cover_filename,
        epub_file=epub_filename,
        kepub_file=kepub_path.name if kepub_path else None,
    )
    storage.upsert_story(story)
    return story
