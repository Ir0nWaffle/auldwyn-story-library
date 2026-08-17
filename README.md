# Auldwyn Story Library

Turns every post (and every edit) in `#stories` into a real EPUB — cover
art, title, author, the Auldwyn "A" watermark, the works — served over a
small API for the [picker app](../auldwyn_sync) and any OPDS/feed-reading
Kobo setup (e.g. KOReader's News Downloader) to pull from.

**This repo holds no Discord credentials at all.** The
[Auldwyn Portrait Bot](../auldwyn-portrait-bot) is the one Discord
connection watching `#stories` (alongside its existing portrait-archive
watch) — it forwards each post/edit here over an authenticated internal
HTTP call, after running any attached cover image through the same
ClamAV + NudeNet scanning it already applies to portrait uploads. See
that repo's `pipeline/story_forward.py`.

## Why this shape

Originally this was its own two-container stack with its own Discord bot
token, matching how `Auldwyn-Lore` and the portrait bot are each set up.
That changed: rather than a third bot login to manage, the portrait bot's
already-running, already-scanning Discord connection now covers
`#stories` too, and just calls this API. Two consequences:

- **One container, not two.** No bot process here to keep separate from
  an API process — there's no Discord connection in this repo to isolate
  in the first place. `library_api` both serves the public read
  endpoints *and* accepts the one authenticated write.
- **The trust boundary moved from "which container" to "which
  endpoint."** `GET /api/stories`, `/covers/{id}`, `/books/{id}.epub`,
  `/feed.xml` are public and read-only. `POST /internal/ingest` is the
  only way to write anything, gated by a shared-secret header
  (`X-Internal-Token`, checked against `INTERNAL_API_TOKEN`) — same
  convention `Auldwyn-Lore`'s `query_api` already uses for its own
  Discord-bot bypass. Only the portrait bot is expected to hold that
  token.

## Layout

```
common/            shared package used by library_api
  storage.py         DATA_DIR layout + catalog.json read/write (atomic)
  cover_gen.py        fallback + player-art cover templates, Auldwyn "A" watermark
  epub_builder.py      title/author/cover/summary -> real .epub (ebooklib)
  kepub.py             .epub -> .kepub.epub via bundled kepubify binary
  ingest.py             ties the above together; the one function POST
                         /internal/ingest calls
library_api/
  app.py              FastAPI: public GET endpoints + POST /internal/ingest
seed/
  simulate.py         dev/test seeding — calls ingest_story() directly,
                       bypassing HTTP, so there's a fast local path that
                       doesn't need the portrait bot wired up
  catalog_seed/         two sample stories used by simulate.py
```

## Setup

1. `docker network create auldwyn-net` (once — shared with the portrait
   bot so it can reach this container by name instead of going out
   through the host's published port).
2. `cp .env.example .env`, set `INTERNAL_API_TOKEN` to a random value
   (`openssl rand -hex 24`) — and set the **same** value as
   `LIBRARY_API_INTERNAL_TOKEN` in the portrait bot's own `.env`.
3. `docker compose up -d --build`
4. In the portrait bot's `.env`, set `STORIES_CHANNEL_ID` and
   `LIBRARY_API_URL=http://library_api:8000`, then redeploy that stack.
   See its README for the story-forwarding section.

## Title / author / cover convention

Enforced on the portrait bot's side (`pipeline/story_forward.py`), since
that's where the raw Discord message is available — this repo just
receives the already-parsed result:

- **Forum channel**: the thread title is the story title; the starter
  message is the body.
- **Plain text channel**: the message's first line is the title, the
  rest is the body.
- **Author** defaults to the poster's Discord display name. A body line
  reading exactly `by <name>` right after the title overrides it, for
  players who write under a character name instead of their Discord
  handle.
- **Cover**: the first image attached to the post is used as cover art,
  *if* it clears the portrait bot's ClamAV + NudeNet scan; a scan hit
  drops just the image (owner gets a DM), the story still publishes with
  a fully generated fallback cover (Auldwyn wordmark + title + byline).
  Either way the Auldwyn "A" watermark is composited onto the corner,
  and onto an internal EPUB title page too, so it shows even on readers
  that don't render cover thumbnails well.
- **Edits regenerate the book, automatically, no approval step.** Story
  identity is the Discord message/thread id; a content hash of the story
  text short-circuits a rebuild when an edit didn't actually change the
  text.

## Verified

Built and run for real on this machine:

**2026-08-17, initial two-container version** — `docker compose build`;
found and fixed two real bugs (a volume-permissions issue from a
root-owned fresh named volume vs. non-root containers, and a FastAPI
route-shadowing bug where `/books/{id}.epub` silently swallowed every
`.kepub.epub` request ahead of the more specific route); ingested both
sample stories and verified every endpoint against the live container
with real zip-integrity checks; confirmed the read-only volume mount and
named-volume persistence across a full stack teardown/`up`.

**2026-08-17, folded into `library_api` + portrait-bot integration**:
- Rebuilt as one container with the volume now read-write.
- `POST /internal/ingest`: verified a wrong token and a missing token
  both get `403`, a correct token with no image and a correct token
  with an image both succeed (`200`, real cover/EPUB/KEPUB generated),
  and — safe-default check — an unset `INTERNAL_API_TOKEN` makes the
  endpoint refuse everything with `503` rather than silently accepting
  unauthenticated writes.
- **Real cross-repo network test**: built the portrait bot's actual
  Docker image and ran it standalone on the shared `auldwyn-net`
  network, calling `http://library_api:8000` exactly as
  `pipeline/story_forward.py` does in production — `/health` and
  `/api/stories` returned real data, and a bad-token `/internal/ingest`
  call correctly got `403`. This confirms the two stacks can actually
  reach each other over the shared network, not just that each one
  works in isolation.

**Not yet verified**: the portrait bot's real Discord-side trigger (a
message posted in `#stories` on the actual server, going through
`on_message`/`on_message_edit` end to end) — no channel ID is configured
yet. Everything on this repo's side of that boundary (the HTTP endpoint
itself) is verified as above.

