"""EPUB -> AZW3 conversion via the `calibre_converter` sidecar container
(stock, unmodified Calibre's `ebook-convert`, invoked as a subprocess
over there -- see that service's own docstring, calibre_converter/app.py).
This module is just the HTTP client half of that split; unlike
kepub.py's local subprocess call, conversion doesn't happen in this
process at all -- Calibre is a different order of magnitude in size
(~1GB+ installed) than the bundled kepubify binary, so it lives in its
own container with its own resource budget instead of bloating this
image. See the README's "AZW3 / Kindle support" section.

Same fallback contract as kepub.to_kepub(): returns None (caller then
just doesn't set azw3_file for that story) if the sidecar is
unconfigured, unreachable, or the conversion itself fails -- an AZW3
outage is never allowed to block a story from publishing.
"""
from __future__ import annotations

import os

import requests

# Internal-only, reached over the shared auldwyn-net Docker network by
# container name (see docker-compose.yml) -- same pattern the portrait
# bot uses to reach this app itself. Blank disables AZW3 generation
# entirely, same "blank disables the feature" convention
# INTERNAL_API_TOKEN already uses.
CALIBRE_CONVERTER_URL = os.environ.get("CALIBRE_CONVERTER_URL", "").rstrip("/")

# A little above the sidecar's own ebook-convert timeout (see
# calibre_converter/app.py's CONVERT_TIMEOUT_S), so a slow-but-real
# conversion's eventual error response gets back to us instead of us
# giving up and timing out first.
REQUEST_TIMEOUT_S = 200


def to_azw3(epub_bytes: bytes) -> bytes | None:
    if not CALIBRE_CONVERTER_URL:
        return None
    try:
        resp = requests.post(
            f"{CALIBRE_CONVERTER_URL}/convert",
            files={"epub": ("story.epub", epub_bytes, "application/epub+zip")},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None
