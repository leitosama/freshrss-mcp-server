"""Turn article HTML into Markdown before it reaches the caller.

Both sources of article text are HTML: FreshRSS hands back the feed's own
``<description>``/``<content:encoded>`` fragment, and scraped pages are raw
documents. Neither reads well as a tool result - tag noise dominates the token
count, and structure an agent actually needs (lists, tables, link targets) is
buried in markup. Every article body therefore passes through
:func:`to_markdown` on its way out.

Scraped pages are the exception: :mod:`trafilatura` already emits Markdown
directly, so ``tools.fetcher`` asks it for that instead of converting twice.
"""

import logging
import re
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from markdownify import markdownify

logger = logging.getLogger(__name__)

# =============================================================================
# Conversion settings
# =============================================================================

# Tags whose markup carries nothing a reader can use. markdownify keeps the
# *children* of a stripped tag, so <figure> still yields its caption and
# <iframe>/<video> their fallback text, while <img> and <picture>/<source>
# vanish along with the long CDN URLs feeds like to inline.
#
# script and style are deliberately absent: markdownify's own converters
# already discard them together with their contents, whereas naming them here
# would strip the tags and emit their source as prose.
_STRIP_TAGS = ["img", "picture", "source", "figure", "iframe", "video", "audio"]

# A body with neither a tag nor an entity is already plain text - some feeds
# publish exactly that - and running it through the converter would only risk
# reflowing it for nothing.
_MARKUP_HINT = re.compile(r"<[a-zA-Z/!]|&[#a-zA-Z0-9]{1,32};")

# Everything a table cell cannot hold literally. A pipe would open a new column
# and any vertical whitespace would end the row, so both are neutralised rather
# than allowed to break the table around them: feed titles are arbitrary text
# from a third party, and one title with a pipe in it must not cost the caller
# every other row.
_CELL_BREAKERS = re.compile(r"[|\r\n\t]")

# Block-level tags, used by the fallback stripper to keep sentences from
# running together once their tags are gone.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)

# Non-printing passengers common in syndicated HTML. A non-breaking space is
# folded into a normal one rather than dropped, since it is holding a real gap.
_NBSP = "\u00a0"
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")

# A whole URL, so that utm_ stripping works on the query string alone and a
# question mark in prose is left alone. The last character is restricted
# separately to keep a sentence's closing punctuation out of the match.
_URL = re.compile(r"https?://[^\s<>\"'\])]*[^\s<>\"'\]).,;:!?]")


# =============================================================================
# Public API
# =============================================================================


def to_markdown(html: str | None) -> str:
    """Convert an HTML article body to Markdown.

    Never raises: a body that cannot be converted falls back to
    :func:`strip_tags`, so one malformed article costs its own formatting
    rather than the whole listing it appears in.

    Args:
        html: Article HTML, or plain text, or None

    Returns:
        Markdown text, empty if there was nothing to convert
    """
    if not html or not html.strip():
        return ""

    if not _MARKUP_HINT.search(html):
        return _tidy(html)

    try:
        converted = markdownify(
            html,
            heading_style="ATX",
            bullets="-",
            strip=_STRIP_TAGS,
            # The result is read as text by a model, never re-rendered back to
            # HTML, so backslash escapes are pure noise - and actively
            # misleading when they land inside a name the agent may quote back,
            # turning snake_case into snake\_case.
            escape_asterisks=False,
            escape_underscores=False,
            escape_misc=False,
        )
    except Exception as e:
        # markdownify parses into a tree and walks it recursively, so tag soup
        # nested a few hundred levels deep - unclosed <div>s in a mangled feed
        # will do it - raises RecursionError. Plain text beats no text.
        logger.warning("Falling back to tag stripping, markdown conversion failed: %s", e)
        return strip_tags(html)

    return _tidy(converted)


