from __future__ import annotations

from pathlib import Path

from ebooklib import epub

HERE = Path(__file__).resolve().parent
A_MARK = HERE / "assets" / "auldwyn-A-mark.png"


def build_epub(
    story_id: str,
    title: str,
    author: str,
    summary: str,
    updated_iso: str,
    text: str,
    cover_png_bytes: bytes,
    out_path: Path,
) -> None:
    book = epub.EpubBook()
    book.set_identifier(f"auldwyn-{story_id}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    book.add_metadata("DC", "publisher", "Auldwyn")
    book.add_metadata("DC", "date", updated_iso)
    book.add_metadata("DC", "subject", "Auldwyn")
    book.add_metadata("DC", "description", summary)

    book.set_cover("cover.jpg", cover_png_bytes)

    a_mark_item = epub.EpubItem(
        uid="a_mark",
        file_name="images/a-mark.png",
        media_type="image/png",
        content=A_MARK.read_bytes(),
    )
    book.add_item(a_mark_item)

    title_page = epub.EpubHtml(title="Title Page", file_name="title.xhtml")
    title_page.content = f"""
      <html><body style="text-align:center; padding-top:15%;">
        <img src="images/a-mark.png" alt="Auldwyn" style="width:20%;"/>
        <h1>{title}</h1>
        <p style="font-style:italic;">an Auldwyn story</p>
        <p>by {author}</p>
      </body></html>
    """
    book.add_item(title_page)

    body_paragraphs = "".join(
        f"<p>{line}</p>" for line in text.splitlines() if line.strip()
    )
    chapter = epub.EpubHtml(title=title, file_name="story.xhtml")
    chapter.content = f"<html><body>{body_paragraphs}</body></html>"
    book.add_item(chapter)

    book.toc = (title_page, chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["cover", title_page, chapter]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
