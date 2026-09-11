"""Pydantic models for FreshRSS Google Reader API."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from freshrss_mcp_server.content import to_markdown
from freshrss_mcp_server.links import GREADER_ITEM_PREFIX

# =============================================================================
# Google Reader Tag Vocabulary
# =============================================================================

# FreshRSS puts three different kinds of string in an entry's "categories" list
# (see FreshRSS_Entry::toGReader): "user/-/label/<name>" for the feed's folder
# and for every label put on the entry, "user/-/state/..." for read/starred and
# feed priority, and a bare "<name>" for each tag the source feed itself
# attached to the item. The bare form is what tells feed tags apart from
# everything FreshRSS adds, hence SYSTEM_PREFIX.
LABEL_PREFIX = "user/-/label/"
SYSTEM_PREFIX = "user/-/"

STATE_READ = "user/-/state/com.google/read"
STATE_STARRED = "user/-/state/com.google/starred"
STATE_READING_LIST = "user/-/state/com.google/reading-list"


def _unique(values: Iterable[str]) -> list[str]:
    """Drop duplicates while keeping first-seen order.

    A label can legitimately appear twice - a feed sitting in a folder named
    like one of the entry's own labels reports both - and callers should not
    have to care.
    """
    return list(dict.fromkeys(values))


# =============================================================================
# Authentication Models
# =============================================================================


class AuthResponse(BaseModel):
    """Response from ClientLogin endpoint."""

    sid: str = Field(alias="SID")
    lsid: str = Field(alias="LSID")
    auth: str = Field(alias="Auth")


# =============================================================================
# Subscription Models
# =============================================================================


class Category(BaseModel):
    """Feed category/folder."""

    id: str
    label: str


class Subscription(BaseModel):
    """RSS feed subscription."""

    id: str
    title: str
    url: str
    html_url: str = Field(alias="htmlUrl")
    icon_url: str | None = Field(default=None, alias="iconUrl")
    categories: list[Category] = Field(default_factory=list)


class SubscriptionList(BaseModel):
    """List of subscriptions response."""

    subscriptions: list[Subscription]


# =============================================================================
# Article Models
# =============================================================================


class ArticleOrigin(BaseModel):
    """Article source feed info."""

    stream_id: str = Field(alias="streamId")
    title: str
    html_url: str = Field(alias="htmlUrl")


class ArticleSummary(BaseModel):
    """Article summary/content."""

    content: str


class Article(BaseModel):
    """RSS article/item."""

    id: str
    title: str
    published: int  # Unix timestamp
    updated: int | None = None
    canonical: list[dict[str, Any]] = Field(default_factory=list)
    alternate: list[dict[str, Any]] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    summary: ArticleSummary | None = None
    origin: ArticleOrigin | None = None

    @computed_field
    @property
    def link(self) -> str | None:
        """Get article URL from canonical or alternate links."""
        if self.canonical:
            return self.canonical[0].get("href")
        if self.alternate:
            return self.alternate[0].get("href")
        return None

    @computed_field
    @property
    def published_at(self) -> datetime:
        """Get published timestamp as datetime."""
        return datetime.fromtimestamp(self.published, tz=UTC)

    @computed_field
    @property
    def labels(self) -> list[str]:
        """FreshRSS labels on this article, including the feed's folder.

        The API reports the feed's folder and the entry's own labels in the same
        "user/-/label/<name>" form, so both land here and cannot be told apart
        without a second lookup.
        """
        return _unique(
            category[len(LABEL_PREFIX) :]
            for category in self.categories
            if category.startswith(LABEL_PREFIX)
        )

    @computed_field
    @property
    def tags(self) -> list[str]:
        """Tags the source feed put on the item itself.

        FreshRSS appends these unprefixed, which is what separates them from the
        "user/-/..." labels and states it adds on its own.
        """
        return _unique(
            category for category in self.categories if not category.startswith(SYSTEM_PREFIX)
        )

    @computed_field
    @property
    def starred(self) -> bool:
        """Whether the article is starred (a favourite) in FreshRSS."""
        return STATE_STARRED in self.categories


class StreamContents(BaseModel):
    """Response from stream/contents endpoint."""

    id: str
    title: str | None = None
    updated: int | None = None
    items: list[Article] = Field(default_factory=list)
    continuation: str | None = None


# =============================================================================
# Unread Count Models
# =============================================================================


class UnreadCount(BaseModel):
    """Unread count for a feed/category."""

    id: str
    count: int
    newest_item_timestamp_usec: str = Field(alias="newestItemTimestampUsec")


class UnreadCountResponse(BaseModel):
    """Response from unread-count endpoint."""

    max: int
    unreadcounts: list[UnreadCount]


# =============================================================================
# MCP Tool Response Models
# =============================================================================


class ArticleResponse(BaseModel):
    """Simplified article for MCP tool response."""

    id: str
    title: str
    summary: str | None = None  # Markdown, converted from the feed's HTML
    link: str | None
    published: datetime
    feed_title: str
    feed_id: str
    labels: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    starred: bool = False

    @classmethod
    def from_article(
        cls,
        article: Article,
        *,
        include_content: bool = True,
    ) -> ArticleResponse:
        """Create from API Article model.

        Args:
            article: Article from the Google Reader API
            include_content: Keep the article's summary text. Pass False to list
                articles without their bodies, which is much cheaper for a
                caller that only needs to triage titles first.
        """
        summary = (
            (to_markdown(article.summary.content) if article.summary else "")
            if include_content
            else None
        )
        return cls(
            # Drop the "tag:google.com,2005:reader/item/" prefix: it's dead
            # weight on every article, and get_article_content/get_article_links
            # still accept the bare form.
            id=article.id.removeprefix(GREADER_ITEM_PREFIX),
            title=article.title,
            summary=summary,
            link=article.link,
            published=article.published_at,
            feed_title=article.origin.title if article.origin else "",
            feed_id=article.origin.stream_id if article.origin else "",
            labels=article.labels,
            tags=article.tags,
            starred=article.starred,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for an MCP tool response.

        A summary of None means the caller asked for no article text, so the
        field is dropped entirely rather than returned as an empty string that
        would read as "this article has no summary".
        """
        exclude = None if self.summary is not None else {"summary"}
        return self.model_dump(mode="json", exclude=exclude)


class SubscriptionResponse(BaseModel):
    """Simplified subscription for MCP tool response."""

    id: str
    title: str
    url: str
    unread_count: int = 0
    category: str | None = None

    @classmethod
    def from_subscription(
        cls, subscription: Subscription, unread_count: int = 0
    ) -> SubscriptionResponse:
        """Create from API Subscription model."""
        category = subscription.categories[0].label if subscription.categories else None
        return cls(
            id=subscription.id,
            title=subscription.title,
            url=subscription.url,
            unread_count=unread_count,
            category=category,
        )