## Only Linux kepubify is bundled

`common/assets/kepubify-linux-64bit` — fine, since this only ever runs in
the Linux container above. Irrelevant to the separate `auldwyn_sync`
picker app, which needs its own per-OS kepubify binary bundled at
PyInstaller build time (see that project's README).

## License

[AGPL-3.0-or-later](LICENSE). Not a free choice: `common/epub_builder.py`
does `from ebooklib import epub` — a direct in-process import of
[ebooklib](https://github.com/aerkalov/ebooklib), which is itself
AGPL-3.0. That makes this codebase a combined work under the same
license, and `library_api` is a network service (`GET /api/stories`,
`/feed.xml`, etc.) — exactly the case AGPL's network-use clause (§13)
covers: anyone interacting with it over the network is entitled to the
corresponding source, the same as if a copy had been distributed to
them.

Everything else pulled in is permissive and doesn't conflict: FastAPI
(MIT), uvicorn (BSD-3), python-multipart (Apache-2.0/BSD), Pillow
(HPND). `kepubify` (MIT) is invoked as a bundled external binary, not
imported as a library, so it's mere aggregation either way.

## Porting to another machine

Everything needed is in this repo (`common/`, `library_api/`,
`docker-compose.yml`, `.env.example`) plus the portrait bot's
story-forwarding config — nothing is tied to this specific machine
beyond the `auldwyn-net` network name both repos reference. The
`library_data` volume holds all generated covers/books/catalog — carry
it over, or let it rebuild by re-forwarding `#stories` history (not
currently automated; would need a one-shot backfill job in the portrait
bot to walk channel history through the same forwarding path used for
live posts).
