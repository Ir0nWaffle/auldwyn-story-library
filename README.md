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
  azw3.py               .epub -> .azw3 via the calibre_converter sidecar (HTTP)
  ingest.py             ties the above together; the one function POST
                         /internal/ingest calls
library_api/
  app.py              FastAPI: public GET endpoints + POST /internal/ingest
calibre_converter/
  app.py              internal-only HTTP wrapper around stock Calibre's
                       ebook-convert; see "AZW3 / Kindle support" below
seed/
  simulate.py         dev/test seeding — calls ingest_story() directly,
                       bypassing HTTP, so there's a fast local path that
                       doesn't need the portrait bot wired up
  catalog_seed/         two sample stories used by simulate.py
web/
  index.html/app.js/style.css   the browser library + reader embed, see
                                 "Web embed" below — plain HTML/JS/CSS, no
                                 build step, served straight off disk by
                                 library_api's own StaticFiles mount
```

## Setup

1. `docker network create auldwyn-net` (once — shared with the portrait
   bot so it can reach this container by name instead of going out
   through the host's published port).
2. `cp .env.example .env`, set `INTERNAL_API_TOKEN` to a random value
   (`openssl rand -hex 24`) — and set the **same** value as
   `LIBRARY_API_INTERNAL_TOKEN` in the portrait bot's own `.env`.
3. `docker compose up -d --build` — first build takes noticeably longer
   than before `calibre_converter` existed, since that image apt-installs
   the full Calibre package (~1GB+); subsequent builds hit Docker's layer
   cache and are quick again. `CALIBRE_CONVERTER_URL` in `.env.example`
   already points at it by container name, nothing else to configure —
   leave it blank instead if you don't want AZW3/Kindle support at all
   (see "AZW3 / Kindle support" below).
4. In the portrait bot's `.env`, set `STORIES_CHANNEL_ID` and
   `LIBRARY_API_URL=http://library_api:8000`, then redeploy that stack.
   See its README for the story-forwarding section.

## Public access (Tailscale Funnel)

Player-facing consumers (the picker app, KOReader) run on machines
outside this LAN, so `library_api` needs a real public URL. This box
already runs Tailscale with Funnel enabled for two other Auldwyn
services, each on one of the only three ports Funnel allows (`443`,
`8443`, `10000`) — all three already taken. Rather than a fourth port
(not possible), this is mounted as a **path** on the already-funneled
`:8443` (alongside `auldwyn-web-chat` at `/`):

```
https://waffleserver1.tail04c8c3.ts.net:8443/library/
```
set up via:
```bash
tailscale funnel --https=8443 --set-path=/library --bg http://127.0.0.1:8083
```
**Use `tailscale funnel`, not `tailscale serve`, for this.** Running
`serve` against a port that already has Funnel enabled silently drops
that port's Funnel flag as a side effect (confirmed the hard way —
briefly took `web_chat` off the public internet before switching to
`funnel`, which restores/keeps `AllowFunnel` correctly). Check
`tailscale serve status --json`'s `AllowFunnel` block after any change to
this if it's ever touched again.

**`PUBLIC_URL_PREFIX=/library`** in `.env` matters because of this
mount shape: Tailscale strips the `/library` prefix before forwarding to
the container, so the app itself has no way to know it's published at a
sub-path — without this, the convenience URLs in `GET /api/stories` and
`/feed.xml` (`cover_url`, `epub_url`, `kepub_url`, the feed's enclosure
links) would come back as bare `/covers/{id}` etc., which 404 when a
client (correctly) hits them against the public host. Only affects those
generated URL strings — the routes themselves (`GET /covers/{id}`, ...)
are unprefixed and work the same locally either way.

## Web embed

