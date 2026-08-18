"""Shared author-list formatting -- used by epub_builder, cover_gen, and
ingest.py so "who wrote this" is displayed consistently everywhere
(cover byline, EPUB title page, dc:creator metadata, API responses)."""
from __future__ import annotations


def format_authors(authors: list[str]) -> str:
    """Oxford-style join: 'A', 'A & B', 'A, B & C'."""
    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} & {authors[1]}"
    return ", ".join(authors[:-1]) + f" & {authors[-1]}"
