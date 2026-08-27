"""Article-related MCP tools for FreshRSS."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from freshrss_mcp_server.api.client import FreshRSSClient
from freshrss_mcp_server.api.models import ArticleResponse, SubscriptionResponse, article_web_url
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
) -> list[dict[str, Any]]:
    """Fetch unread articles from FreshRSS.

    Args:
        client: FreshRSS API client
        limit: Maximum number of articles to return (default: 100)
        feed_id: Optional feed ID to filter articles by specific subscription
        max_age_minutes: Only return articles published within this many minutes
            of now (e.g. 30 for "last 30 minutes", 1440 for "last 24h")

    Returns:
        List of articles with id, title, summary, link, published, feed_title, feed_id,
        and freshrss_url (link to the article in the FreshRSS web UI)
    """
    since = (
        datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        if max_age_minutes is not None
        else None
    )
    web_url = get_settings().freshrss_web_url
    try:
        articles = await client.get_unread_articles(limit=limit, feed_id=feed_id, since=since)
        return [
            ArticleResponse.from_article(article, web_url).model_dump(mode="json")
            for article in articles
        ]
    except APIError as e:
        logger.error("Failed to get unread articles: %s", e)
        return [{"error": True, "message": str(e), "code": "API_ERROR"}]
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return [{"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}]


async def get_article_content(
    client: FreshRSSClient,
    article_id: str,
) -> dict[str, Any]:
    """Get full content of a specific article.

    Args:
        client: FreshRSS API client
        article_id: The article ID to fetch

    Returns:
        Article with full content including id, title, content, link, published,
        and freshrss_url (link to the article in the FreshRSS web UI)
    """
    web_url = get_settings().freshrss_web_url
    try:
        # Get the article by fetching stream contents with the specific article
        # The article_id in Google Reader API is like "tag:google.com,2005:reader/item/..."
        stream = await client.get_stream_contents(
            stream_id="user/-/state/com.google/reading-list",
            count=1000,  # Fetch more to find the article
        )

        for article in stream.items:
            if article.id == article_id:
                return {
                    "id": article.id,
                    "title": article.title,
                    "content": article.summary.content if article.summary else "",
                    "link": article.link,
                    "published": article.published_at.isoformat(),
                    "feed_title": article.origin.title if article.origin else "",
                    "feed_id": article.origin.stream_id if article.origin else "",
                    "freshrss_url": article_web_url(article.id, web_url),
                }

        return {"error": True, "message": f"Article not found: {article_id}", "code": "NOT_FOUND"}

    except APIError as e:
        logger.error("Failed to get article content: %s", e)
        return {"error": True, "message": str(e), "code": "API_ERROR"}
    except FreshRSSError as e:
        logger.error("FreshRSS error: %s", e)
        return {"error": True, "message": str(e), "code": "FRESHRSS_ERROR"}


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