A browsable, scrollable story grid with an in-browser reader
([epub.js](https://github.com/futurepress/epub.js)) and a direct
"Download EPUB" button, meant to be dropped into another website as one
`<iframe>` — a proof of concept for embedding the library on the main
Auldwyn site, not a general public feature announcement yet. `web/` is
plain HTML/CSS/JS with no build step, so it's something a non-Node site
owner can open and read directly rather than bundler output; it's served
straight off disk by `library_api`'s own `StaticFiles` mount at
`/embed`, meaning no separate process, container, or deploy step — it
comes up automatically with `library_api` itself.

Embed it with:

```html
<iframe src="https://waffleserver1.tail04c8c3.ts.net:8443/library/embed/"
        style="width:100%; height:800px; border:0"></iframe>
```

(swap in whatever host/path this ends up actually published at if that
changes — see "Public access" above for the general shape).

**Why `/embed`, not `/`:** every other route in this file is deliberately
unprefixed (see `PUBLIC_URL_PREFIX`'s comment above) so it works the same
locally and behind the public Funnel path mount; `/embed` follows that
same rule rather than being a special case. `web/app.js`'s top comment
explains how its own `fetch("../api/stories")` call resolves correctly
under both the bare local URL and the public `/library`-prefixed one,
using nothing but standard relative-URL resolution — no server-detected
prefix logic needed on the client side. Cover/EPUB links don't need that
trick at all: `GET /api/stories`'s `cover_url`/`epub_url` fields already
carry the correct prefix server-side, so the page just uses those as-is.

**Not yet verified**: real in-browser rendering. This dev environment has
no headless browser or JS runtime to actually execute `app.js` against
epub.js — what's been checked is that every route the page depends on
(`/embed/`, `/embed/app.js`, `/embed/style.css`, `/embed/assets/...`,
`/api/stories`) serves the right content/content-type from a locally run
server seeded via `seed/simulate.py`, and that the relative-URL scheme
above resolves exactly as intended (checked directly with
`urllib.parse.urljoin`) for both the local and publicly-prefixed cases.
Actually opening the page in a real browser and confirming epub.js reads
a story, paginates, and the download button saves a working file is the
next check before calling this more than a proof of concept.

## Title / author / cover convention

Enforced on the portrait bot's side (`pipeline/story_forward.py`), since
that's where the raw Discord message is available — this repo just
receives the already-parsed result:

- **`#stories` is a Forum channel**: every post is its own thread, the
  thread title is the story title, the starter message is the story's
  first segment.
- **Author(s)**: the starter's poster is always an author. A thread
  reply at least `STORY_COMMENT_LENGTH_THRESHOLD` characters (default
  100, configured on the portrait bot's side) counts as a real
  continuation — appended to the story, its poster added as a
  co-author, in the order contributors first appear. Anything shorter is
  a comment and is ignored completely, never touching the book. See the
  portrait bot's README, "Comments vs. collaboration", for the full
  reasoning (deliberately length-only, no typed marker). A body line
  reading exactly `by <name>` right after the title (starter *or* any
  continuation) overrides that segment's credited author, for players
  who write under a character name instead of their Discord handle.
  Multiple authors get one real `dc:creator` entry each in the EPUB
  (not a joined string) via `common/authors.py`'s `format_authors()`,
  which also produces the "A & B" / "A, B & C" display string used for
  the cover byline and the catalog's `author` field.
- **Cover**: the first image attached to the *starter* post is used as
  cover art (a collaborator's continuation adding an image is out of
  scope for now),
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

**2026-08-17, security pass before going public + Tailscale Funnel**:
- Found and fixed two real issues while reviewing before public exposure
  (not hypothetical — both verified against the live container):
  - `story_id` flowed unsanitized into filenames written under `DATA_DIR`
    — harmless with the portrait bot as the only caller (always sends a
    plain numeric Discord id), but a real path-traversal risk once the
    token becomes the only barrier against an internet-facing caller.
    Fixed with a strict allowlist regex (`^[A-Za-z0-9_-]{1,128}$`),
    checked before any file touches disk. Verified: a
    `../../../../tmp/pwned` attempt got `400` and nothing was written
    outside `DATA_DIR`; a real numeric id still works.
  - Token comparison was `!=` (not constant-time). Switched to
    `hmac.compare_digest`. Re-verified wrong/missing tokens still `403`.
- Published via Tailscale Funnel path-mount on `:8443` (see "Public
  access" above). **Caught a real deployment mistake in the process**:
  the first attempt used `tailscale serve` instead of `tailscale funnel`,
  which silently dropped `web_chat`'s existing public Funnel flag on that
  same port as a side effect — caught immediately via
  `tailscale serve status --json`'s `AllowFunnel` block, fixed by
  reapplying with `funnel`, and re-verified all three previously-public
  endpoints (`web_chat` root, `query_api` on `:10000`, and the new
  `/library` path) all return `200`/real data over the actual public
  HTTPS URL, not just `localhost`.
- Found and fixed a second real bug this surfaced: `cover_url` /
  `epub_url` / `kepub_url` / feed enclosure links were generated as bare
  `/covers/{id}` etc., which 404 when accessed at the real public path
  (Tailscale strips its own path prefix before forwarding, so the app had
  no way to know it's mounted at `/library`). Added `PUBLIC_URL_PREFIX`;
  verified by fetching `/api/stories` from the real public URL, taking
  the exact `cover_url` string it returned, and confirming that exact
  URL downloads real cover bytes — not just that the field looks right.

**2026-08-17, multi-author / comment-vs-continuation support**:
- `POST /internal/ingest` changed from a single `author` field to a
  repeated `authors` form field (list). Verified directly against the
  live container: a real two-author ingest produced an EPUB with two
  separate `dc:creator` entries (`Corvin Ashgrove`, `Wren Talbot` —
  confirmed by unzipping the actual output and reading `content.opf`,
  not just checking the API's response), a single-author story still
  works unchanged, and an empty `authors` list is rejected (`400`).
- Full real cross-repo test (from the portrait bot's side, see that
  repo's README) confirmed the whole point of this change end-to-end: a
  short comment never reached the story text, a long reply from a
  second author did, credited correctly, both as a `dc:creator` and in
  the joined display string.

**Not yet verified**: the portrait bot's real Discord-side trigger (a
message posted in `#stories` on the actual server, going through
`on_message`/`on_message_edit` end to end) — no channel ID is configured
yet. Everything on this repo's side of that boundary (the HTTP endpoint
itself, and now the public path it's actually reachable at) is verified
as above.

**2026-08-18, AZW3 / Kindle support**:
- `ingest_story()` run end-to-end against a real `.env`-less local
  `DATA_DIR` with no `CALIBRE_CONVERTER_URL` configured: confirmed the
  existing epub/kepub generation is completely unaffected, and the new
  `azw3_file` field comes back `None` and serializes as `null` in
  `catalog.json` rather than breaking anything.
- `GET /api/stories` and `GET /books/{id}.azw3` against a live `app`
  instance (`fastapi.testclient`) with that same no-azw3 story: `azw3_url`
  correctly `null` in the list response, and the new route 404s with a
  clear message rather than erroring — while `GET /books/{id}.epub` and
  `.kepub.epub` continue working unchanged (no regression from adding
  the new route).
- `common/azw3.py`'s fallback contract, both without and with a
  `calibre_converter`: confirmed `to_azw3()` returns `None` cleanly when
  `CALIBRE_CONVERTER_URL` is unset, when the URL points at nothing
  listening, *and* — the real test — against an actual live
  `calibre_converter` instance (`uvicorn` run for real, `/health` polled
  to confirm it was actually up) reached over real HTTP on localhost:
  the sidecar's own `/convert` correctly 500s (no `ebook-convert`
  binary present outside its real Docker image) and the client-side
  `to_azw3()` still returns `None` rather than raising — proving the
  non-fatal-fallback contract holds across an actual process boundary,
  not just in a mocked one.
- Found and fixed a real bug while building `calibre_converter/app.py`:
  a missing `ebook-convert` binary raised an *unhandled* `FileNotFoundError`
  (500 with a raw traceback) instead of a clean error — caught explicitly
  now, and `GET /health` reports `ebook_convert_found` so a broken image
  build (apt install silently failing, `PATH` misconfigured) is visible
  before the first real conversion request hits it.

**2026-08-18, calibre_converter built and run for real** — `docker build`
against `calibre_converter/Dockerfile` on this machine (apt-installing
Calibre, ~2.05GB image), then run standalone (`docker run`, host-port
mapped, *not* via `docker compose up` — see below for why) and exercised
for real, not mocked:
- `GET /health` on the running container: `ebook_convert_found: true` —
  confirms Calibre's `ebook-convert` actually landed on `PATH` inside the
  image, not just that `apt-get install` reported success.
- A real `.epub` (built via `common/epub_builder.build_epub`, not a
  hand-crafted fixture) posted to `POST /convert`: came back as a real,
  valid Mobipocket/AZW3 file — confirmed with `file`, which correctly
  identified it as `Mobipocket E-book "A Real Test Story" ... version 8`
  (MOBI8/KF8 is what AZW3 actually is) with the right title embedded.
- The same conversion again, this time through the actual
  `common/azw3.to_azw3()` client rather than raw `curl` — identical
  valid output, confirming the HTTP client code path itself (not just
  the sidecar in isolation) works.
- Full `ingest_story()` run with `CALIBRE_CONVERTER_URL` pointed at the
  live container: real cover, real epub, real kepub, *and* a real azw3
  (correct title, correct multi-author display string) all produced and
  correctly recorded in `catalog.json` in one pass — then confirmed
  `GET /api/stories` returns a populated `azw3_url` and
  `GET /books/{id}.azw3` actually serves those real bytes with the right
  content-type.
- Test image and container removed afterward (`docker rmi`/`docker rm`)
  — this was a standalone, throwaway build to prove the mechanism works,
  not a deployment.

**Deliberately not done in this pass**: running this via
`docker compose up -d --build` against the real stack on this box.
`library_api/requirements.txt` also changed (added `requests`), so that
command would rebuild *and restart* the already-running, publicly
Funnel-exposed `library_api` container too, not just add the new
service — restarting a live public service is the kind of thing to
confirm before doing, not fold into a verification pass.

**2026-08-20, web embed added** — `web/` (grid + epub.js reader +
download button) and `library_api/app.py`'s `/embed` `StaticFiles`
mount:
- Ran `library_api` for real locally (`uvicorn`, `LIBRARY_DATA_DIR`
  pointed at a scratch dir) against `seed/simulate.py`'s two real seeded
  stories — confirmed every route the page depends on actually serves
  with the right status/content-type: `/embed/` → `text/html`,
  `/embed/app.js` → `text/javascript`, `/embed/style.css` → `text/css`,
  `/embed/assets/auldwyn-logo.png` → `image/png`,
  `/embed/assets/fonts/Cinzel[wght].ttf` → `font/ttf`. Also confirmed no
  regression on the pre-existing routes (`/health`, `/api/stories`,
  `/covers/{id}`, `/books/{id}.epub`, `/feed.xml`) — none collide with
  the new `/embed` mount.
- The relative-URL scheme `app.js` depends on (`fetch("../api/stories")`
  resolving correctly whether the page is at the bare local `/embed/` or
  the public Funnel-prefixed `/library/embed/`) checked directly with
  `urllib.parse.urljoin()` against both forms — confirmed it lands on
  `/api/stories` and `/library/api/stories` respectively, exactly as
  intended.
- **Not verified**: actually opening the page in a real browser. This
  dev environment has no headless browser or JS runtime available to
  execute `app.js` — whether epub.js actually renders a story,
  pagination/keyboard nav work, and the download button saves a real
  file all still need a real-browser check before this is more than a
  proof of concept. See "Web embed" above.

## Only Linux kepubify is bundled

`common/assets/kepubify-linux-64bit` — fine, since this only ever runs in
the Linux container above. Irrelevant to the separate `auldwyn_sync`
picker app, which needs its own per-OS kepubify binary bundled at
PyInstaller build time (see that project's README).

## AZW3 / Kindle support

Kindle doesn't read `.epub` or `.kepub.epub` off a USB drop — it needs
`.azw3`. Unlike kepub, this isn't a bundled binary invoked in-process:
it's a separate `calibre_converter` container (see `docker-compose.yml`)
running stock, unmodified Calibre, apt-installed, with `common/azw3.py`
talking to it over HTTP on the internal `auldwyn-net` network
(`CALIBRE_CONVERTER_URL`, blank by default in a fresh checkout — see
`.env.example`).

Why a separate container instead of just adding Calibre to `library_api`
the way kepubify was added: Calibre is a different order of magnitude in
size than kepubify's few-MB static binary (~1GB+ installed, pulls in Qt
and a large dependency tree) and wants real memory headroom to actually
run `ebook-convert` — nowhere near what `library_api`'s own
`mem_limit: 512m` allows for. Splitting it out means `library_api`'s
image and resource budget stay untouched, and a hung or crashed
conversion (ebook-convert is known to occasionally hang on malformed
input) takes down only the converter, not the API.

Same non-fatal-fallback contract as kepub: if the sidecar is down,
unconfigured, or a specific conversion fails, `to_azw3()` just returns
`None`, `azw3_file`/`azw3_url` stay null for that story, and ingest still
succeeds — an AZW3 outage never blocks a story from publishing.

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
(HPND), requests (Apache-2.0). `kepubify` (MIT) is invoked as a bundled
external binary, not imported as a library, so it's mere aggregation
either way.

`calibre_converter`'s Calibre is GPL-3.0, a stricter case worth calling
out on its own rather than folding into the kepubify sentence above:
it's a full apt-installed copy of upstream Calibre, invoked only via its
`ebook-convert` CLI as a subprocess *from a separate container*,
communicating with this codebase over a plain HTTP request/response —
no Calibre code is imported, linked, or vendored into anything this repo
ships. That keeps it mere aggregation same as kepubify, just with an
extra degree of separation (a network boundary, not just a process
boundary) given how much larger and more complex a dependency Calibre is
than a single-purpose static binary.

## Porting to another machine

Everything needed is in this repo (`common/`, `library_api/`,
`calibre_converter/`, `docker-compose.yml`, `.env.example`) plus the portrait bot's
story-forwarding config — nothing is tied to this specific machine
beyond the `auldwyn-net` network name both repos reference. The
`library_data` volume holds all generated covers/books/catalog — carry
it over, or let it rebuild by re-forwarding `#stories` history (not
currently automated; would need a one-shot backfill job in the portrait
bot to walk channel history through the same forwarding path used for
live posts).
