from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Story:
    id: str  # Discord message id (or thread id) as a stable string
    title: str
    author: str
    summary: str
    updated: str  # ISO 8601, message edit time (or post time if never edited)
    content_hash: str  # sha256 of the raw story text, used for build caching
    has_custom_cover: bool
    cover_file: str  # filename within DATA_DIR/covers/
    epub_file: str  # filename within DATA_DIR/books/
    kepub_file: str | None  # filename within DATA_DIR/books/, None if kepubify unavailable

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Story":
        return cls(**d)
