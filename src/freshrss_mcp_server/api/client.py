"""FreshRSS Google Reader API client."""

import logging
from datetime import datetime
from types import TracebackType
from urllib.parse import quote, urlencode

import httpx

from freshrss_mcp_server.api.models import (
    FEED_PREFIX,
    LABEL_PREFIX,
    STATE_READ,
    STATE_READING_LIST,
    STATE_STARRED,
    Article,
    StreamContents,
    Subscription,
    SubscriptionList,
    UnreadCountResponse,
)
from freshrss_mcp_server.exceptions import APIError, AuthenticationError

logger = logging.getLogger(__name__)

# The Google Reader tag vocabulary (STATE_*, LABEL_PREFIX) is imported above
# rather than defined here: models.py parses the same strings out of an entry's
# categories, and one spelling of them is enough.

# How many article IDs go into one stream/items/contents request. FreshRSS reads
# the POST body with a 1 MiB cap, but that is not the binding limit -- at ~62
# bytes per URL-encoded ID it would take some 16,000 IDs to reach it. The
# response is, since every article arrives with its body. 100 matches
# links.MAX_IDS_PER_URL and the page size get_unread_articles already uses.
MAX_IDS_PER_REQUEST = 100


def build_label_stream_id(label: str) -> str:
    """Build a Google Reader stream ID for a FreshRSS user label.

    Args:
        label: User label name as shown in FreshRSS (e.g. "news"), or an
            already-built stream ID (e.g. "user/-/label/news")

    Returns:
        Stream ID of the form "user/-/label/<name>".

    Raises:
        ValueError: If the label is empty or whitespace only.
    """
    name = label.strip()
    if not name:
        raise ValueError("Label name must not be empty")
    if name.startswith(LABEL_PREFIX):
        return name
    return f"{LABEL_PREFIX}{name}"


def build_feed_stream_id(feed_id: str) -> str:
    """Build a Google Reader stream ID for a FreshRSS feed.

    Accepts both forms the server itself hands out: the bare number ``get_feeds``
    reports and the ``"feed/25"`` the subscription list and an article's
    ``feed_id`` carry. Either can therefore be pasted straight back in as a
    filter, which is the whole point of the id column in the feed listing.

    Args:
        feed_id: Feed ID as a bare number (e.g. "25") or a stream ID
            (e.g. "feed/25")

    Returns:
        Stream ID of the form "feed/<id>".

    Raises:
        ValueError: If the feed ID is empty or whitespace only.
    """
    name = feed_id.strip()
    if not name:
        raise ValueError("Feed ID must not be empty")
    if name.startswith(FEED_PREFIX):
        return name
    # Only a bare number is a feed ID missing its prefix. Anything else is some
    # other kind of stream the caller built deliberately (a state, a label), and
    # prefixing it would turn a working request into a broken one.
    return f"{FEED_PREFIX}{name}" if name.isdigit() else name


