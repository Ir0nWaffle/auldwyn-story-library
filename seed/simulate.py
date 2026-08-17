"""Dev/test seeding: feeds the two sample stories through the real ingest
pipeline directly (bypassing HTTP and the internal-token check) so there's
a fast local path that doesn't need the portrait bot wired up. The real
production path is library_api's POST /internal/ingest -- this is only
for local testing/demo. Mirrors Auldwyn-Lore's `ingest` one-shot pattern.

    docker compose run --rm library_api python /app/seed/simulate.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.ingest import ingest_story

SEED_DIR = Path(__file__).resolve().parent / "catalog_seed"

SAMPLE_STORIES = [
    dict(
        story_id="salt-road-confession",
        title="The Salt Road Confession",
        author="Corvin Ashgrove",
        text_file="salt-road-confession.txt",
        image_file=None,
    ),
    dict(
        story_id="river-of-glass",
        title="The River of Glass",
        author="Wren Talbot",
        text_file="river-of-glass.txt",
        image_file="river-of-glass-player-art.png",
    ),
]


def main():
    now = datetime.now(timezone.utc).isoformat()
    for entry in SAMPLE_STORIES:
        text = (SEED_DIR / entry["text_file"]).read_text()
        image_bytes = None
        if entry["image_file"]:
            image_bytes = (SEED_DIR / entry["image_file"]).read_bytes()

        story = ingest_story(
            story_id=entry["story_id"],
            title=entry["title"],
            author=entry["author"],
            text=text,
            updated_iso=now,
            image_bytes=image_bytes,
        )
        print(f"ingested: {story.title} — by {story.author} "
              f"[cover={story.cover_file}, epub={story.epub_file}, "
              f"kepub={story.kepub_file}]")


if __name__ == "__main__":
    main()
