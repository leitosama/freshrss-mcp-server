"""Build links back into the FreshRSS web UI.

FreshRSS's Google Reader API reports article IDs as
``tag:google.com,2005:reader/item/00065a0a9a6c0360`` -- the entry's internal
integer ID rendered as 16-digit zero-padded hex by ``FreshRSS_Entry::dec2hex()``.
The web UI's ``e:`` search operator only accepts *decimal* IDs (its parser is
``/\\be:(?P<search>[0-9,]*)/``), so linking to an article means converting the
hex form back to decimal first.
"""

from collections.abc import Sequence

GREADER_ITEM_PREFIX = "tag:google.com,2005:reader/item/"

# FreshRSS_Entry::STATE_READ | STATE_NOT_READ. This is required, not cosmetic:
# without an explicit state the view falls back to the user's default_state,
# which is usually unread-only, so a link to an already-read article would land
# on an empty list.
STATE_ALL = 3

# Keep generated URLs comfortably below the ~2000 character limit that older
# browsers and some reverse proxies enforce. Each ID costs ~17 characters.
MAX_IDS_PER_URL = 100


class ArticleIdError(ValueError):
    """Raised when an article ID cannot be converted to a FreshRSS entry ID."""


def to_entry_id(article_id: str) -> str:
    """Convert an article ID to the decimal entry ID used by FreshRSS ``e:`` search.

    Accepts all three forms this codebase can produce:

    - ``tag:google.com,2005:reader/item/00065a0a9a6c0360`` (``stream/contents``)
    - ``00065a0a9a6c0360`` (bare Google Reader short form)
    - ``1787851447206752`` (decimal, as returned by ``stream/items/ids``)

    The last two are both 16 characters wide, so they are told apart by their
    leading digit: the short form is zero-padded to ``%016x`` while a real
    decimal entry ID never starts with ``0``.

    Args:
        article_id: Article ID in any of the forms above

    Returns:
        The entry ID as a decimal string

    Raises:
        ArticleIdError: If the ID cannot be parsed as a positive entry ID
    """
    raw = article_id.strip()

    if raw.startswith(GREADER_ITEM_PREFIX):
        # Always hex: FreshRSS builds this form with sprintf('%016x').
        return _from_hex(raw[len(GREADER_ITEM_PREFIX) :], article_id)

    if raw.isdigit() and not raw.startswith("0"):
        return _as_positive(int(raw), article_id)

    return _from_hex(raw, article_id)


def _from_hex(value: str, original: str) -> str:
    """Parse a hexadecimal entry ID, reporting failures against the original input."""
    try:
        return _as_positive(int(value, 16), original)
    except ValueError as e:
        raise ArticleIdError(f"Not a valid article ID: {original!r}") from e


def _as_positive(entry_id: int, original: str) -> str:
    """Reject IDs that are not positive integers, as every FreshRSS entry ID is."""
    if entry_id <= 0:
        raise ArticleIdError(f"Not a valid article ID: {original!r}")
    return str(entry_id)


def build_article_url(web_url: str, entry_ids: Sequence[str]) -> str:
    """Build a single FreshRSS URL showing the given entries.

    Args:
        web_url: Root URL of the FreshRSS web UI, without a trailing slash
        entry_ids: Decimal entry IDs, as returned by :func:`to_entry_id`

    Returns:
        URL opening the FreshRSS reading view filtered to those entries
    """
    # Entry IDs are digits only, so the query string needs no escaping.
    return f"{web_url}/i/?a=normal&state={STATE_ALL}&search=e:{','.join(entry_ids)}"


def build_article_urls(
    web_url: str,
    entry_ids: Sequence[str],
    chunk_size: int = MAX_IDS_PER_URL,
) -> list[str]:
    """Build FreshRSS URLs covering the given entries, splitting oversized batches.

    Args:
        web_url: Root URL of the FreshRSS web UI, without a trailing slash
        entry_ids: Decimal entry IDs, as returned by :func:`to_entry_id`
        chunk_size: Maximum number of entry IDs per URL

    Returns:
        List of URLs, usually one. Empty if no entry IDs were given.
    """
    return [
        build_article_url(web_url, entry_ids[i : i + chunk_size])
        for i in range(0, len(entry_ids), chunk_size)
    ]