class FreshRSSClient:
    """Async client for FreshRSS Google Reader API."""

    def __init__(
        self,
        api_url: str,
        username: str,
        password: str,
        timeout: int = 30,
    ) -> None:
        """Initialize the FreshRSS client.

        Args:
            api_url: Base URL of FreshRSS API (e.g., https://example.com/api/greader.php)
            username: FreshRSS username
            password: FreshRSS API password
            timeout: Request timeout in seconds
        """
        self.api_url = api_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._auth_token: str | None = None
        self._action_token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> FreshRSSClient:
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client, creating if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    # =========================================================================
    # Authentication
    # =========================================================================

    async def authenticate(self) -> str:
        """Authenticate with FreshRSS and get auth token.

        Returns:
            Auth token string.

        Raises:
            AuthenticationError: If authentication fails.
        """
        client = self._get_client()
        url = f"{self.api_url}/accounts/ClientLogin"

        try:
            response = await client.post(
                url,
                data={
                    "Email": self.username,
                    "Passwd": self.password,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(f"Authentication failed: {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise AuthenticationError(f"Authentication request failed: {e}") from e

        # Parse response: SID=xxx\nLSID=xxx\nAuth=xxx
        auth_data: dict[str, str] = {}
        for line in response.text.strip().split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                auth_data[key] = value

        if "Auth" not in auth_data:
            raise AuthenticationError("Auth token not found in response")

        self._auth_token = auth_data["Auth"]
        logger.info("Successfully authenticated with FreshRSS")
        return self._auth_token

    async def _ensure_authenticated(self) -> None:
        """Ensure client is authenticated, authenticating if needed."""
        if self._auth_token is None:
            await self.authenticate()

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authorization."""
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self._auth_token:
            headers["Authorization"] = f"GoogleLogin auth={self._auth_token}"
        return headers

    async def get_token(self) -> str:
        """Get action token for POST operations.

        Returns:
            Action token string.

        Raises:
            APIError: If token request fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/token"

        try:
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to get token: {e.response.status_code}", e.response.status_code
            ) from e

        self._action_token = response.text.strip()
        return self._action_token

    async def _ensure_action_token(self) -> str:
        """Ensure action token is available and fresh.

        Note: Always fetch a new token because FreshRSS action tokens expire.
        The token expiration time is relatively short, and caching can lead to
        'Invalid POST token' errors in long-running sessions.
        """
        # Always get a fresh token to avoid expiration issues
        await self.get_token()
        return self._action_token  # type: ignore[return-value]

    # =========================================================================
    # Subscriptions
    # =========================================================================

    async def get_subscriptions(self) -> list[Subscription]:
        """Get list of RSS feed subscriptions.

        Returns:
            List of Subscription objects.

        Raises:
            APIError: If request fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/subscription/list"

        try:
            response = await client.get(
                url,
                params={"output": "json"},
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to get subscriptions: {e.response.status_code}",
                e.response.status_code,
            ) from e

        data = response.json()
        subscription_list = SubscriptionList.model_validate(data)
        return subscription_list.subscriptions

    async def get_unread_counts(self) -> dict[str, int]:
        """Get unread article counts per feed.

        Returns:
            Dict mapping feed ID to unread count.

        Raises:
            APIError: If request fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/unread-count"

        try:
            response = await client.get(
                url,
                params={"output": "json"},
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to get unread counts: {e.response.status_code}",
                e.response.status_code,
            ) from e

        data = response.json()
        unread_response = UnreadCountResponse.model_validate(data)
        return {item.id: item.count for item in unread_response.unreadcounts}

    # =========================================================================
    # Articles
    # =========================================================================

    async def get_stream_contents(
        self,
        stream_id: str,
        count: int = 100,
        continuation: str | None = None,
        exclude_target: str | None = None,
        start_time: int | None = None,
        stop_time: int | None = None,
    ) -> StreamContents:
        """Get contents of a stream (feed, category, or state).

        Args:
            stream_id: Stream identifier (feed ID, category, or state tag)
            count: Maximum number of items to return
            continuation: Continuation token for pagination
            exclude_target: State tag to exclude (e.g., read articles)
            start_time: Only return items published at or after this Unix timestamp
            stop_time: Only return items published at or before this Unix timestamp

        Returns:
            StreamContents with articles.

        Raises:
            APIError: If request fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        # URL encode the stream_id
        encoded_stream_id = quote(stream_id, safe="")
        url = f"{self.api_url}/reader/api/0/stream/contents/{encoded_stream_id}"

        params: dict[str, str | int] = {
            "output": "json",
            "n": count,
        }
        if continuation:
            params["c"] = continuation
        if exclude_target:
            params["xt"] = exclude_target
        if start_time is not None:
            params["ot"] = start_time
        if stop_time is not None:
            params["nt"] = stop_time

        try:
            response = await client.get(
                url,
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to get stream contents: {e.response.status_code}",
                e.response.status_code,
            ) from e

        data = response.json()
        return StreamContents.model_validate(data)

    async def get_unread_articles(
        self,
        limit: int = 100,
        feed_id: str | None = None,
        since: datetime | None = None,
        label: str | None = None,
    ) -> list[Article]:
        """Get unread articles.

        Args:
            limit: Maximum number of articles to return
            feed_id: Optional feed ID to filter by
            since: Only return articles published at or after this time
            label: Optional user label name to filter by. Mutually exclusive
                with feed_id -- the API addresses one stream per request.

        Returns:
            List of unread Article objects.

        Raises:
            ValueError: If both feed_id and label are given, or label is empty.
            APIError: If request fails.
        """
        if feed_id and label:
            raise ValueError("Pass either feed_id or label, not both")

        if label:
            stream_id = build_label_stream_id(label)
        elif feed_id:
            stream_id = build_feed_stream_id(feed_id)
        else:
            stream_id = STATE_READING_LIST
        exclude = STATE_READ
        start_time = int(since.timestamp()) if since else None

        articles: list[Article] = []
        continuation: str | None = None

        while len(articles) < limit:
            remaining = limit - len(articles)
            batch_size = min(remaining, 100)  # API typically limits to 100 per request

            stream = await self.get_stream_contents(
                stream_id=stream_id,
                count=batch_size,
                continuation=continuation,
                exclude_target=exclude,
                start_time=start_time,
            )

            articles.extend(stream.items)

            if not stream.continuation or len(stream.items) < batch_size:
                break

            continuation = stream.continuation

        # Belt-and-braces: filter client-side too, in case the server ignores `ot`.
        if since is not None:
            articles = [a for a in articles if a.published_at >= since]

        return articles[:limit]

    async def get_article_ids(
        self,
        stream_id: str,
        count: int = 100,
        exclude_target: str | None = None,
    ) -> list[str]:
        """Get article IDs from a stream.

        Args:
            stream_id: Stream identifier
            count: Maximum number of IDs to return
            exclude_target: State tag to exclude

        Returns:
            List of article ID strings.

        Raises:
            APIError: If request fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/stream/items/ids"

        params: dict[str, str | int] = {
            "output": "json",
            "s": stream_id,
            "n": count,
        }
        if exclude_target:
            params["xt"] = exclude_target

        try:
            response = await client.get(
                url,
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to get article IDs: {e.response.status_code}",
                e.response.status_code,
            ) from e

        data = response.json()
        # Response format: {"itemRefs": [{"id": "..."}, ...]}
        return [item["id"] for item in data.get("itemRefs", [])]

    async def get_articles_by_ids(self, article_ids: list[str]) -> list[Article]:
        """Get articles by ID, whatever their read state.

        Unlike :meth:`get_stream_contents` this addresses entries directly, so
        it also reaches articles that are already read, or older than any
        reasonable page of the reading list.

        FreshRSS normalizes the IDs itself, so the long
        ``tag:google.com,2005:reader/item/<hex>`` form, the bare hex form and
        the decimal form all work and are passed through verbatim.

        Args:
            article_ids: Article IDs, in any form FreshRSS accepts

        Returns:
            Articles for the IDs that exist, in the server's own date order --
            the endpoint ignores the order they were asked for. IDs with no
            article behind them are dropped silently; the endpoint reports no
            error for them, so a caller that needs to know pairs the result
            back up against its request itself.

        Raises:
            APIError: If request fails.
        """
        if not article_ids:
            # Required, not just a saving: the route is gated on the presence of
            # an "i" parameter, and without one the request falls through to
            # FreshRSS's badRequest() handler.
            return []

        await self._ensure_authenticated()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/stream/items/contents"

        articles: list[Article] = []

        for start in range(0, len(article_ids), MAX_IDS_PER_REQUEST):
            chunk = article_ids[start : start + MAX_IDS_PER_REQUEST]

            # Repeated 'i' fields, same shape as _edit_tag: FreshRSS re-parses
            # the raw body itself because PHP collapses duplicate keys, so the
            # duplicates have to survive encoding. No action token here -- that
            # check guards only the endpoints that write.
            encoded_data = urlencode([("i", article_id) for article_id in chunk])

            try:
                response = await client.post(
                    url,
                    content=encoded_data,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise APIError(
                    f"Failed to get articles by ID: {e.response.status_code}",
                    e.response.status_code,
                ) from e

            articles.extend(StreamContents.model_validate(response.json()).items)

        return articles

    # =========================================================================
    # State Management
    # =========================================================================

    async def mark_as_read(self, article_ids: list[str]) -> bool:
        """Mark articles as read.

        Args:
            article_ids: List of article IDs to mark as read

        Returns:
            True if successful.

        Raises:
            APIError: If request fails.
        """
        return await self._edit_tag(article_ids, add_tag=STATE_READ)

    async def mark_as_starred(self, article_ids: list[str]) -> bool:
        """Mark articles as starred.

        Args:
            article_ids: List of article IDs to star

        Returns:
            True if successful.

        Raises:
            APIError: If request fails.
        """
        return await self._edit_tag(article_ids, add_tag=STATE_STARRED)

    async def _edit_tag(
        self,
        article_ids: list[str],
        add_tag: str | None = None,
        remove_tag: str | None = None,
    ) -> bool:
        """Edit tags on articles.

        Args:
            article_ids: List of article IDs
            add_tag: Tag to add
            remove_tag: Tag to remove

        Returns:
            True if successful.

        Raises:
            APIError: If request fails.
        """
        if not article_ids:
            return True

        await self._ensure_authenticated()
        token = await self._ensure_action_token()
        client = self._get_client()
        url = f"{self.api_url}/reader/api/0/edit-tag"

        # Build form data with multiple 'i' parameters for each article ID
        form_data: list[tuple[str, str]] = [("T", token)]
        for article_id in article_ids:
            form_data.append(("i", article_id))
        if add_tag:
            form_data.append(("a", add_tag))
        if remove_tag:
            form_data.append(("r", remove_tag))

        # Use urlencode to explicitly encode form data (handles duplicate keys correctly)
        encoded_data = urlencode(form_data)

        try:
            response = await client.post(
                url,
                content=encoded_data,
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Failed to edit tags: {e.response.status_code}",
                e.response.status_code,
            ) from e

        return response.text.strip() == "OK"
