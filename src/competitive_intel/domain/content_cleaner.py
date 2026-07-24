"""Deterministic HTML-to-text cleaning without model or database access."""

from __future__ import annotations

import re
from hashlib import sha256

from bs4 import BeautifulSoup, Tag

from .webpage import CleanPageRequest, CleanPageResult, CleanStatus


REMOVED_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "footer",
    "header",
    "aside",
)
CONTENT_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "tr", "th", "td")
WHITESPACE = re.compile(r"\s+")


def _normalized_text(tag: Tag) -> str:
    return WHITESPACE.sub(" ", " ".join(tag.stripped_strings)).strip()


def _content_blocks(container: Tag) -> list[str]:
    blocks: list[str] = []
    previous: str | None = None
    for tag in container.find_all(CONTENT_TAGS):
        # Parent table/tr text would duplicate its cells. Keep the deepest
        # meaningful blocks while still supporting direct table text.
        if tag.find(CONTENT_TAGS):
            continue
        text = _normalized_text(tag)
        if not text or text == previous:
            continue
        blocks.append(text)
        previous = text
    if not blocks:
        fallback = _normalized_text(container)
        if fallback:
            blocks.append(fallback)
    return blocks


def clean_page(request: CleanPageRequest) -> CleanPageResult:
    """Return stable text and a SHA-256 hash for the supplied HTML."""

    soup = BeautifulSoup(request.raw_html, "html.parser")
    title = _normalized_text(soup.title) if soup.title else None

    for element in soup.find_all(REMOVED_TAGS):
        element.decompose()

    container = soup.find("main") or soup.find("article") or soup.body
    blocks = _content_blocks(container) if isinstance(container, Tag) else []
    clean_content = "\n".join(blocks)
    clean_hash = sha256(clean_content.encode("utf-8")).hexdigest()

    return CleanPageResult(
        page_title=title,
        clean_content=clean_content,
        clean_hash=clean_hash,
        content_length=len(clean_content),
        cleaner_version=request.cleaner_version,
        clean_status=CleanStatus.SUCCESS if clean_content else CleanStatus.EMPTY,
    )
