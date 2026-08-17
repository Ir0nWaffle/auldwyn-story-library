"""EPUB -> KEPUB conversion via the bundled kepubify binary (MIT licensed,
https://github.com/pgaskin/kepubify). See the design discussion for why
this doesn't need Calibre at all. Falls back to `None` (caller then just
serves the plain .epub) if the binary is missing for some reason."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLED = HERE / "assets" / "kepubify-linux-64bit"


def find_kepubify() -> Path | None:
    if BUNDLED.exists():
        return BUNDLED
    on_path = shutil.which("kepubify")
    return Path(on_path) if on_path else None


def to_kepub(epub_path: Path, dest_dir: Path) -> Path | None:
    kepubify = find_kepubify()
    if kepubify is None:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(kepubify), "-i", "-o", str(dest_dir), str(epub_path)],
        check=True,
        capture_output=True,
    )
    out = dest_dir / (epub_path.stem + ".kepub.epub")
    return out if out.exists() else None
