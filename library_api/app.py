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
  - the desktop picker app (GET /api/stories, GET /books/{id}.epub,
    /books/{id}.kepub.epub, or /books/{id}.azw3)
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

from fastapi import FastAPI, Form, HTTPException, Header, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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

# /api/stories and the four asset routes below (cover/epub/kepub/azw3) all
# serve mutable content behind a URL that's stable per story_id -- a cover
# or book can be regenerated in place (an edit, or a backfill like the
# cover-art-from-thread-images one) without the URL changing at all, since
# story_id is the route key, not the content-hash-named file it currently
# points to. Without an explicit Cache-Control, browsers are free to serve
# a stale cached copy of that URL indefinitely instead of revalidating --
# exactly what happened after the 2026-08-21 cover backfill: regenerated
# covers landed on disk (confirmed on the server) but the embed page kept
# showing the old ones until a hard refresh. "no-cache" (not "no-store")
# still lets ETag/Last-Modified do their job -- it just forces a
# revalidation round-trip instead of trusting a local copy blindly.
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/stories")
def list_stories():
    stories = sorted(storage.load_catalog(), key=lambda s: s.updated, reverse=True)
    return JSONResponse(
        [
            {
                "id": s.id,
                "title": s.title,
                "author": s.author,
                "summary": s.summary,
                "updated": s.updated,
                "cover_url": f"{PUBLIC_URL_PREFIX}/covers/{s.id}",
                "epub_url": f"{PUBLIC_URL_PREFIX}/books/{s.id}.epub",
                "kepub_url": f"{PUBLIC_URL_PREFIX}/books/{s.id}.kepub.epub" if s.kepub_file else None,
                "azw3_url": f"{PUBLIC_URL_PREFIX}/books/{s.id}.azw3" if s.azw3_file else None,
            }
            for s in stories
        ],
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/covers/{story_id}")
def get_cover(story_id: str):
    story = storage.get_story(story_id)
    if not story:
        raise HTTPException(404, "unknown story")
    return FileResponse(storage.COVERS_DIR / story.cover_file, media_type="image/png", headers=_NO_CACHE_HEADERS)


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
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/books/{story_id}.azw3")
def get_azw3(story_id: str):
    # No route-ordering hazard here the way get_kepub above has with
    # get_epub below: ".azw3" doesn't end in ".epub", so Starlette's
    # greedy {story_id} match on the generic route can never accidentally
    # swallow this one regardless of registration order. Kept up here
    # anyway to group the three /books/{id}.* routes together.
    story = storage.get_story(story_id)
    if not story or not story.azw3_file:
        raise HTTPException(404, "no azw3 available for this story")
    return FileResponse(
        storage.BOOKS_DIR / story.azw3_file,
        media_type="application/x-mobi8-ebook",
        filename=f"{story.title}.azw3",
        headers=_NO_CACHE_HEADERS,
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
        headers=_NO_CACHE_HEADERS,
    )


def _check_internal_request(story_id: str, x_internal_token: str | None) -> None:
    """Shared guard for every /internal/* route: the token check and the
    story_id shape check. Factored out once a second internal route
    (the retire-on-thread-delete one below) needed the exact same pair."""
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


@app.post("/internal/ingest")
async def internal_ingest(
    story_id: str = Form(...),
    title: str = Form(...),
    authors: list[str] = Form(...),  # repeated form field, one per author, in order
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
    _check_internal_request(story_id, x_internal_token)

    image_bytes = await image.read() if image is not None else None
    updated_iso = updated or datetime.now(timezone.utc).isoformat()

    if not authors or not any(a.strip() for a in authors):
        raise HTTPException(400, "authors must contain at least one non-empty name")

    story = ingest_story(
        story_id=story_id,
        title=title,
        authors=authors,
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
        "azw3_file": story.azw3_file,
    }


@app.delete("/internal/stories/{story_id}")
def internal_retire_story(story_id: str, x_internal_token: str | None = Header(None)):
    """Retires a catalog entry (and its cover/epub/kepub/azw3 files) whose
    originating #stories thread no longer exists on Discord.

    Called by the portrait bot's on_thread_delete/on_raw_thread_delete
    handlers when the *whole* thread disappears -- typically because its
    starter post was deleted, which takes the entire forum thread with it
    -- as opposed to a message-within-thread delete, which just triggers a
    reassembly via /internal/ingest instead. Without this route, that kind
    of thread deletion left an orphaned catalog entry behind forever: found
    for real 2026-08-19, when an author deleted-and-reposted under the same
    title and the old post's entry sat there duplicating the new one until
    it was cleaned up by hand.
    """
    _check_internal_request(story_id, x_internal_token)

    removed = storage.delete_story(story_id)
    if not removed:
        raise HTTPException(404, "unknown story")
    return {"id": story_id, "deleted": True}


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


# Static site: the library grid + in-browser epub.js reader + download
# buttons meant to be dropped into another site as a single
# `<iframe src=".../embed/">`. Mounted at the bare, unprefixed "/embed"
# path -- same convention every other route in this file follows (see
# PUBLIC_URL_PREFIX's comment above) -- which the public Tailscale Funnel
# mount then exposes as ".../library/embed/". web/app.js's top comment
# explains how its own fetches find "/api/stories" etc correctly under
# either path. html=True serves web/index.html for both "/embed" and
# "/embed/" instead of a bare directory listing.
app.mount(
    "/embed",
    StaticFiles(directory=Path(__file__).resolve().parent.parent / "web", html=True),
    name="embed",
)
