"""Article-related MCP tools for FreshRSS."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from freshrss_mcp_server.api.client import FreshRSSClient
from freshrss_mcp_server.api.models import Article, ArticleResponse, SubscriptionResponse
from freshrss_mcp_server.config import get_settings
from freshrss_mcp_server.exceptions import APIError, FreshRSSError
from freshrss_mcp_server.links import (
    ArticleIdError,
    build_article_url,
    build_article_urls,
    to_entry_id,
)

logger = logging.getLogger(__name__)


async def get_unread_articles(
    client: FreshRSSClient,
    limit: int = 100,
    feed_id: str | None = None,
    max_age_minutes: float | None = None,
    label: str | None = None,
    include_content: bool = True,
) -> list[dict[str, Any]]:
    """Fetch unread articles from FreshRSS.

    Args:
        client: FreshRSS API client
        limit: Maximum number of articles to return (default: 100)
        feed_id: Optional feed ID to filter articles by specific subscription
        max_age_minutes: Only return articles published within this many minutes
            of now (e.g. 30 for "last 30 minutes", 1440 for "last 24h")
        label: Optional user label (tag) name to filter by, e.g. "news".
            Mutually exclusive with feed_id.
        include_content: Include each article's summary text (default: True).
            Pass False for a titles-and-metadata listing; labels, tags and links
            still come back, so a caller can triage first and fetch the text of
            the few articles it wants with a single get_article_content call.

    Returns:
        List of articles with id, title, summary as Markdown (unless
        include_content is False), link, published, feed_title, feed_id, labels,
        tags, starred, and freshrss_url (link to the article in the FreshRSS web
        UI)
    """
    if feed_id and label:
        return [
            {
                "error": True,
                "message": (
                    "Pass either feed_id or label, not both - the FreshRSS API "
                    "reads one stream per request."
                ),
                "code": "INVALID_ARGS",
            }
        ]

    since = (
        datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        if max_age_minutes is not None
        else None
    )
    web_url = get_settings().freshrss_web_url
    try:
        articles = await client.get_unread_articles(
            limit=limit, feed_id=feed_id, since=since, label=label
        )
        return [
            ArticleResponse.from_article(
                article, web_url, include_content=include_content
            ).to_dict()
            for article in articles
        ]
    except ValueError as e:
        logger.error("Invalid arguments for get_unread_articles: %s", e)
        return [{"error": True, "message": str(e), "code": "INVALID_ARGS"}]
    except APIError as e:
        logger.error("Failed to get unread articles: %s", e)
        return [{"error": True, "message": str(e), "code": "API_ERROR"}]
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return [{"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}]


async def get_article_content(
    client: FreshRSSClient,
    article_ids: list[str],
) -> dict[str, Any]:
    """Get the full text of one or more articles by ID.

    Reaches any article still in FreshRSS, read or not, and fetches the whole
    batch in a single request.

    Args:
        client: FreshRSS API client
        article_ids: Article IDs to fetch, in any form to_entry_id accepts

    Returns:
        articles, in the order they were asked for, each with id, title,
        summary as Markdown, link, published, feed_title, feed_id, labels,
        tags, starred and freshrss_url; not_found for IDs no article exists
        for; and invalid_ids for IDs that could not be parsed
    """
    if not article_ids:
        return {"articles": [], "not_found": [], "invalid_ids": []}

    # Normalize to decimal entry IDs: the caller may use any of the three ID
    # forms while the API always answers in the long "tag:..." one, so the two
    # sides only line up once both are converted. The dict also collapses
    # duplicate requests while keeping first-seen order, which is the order the
    # response is built around.
    requested: dict[str, str] = {}  # entry ID -> the ID as the caller spelled it
    invalid_ids: list[str] = []

    for article_id in article_ids:
        try:
            entry_id = to_entry_id(article_id)
        except ArticleIdError:
            # Report unusable IDs alongside the ones that worked, so a single
            # bad ID does not cost the caller every other article.
            logger.warning("Skipping unparseable article ID: %s", article_id)
            invalid_ids.append(article_id)
            continue
        requested.setdefault(entry_id, article_id)

    if not requested:
        return {"articles": [], "not_found": [], "invalid_ids": invalid_ids}

    web_url = get_settings().freshrss_web_url
    try:
        # Decimal IDs go on the wire: FreshRSS takes them as they are, and they
        # are the shortest of the three forms.
        fetched = await client.get_articles_by_ids(list(requested))
    except APIError as e:
        logger.error("Failed to get article content: %s", e)
        return {"error": True, "message": str(e), "code": "API_ERROR"}
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return {"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}

    # The endpoint answers in date order and drops IDs it does not know, so pair
    # the two lists up by entry ID rather than by position.
    by_entry_id: dict[str, Article] = {}
    for article in fetched:
        try:
            by_entry_id[to_entry_id(article.id)] = article
        except ArticleIdError:
            # FreshRSS builds these itself, so this should not happen.
            logger.warning("API returned an unparseable article ID: %s", article.id)

    articles: list[dict[str, Any]] = []
    not_found: list[str] = []

    for entry_id, original_id in requested.items():
        article = by_entry_id.get(entry_id)
        if article is None:
            # A missing article is partial success, not a failed call: in a
            # batch, one dead ID must not cost the caller every other article.
            not_found.append(original_id)
        else:
            articles.append(ArticleResponse.from_article(article, web_url).to_dict())

    return {"articles": articles, "not_found": not_found, "invalid_ids": invalid_ids}


def get_article_links(article_ids: list[str]) -> dict[str, Any]:
    """Build links to articles in the FreshRSS web UI.

    Does no network I/O: article IDs carry the FreshRSS entry ID, so the links
    are built by converting them from hex to decimal locally.

    Args:
        article_ids: Article IDs, in either the "tag:google.com,2005:reader/item/..."
            form or the plain numeric form

    Returns:
        base_url, batch_urls (one page showing every article, split across
        several URLs only if the batch is large), links (per-article entry_id
        and url), and invalid_ids for any IDs that could not be converted
    """
    web_url = get_settings().freshrss_web_url

    links: list[dict[str, str]] = []
    entry_ids: list[str] = []
    invalid_ids: list[str] = []

    for article_id in article_ids:
        try:
            entry_id = to_entry_id(article_id)
        except ArticleIdError:
            # Report unusable IDs alongside the ones that worked, so a single
            # bad ID does not cost the caller every other link.
            logger.warning("Skipping unparseable article ID: %s", article_id)
            invalid_ids.append(article_id)
            continue

        entry_ids.append(entry_id)
        links.append(
            {
                "article_id": article_id,
                "entry_id": entry_id,
                "url": build_article_url(web_url, [entry_id]),
            }
        )

    return {
        "base_url": web_url,
        "batch_urls": build_article_urls(web_url, entry_ids),
        "links": links,
        "invalid_ids": invalid_ids,
    }


async def mark_as_read(
    client: FreshRSSClient,
    article_ids: list[str],
) -> dict[str, Any]:
    """Mark articles as read.

    Args:
        client: FreshRSS API client
        article_ids: List of article IDs to mark as read

    Returns:
        Operation result with success status and count of articles marked
    """
    if not article_ids:
        return {"success": True, "marked_count": 0, "message": "No articles to mark"}

    try:
        success = await client.mark_as_read(article_ids)
        if success:
            return {
                "success": True,
                "marked_count": len(article_ids),
                "message": f"Successfully marked {len(article_ids)} article(s) as read",
            }
        else:
            return {
                "success": False,
                "marked_count": 0,
                "message": "Failed to mark articles as read",
            }
    except APIError as e:
        logger.error("Failed to mark articles as read: %s", e)
        return {"error": True, "message": str(e), "code": "API_ERROR"}
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return {"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}


async def get_subscriptions(
    client: FreshRSSClient,
) -> list[dict[str, Any]]:
    """Get all RSS feed subscriptions with unread counts.

    Args:
        client: FreshRSS API client

    Returns:
        List of subscriptions with id, title, url, unread_count, category
    """
    try:
        subscriptions = await client.get_subscriptions()
        unread_counts = await client.get_unread_counts()

        return [
            SubscriptionResponse.from_subscription(
                sub, unread_count=unread_counts.get(sub.id, 0)
            ).model_dump(mode="json")
            for sub in subscriptions
        ]
    except APIError as e:
        logger.error("Failed to get subscriptions: %s", e)
        return [{"error": True, "message": str(e), "code": "API_ERROR"}]
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return [{"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}]
