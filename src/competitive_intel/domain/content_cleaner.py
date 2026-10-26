"""Deterministic HTML-to-text cleaning without model or database access."""

from __future__ import annotations

import re
from hashlib import sha256

from bs4 import BeautifulSoup, Tag, NavigableString, Comment

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


def _hidden_selectors(css: str):
    """Only unconditional top-level rules; never guess viewport/media state."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth, start, opened = 0, 0, 0
    for index, char in enumerate(css):
        if char == '{':
            if depth == 0:
                opened = index
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                selector, declarations = css[start:opened].strip(), css[opened + 1:index]
                if (selector and not selector.startswith('@') and '{' not in declarations
                        and re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", declarations, re.I)):
                    yield selector
                start = index + 1


def _normalized_text(tag: Tag) -> str:
    return WHITESPACE.sub(" ", " ".join(tag.stripped_strings)).strip()


def _content_blocks(container: Tag) -> list[str]:
    # Walk each visible text node exactly once; block boundaries preserve order.
    blocks, pending = [], []
    block_tags = set(CONTENT_TAGS) | {"div", "section", "article", "main", "br", "dl", "dt", "dd"}

    def flush():
        text = WHITESPACE.sub(" ", " ".join(pending)).strip()
        if text:
            blocks.append(text)
        pending.clear()

    def visit(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            if str(node).strip():
                pending.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        boundary = node.name in block_tags
        if boundary:
            flush()
        for child in node.children:
            visit(child)
        if boundary:
            flush()

    visit(container)
    flush()
    return blocks



def clean_page(request: CleanPageRequest) -> CleanPageResult:
    """Return stable text and a SHA-256 hash for the supplied HTML."""

    soup = BeautifulSoup(request.raw_html, "html.parser")
    title = _normalized_text(soup.title) if soup.title else None

    # Honor explicit HTML/inline hiding and simple embedded CSS hiding rules.
    hidden_css = []
    for style in soup.find_all("style"):
        for selectors in _hidden_selectors(style.get_text()):
            try:
                hidden_css.extend(soup.select(selectors))
            except Exception:
                pass  # Unsupported CSS is not treated as permission to remove content.
    for element in hidden_css:
        if element.parent:
            element.decompose()
    for element in list(soup.find_all(True)):
        if not element.parent or not element.attrs:
            continue
        style = str(element.get("style", ""))
        if (element.has_attr("hidden") or element.get("aria-hidden") == "true"
                or element.get("type") == "hidden"
                or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", style, re.I)):
            element.decompose()
    for element in soup.find_all((*REMOVED_TAGS, "template")):

        element.decompose()

    # Collapse only adjacent duplicate paragraphs, never repeated table cells.
    for paragraph in list(soup.find_all("p")):
        previous = paragraph.find_previous_sibling()
        if previous and previous.name == "p" and _normalized_text(previous) == _normalized_text(paragraph):
            paragraph.decompose()
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