def strip_utm(text: str) -> str:
    """Drop ``utm_*`` tracking parameters from every URL in a string.

    Feeds append these to the links they publish - both the article's own link
    and the ones inside its body - where they carry nothing for a reader.

    Args:
        text: A bare URL, or any text with URLs in it

    Returns:
        The same text with every ``utm_*`` parameter removed
    """
    return _URL.sub(_drop_utm, text) if "utm_" in text else text


def strip_tags(html: str | None) -> str:
    """Drop every tag and keep the text, using only the standard library.

    The fallback for when Markdown conversion fails. Uses
    :class:`html.parser.HTMLParser`, which walks the document iteratively and
    tolerates unclosed tags, so it survives the malformed input that defeats a
    tree-based converter.

    Args:
        html: Article HTML, or plain text, or None

    Returns:
        Plain text with entities resolved, empty if there was nothing to strip
    """
    if not html or not html.strip():
        return ""

    stripper = _TagStripper()
    stripper.feed(html)
    stripper.close()
    return _tidy(stripper.text())


def to_markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render rows as a GitHub-flavoured Markdown table.

    Written for tool results an LLM reads, so the layout is the cheap one: no
    column padding, and no leading or trailing pipe on a row. Both are optional
    in GitHub-flavoured Markdown and cost tokens on every line of a listing
    that exists to be small.

    Args:
        headers: Column headings, which also fix the column count
        rows: One sequence of cells per row, each cell whatever
            ``model_dump(mode="json")`` produced for its column - see
            :func:`_cell` for how the non-string ones are flattened. A row
            shorter than ``headers`` is padded with empty cells and a longer one
            is truncated, so a ragged row cannot shift the columns underneath it.

    Returns:
        The table, without a trailing newline. Empty if there are no headers.
    """
    if not headers:
        return ""

    width = len(headers)
    lines = [
        " | ".join(_cell(header) for header in headers),
        " | ".join(["---"] * width),
    ]
    for row in rows:
        cells = [_cell(cell) for cell in row[:width]]
        cells.extend([""] * (width - len(cells)))
        lines.append(" | ".join(cells))

    return "\n".join(lines)


# =============================================================================
# Internals
# =============================================================================


class _TagStripper(HTMLParser):
    """Collect an HTML document's text, discarding its markup."""

    # Text inside these elements is machinery, not prose.
    _SKIP_CONTENT = frozenset({"script", "style", "head", "title", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_CONTENT:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_CONTENT:
            # Clamp rather than trust the markup: a stray </script> with no
            # opening tag would otherwise leave the depth negative and swallow
            # the rest of the document.
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _drop_utm(match: re.Match[str]) -> str:
    """Rebuild one matched URL without its ``utm_*`` query parameters."""
    try:
        parts = urlsplit(match[0])
    except ValueError:  # a malformed netloc, e.g. an unclosed IPv6 bracket
        return match[0]
    kept = (p for p in parts.query.split("&") if not p.startswith("utm_"))
    return urlunsplit(parts._replace(query="&".join(kept)))


def _tidy(text: str) -> str:
    """Normalise whitespace, strip non-printing characters and UTM parameters.

    Trailing spaces go even though two of them are Markdown's hard line break:
    the newline they decorate already conveys the break to a reader, and every
    other trailing space in syndicated HTML is noise.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(_NBSP, " ")
    text = _ZERO_WIDTH.sub("", text)
    text = _TRAILING_SPACE.sub("", text)
    text = _EXTRA_BLANK_LINES.sub("\n\n", text)
    return strip_utm(text).strip()


def _cell(value: object) -> str:
    """Flatten one value into something a Markdown table row can hold.

    Takes a column straight out of ``model_dump(mode="json")``, so a listing
    reports the same values whichever form it is rendered in: a list of labels
    joins into one cell, a bool keeps its JSON spelling rather than Python's
    capitalised one, and a field that is absent or None is simply blank.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return ", ".join(_cell(item) for item in value)
    return _CELL_BREAKERS.sub(" ", str(value)).strip()
