"""
Auldwyn Story Library API.

This process holds no Discord credentials at all -- the Auldwyn Portrait
Bot is the one Discord connection watching #stories (alongside its
existing portrait-archive watch), and forwards each post/edit here over
HTTP after running it through the same ClamAV + NudeNet scanning it
already applies to portrait uploads. See that repo's
pipeline/story_forward.py.

Two trust levels in one app:
  - GET endpoints (stories, covers, books, feed) are public, read-only.
  - POST /internal/ingest is the only write path, gated by a shared
    secret (INTERNAL_API_TOKEN) in the X-Internal-Token header -- same
    convention Auldwyn-Lore's query_api uses for its Discord bot bypass.
    Only the portrait bot is expected to hold that token.

Consumed by:
  - the desktop picker app (GET /api/stories, GET /books/{id}.epub or
    /books/{id}.kepub.epub)
  - KOReader's News Downloader / any OPDS-ish reader (GET /feed.xml)
  - the portrait bot (POST /internal/ingest)
"""
from __future__ import annotations

import hmac
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Form, HTTPException, Header, UploadFile
from fastapi.responses import FileResponse, Response

from common import storage
from common.ingest import ingest_story

app = FastAPI(title="Auldwyn Story Library")

INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

# This container's own routes are unprefixed (e.g. GET /covers/{id}) --
# that's correct for local/direct access (curl http://localhost:8083/...,
# the portrait bot over the docker network) but wrong for the public
# Tailscale Funnel path mount, which strips its own prefix before
# forwarding, so the app has no built-in way to know it's mounted at
# .../library publicly. Rather than guess, this is explicit: set to
# "/library" in .env to match how it's actually published (see README),
# blank if serving from the bare root. Only affects the convenience URL
# fields returned in JSON/the Atom feed below -- the real routes
# themselves are unaffected either way.
PUBLIC_URL_PREFIX = os.environ.get("PUBLIC_URL_PREFIX", "").rstrip("/")

# story_id ends up directly in generated filenames (see common/ingest.py:
# f"{story_id}-{content_hash}.png" etc, written under DATA_DIR). The only
# caller today (the portrait bot) always sends a plain Discord snowflake
# id, so this never triggers in practice -- but /internal/ingest is about
# to be reachable from the public internet, at which point the token
# becomes the *only* thing stopping a crafted story_id like
# "../../../../etc/cron.d/x" from writing outside DATA_DIR. Validating
# the shape here is a second, independent control, not a replacement for
# the token check below.
_SAFE_STORY_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/stories")
def list_stories():
    stories = sorted(storage.load_catalog(), key=lambda s: s.updated, reverse=True)
    return [
        {
            "id": s.id,
            "title": s.title,
            "author": s.author,
            "summary": s.summary,
            "updated": s.updated,
            "cover_url": f"{PUBLIC_URL_PREFIX}/covers/{s.id}",
            "epub_url": f"{PUBLIC_URL_PREFIX}/books/{s.id}.epub",
            "kepub_url": f"{PUBLIC_URL_PREFIX}/books/{s.id}.kepub.epub" if s.kepub_file else None,
        }
        for s in stories
    ]


@app.get("/covers/{story_id}")
def get_cover(story_id: str):
    story = storage.get_story(story_id)
    if not story:
        raise HTTPException(404, "unknown story")
    return FileResponse(storage.COVERS_DIR / story.cover_file, media_type="image/png")


@app.get("/books/{story_id}.kepub.epub")
def get_kepub(story_id: str):
    # Registered BEFORE get_epub below: {story_id} is a plain greedy
    # string match, so "/books/foo.kepub.epub" would otherwise also
    # satisfy "/books/{story_id}.epub" (with story_id="foo.kepub") since
    # route order decides ties, not specificity. FastAPI/Starlette match
    # routes in registration order, so the more specific pattern has to
    # come first or it never gets reached.
    story = storage.get_story(story_id)
    if not story or not story.kepub_file:
        raise HTTPException(404, "no kepub available for this story")
    return FileResponse(
        storage.BOOKS_DIR / story.kepub_file,
        media_type="application/epub+zip",
        filename=f"{story.title}.kepub.epub",
    )


@app.get("/books/{story_id}.epub")
def get_epub(story_id: str):
    story = storage.get_story(story_id)
    if not story:
        raise HTTPException(404, "unknown story")
    return FileResponse(
        storage.BOOKS_DIR / story.epub_file,
        media_type="application/epub+zip",
        filename=f"{story.title}.epub",
    )


@app.post("/internal/ingest")
async def internal_ingest(
    story_id: str = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    text: str = Form(...),
    updated: str | None = Form(None),
    image: UploadFile | None = None,
    x_internal_token: str | None = Header(None),
):
    """Called by the portrait bot after it has already scanned any attached
    image (ClamAV + NudeNet) and rejected/stripped it if flagged -- this
    endpoint trusts the caller's image as pre-cleared and does no scanning
    of its own. It is NOT meant to be reachable by anything else; that
    trust boundary is the whole reason for the token check below.
    """
    if not INTERNAL_API_TOKEN:
        raise HTTPException(503, "ingest disabled: INTERNAL_API_TOKEN not configured")
    # Constant-time compare -- `!=` on secrets leaks timing information an
    # attacker could in principle use to guess the token byte by byte.
    # Impractical over normal internet latency jitter for a 192-bit token,
    # but there's no reason to rely on that instead of just using the
    # comparison built for this.
    if not x_internal_token or not hmac.compare_digest(x_internal_token, INTERNAL_API_TOKEN):
        raise HTTPException(403, "invalid or missing X-Internal-Token")
    if not _SAFE_STORY_ID.match(story_id):
        # See _SAFE_STORY_ID's comment above -- this is the second,
        # independent control against a crafted story_id escaping
        # DATA_DIR via the filenames ingest_story() builds from it.
        raise HTTPException(400, "story_id must match ^[A-Za-z0-9_-]{1,128}$")

    image_bytes = await image.read() if image is not None else None
    updated_iso = updated or datetime.now(timezone.utc).isoformat()

    story = ingest_story(
        story_id=story_id,
        title=title,
        author=author,
        text=text,
        updated_iso=updated_iso,
        image_bytes=image_bytes,
    )
    return {
        "id": story.id,
        "title": story.title,
        "author": story.author,
        "cover_file": story.cover_file,
        "epub_file": story.epub_file,
        "kepub_file": story.kepub_file,
    }


@app.get("/feed.xml")
def atom_feed():
    """Atom feed for KOReader's News Downloader (or any feed reader) --
    the "subscribe and get new/updated stories automatically" path from
    the original design discussion, independent of the picker app."""
    stories = sorted(storage.load_catalog(), key=lambda s: s.updated, reverse=True)
    entries = "\n".join(
        f"""
  <entry>
    <title>{escape(s.title)}</title>
    <id>urn:auldwyn:story:{escape(s.id)}</id>
    <updated>{escape(s.updated)}</updated>
    <author><name>{escape(s.author)}</name></author>
    <summary>{escape(s.summary)}</summary>
    <link rel="enclosure" type="application/epub+zip" href="{escape(PUBLIC_URL_PREFIX)}/books/{escape(s.id)}.epub"/>
  </entry>"""
        for s in stories
    )
    latest = stories[0].updated if stories else ""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Auldwyn Stories</title>
  <id>urn:auldwyn:stories</id>
  <updated>{escape(latest)}</updated>{entries}
</feed>"""
    return Response(content=xml, media_type="application/atom+xml")
