"""
Standalone AZW3 conversion service.

The only code in this container that's "ours" is this thin wrapper --
the actual conversion is stock, unmodified Calibre (`ebook-convert`),
apt-installed in the Dockerfile and invoked here as a subprocess, the
same "shell out to a bundled external tool" boundary common/kepub.py
already uses for kepubify in the main library_api image. Split into its
own container instead of bundled into library_api because Calibre is a
different order of magnitude in size/memory (~1GB+ installed, wants real
headroom to run) than kepubify's few-MB static binary -- see the
story-library README's "AZW3 / Kindle support" section for the full
reasoning, including why that also matters for the license story (GPL-3
Calibre vs MIT kepubify).

No state, no auth, no public exposure: this only ever runs on the
internal `auldwyn-net` Docker network, called by library_api's
common/azw3.py. If it's down, unreachable, or a specific conversion
fails, that's a non-fatal fallback on the caller's side (no azw3_url for
that story) -- the same contract a missing kepubify binary already has.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response

app = FastAPI(title="Auldwyn AZW3 Converter")

# ebook-convert has been known to hang on malformed input -- better to
# fail the request after a bound than tie up a worker indefinitely.
CONVERT_TIMEOUT_S = 180


@app.get("/health")
def health():
    # Reports whether ebook-convert is actually on PATH, not just that
    # this process is up -- a broken image build (apt install silently
    # failing, PATH misconfigured) would otherwise look healthy right up
    # until the first real /convert call 500s.
    return {"status": "ok", "ebook_convert_found": shutil.which("ebook-convert") is not None}


@app.post("/convert")
async def convert(epub: UploadFile) -> Response:
    epub_bytes = await epub.read()
    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "in.epub"
        out_path = Path(tmp) / "out.azw3"
        in_path.write_bytes(epub_bytes)
        try:
            subprocess.run(
                ["ebook-convert", str(in_path), str(out_path)],
                check=True,
                capture_output=True,
                timeout=CONVERT_TIMEOUT_S,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace")[-2000:]
            raise HTTPException(422, f"ebook-convert failed: {stderr}")
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "ebook-convert timed out")
        except FileNotFoundError:
            # Caught explicitly rather than left to surface as an
            # unhandled 500 -- means the image itself is broken (apt
            # install of calibre failed or PATH is wrong), which is
            # meaningfully different from a normal per-story conversion
            # failure and worth its own message pointing at the cause.
            raise HTTPException(500, "ebook-convert binary not found -- calibre_converter image is misconfigured")

        if not out_path.exists():
            # Not expected to actually happen (check=True should have
            # already raised on any nonzero exit) -- guarded anyway
            # rather than trusting that assumption silently.
            raise HTTPException(500, "ebook-convert reported success but produced no output file")

        return Response(
            content=out_path.read_bytes(),
            media_type="application/x-mobi8-ebook",
        )
