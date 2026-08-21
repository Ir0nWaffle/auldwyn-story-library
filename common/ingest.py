"""The single entry point that turns a Discord post (or an edit to one)
into a catalog entry: cover -> EPUB -> KEPUB -> catalog.json update.

Called from two places: the real bot's on_message/on_raw_message_edit
handlers, and discord_bot/simulate.py (which calls it directly against
local sample text, no Discord connection needed, for testing/demo)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import storage
from .authors import format_authors
from .azw3 import to_azw3
from .cover_gen import make_cover, make_thumbnail
from .epub_builder import build_epub
from .kepub import to_kepub
from .models import Story


def ingest_story(
    story_id: str,
    title: str,
    authors: list[str],
    text: str,
    updated_iso: str,
    summary: str | None = None,
    image_bytes: bytes | None = None,
) -> Story:
    """`authors` is the full, ordered, de-duplicated list for this story --
    the caller (portrait bot's thread-assembly logic) is responsible for
    deciding who that is; this function just renders whatever it's given.
    One dc:creator per author in the EPUB; `format_authors()` produces the
    single display string used for the cover byline and the catalog's
    `author` field.
    """
    storage.ensure_dirs()

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    existing = storage.get_story(story_id)
    if (
        existing
        and existing.content_hash == content_hash
        and existing.has_custom_cover == (image_bytes is not None)
        and existing.thumb_file is not None
    ):
        # Unchanged text AND unchanged cover-image availability AND
        # already has a thumbnail on a re-save/edit event -- nothing to
        # rebuild. (A change in `authors` with no change in `text` can't
        # happen in practice: a new contributor's segment is what changes
        # the text in the first place -- see the portrait bot's
        # assemble_story().)
        #
        # The has_custom_cover check matters on top of the hash check: a
        # backfill re-run (e.g. after story_forward.py's cover-image search
        # widens to cover more of the thread, or a caller passes an image
        # that simply wasn't available before) can find a cover for a story
        # whose text hasn't changed at all -- a hash-only check would
        # silently skip regenerating the cover/epub/kepub/azw3 in that case.
        #
        # The thumb_file check exists purely to migrate pre-thumbnail
        # entries (added 2026-08-21): the next time any such story is
        # forwarded for any reason, this forces one rebuild to backfill
        # its thumbnail, same trick as has_custom_cover above.
        return existing

    if summary is None:
        first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
        summary = (first_line[:157] + "...") if len(first_line) > 160 else first_line

    author_display = format_authors(authors)

    cover_bytes = make_cover(title, author_display, image_bytes)
    cover_filename = f"{story_id}-{content_hash}.png"
    (storage.COVERS_DIR / cover_filename).write_bytes(cover_bytes)

    thumb_bytes = make_thumbnail(cover_bytes)
    thumb_filename = f"{story_id}-{content_hash}-thumb.jpg"
    (storage.COVERS_DIR / thumb_filename).write_bytes(thumb_bytes)

    epub_filename = f"{story_id}-{content_hash}.epub"
    epub_path = storage.BOOKS_DIR / epub_filename
    build_epub(
        story_id=story_id,
        title=title,
        authors=authors,
        summary=summary,
        updated_iso=updated_iso,
        text=text,
        cover_png_bytes=cover_bytes,
        out_path=epub_path,
    )

    kepub_path = to_kepub(epub_path, storage.BOOKS_DIR)

    # Unlike to_kepub, conversion doesn't happen in this process -- see
    # common/azw3.py's docstring for why (the calibre_converter sidecar
    # does the actual work and hands back finished bytes over HTTP), so
    # this is the one format we write to BOOKS_DIR ourselves rather than
    # the converter writing there directly.
    azw3_bytes = to_azw3(epub_path.read_bytes())
    azw3_filename = None
    if azw3_bytes is not None:
        azw3_filename = f"{story_id}-{content_hash}.azw3"
        (storage.BOOKS_DIR / azw3_filename).write_bytes(azw3_bytes)

    story = Story(
        id=story_id,
        title=title,
        author=author_display,
        summary=summary,
        updated=updated_iso,
        content_hash=content_hash,
        has_custom_cover=image_bytes is not None,
        cover_file=cover_filename,
        thumb_file=thumb_filename,
        epub_file=epub_filename,
        kepub_file=kepub_path.name if kepub_path else None,
        azw3_file=azw3_filename,
    )
    storage.upsert_story(story)
    return story
