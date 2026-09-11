"""FreshRSS MCP Server - Main entry point."""

import argparse
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from freshrss_mcp_server import __version__
from freshrss_mcp_server.api.client import FreshRSSClient
from freshrss_mcp_server.config import get_settings
from freshrss_mcp_server.tools import articles, fetcher

# Logger will be configured in main() based on settings
logger = logging.getLogger("freshrss-mcp")


def _configure_logging(level: str) -> None:
    """Configure logging with the specified level."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )


# Global client instance (initialized lazily)
_client: FreshRSSClient | None = None


async def get_client() -> FreshRSSClient:
    """Get or create FreshRSS API client.

    Returns:
        Initialized FreshRSSClient instance.
    """
    global _client
    if _client is None:
        settings = get_settings()
        _client = FreshRSSClient(
            api_url=settings.freshrss_api_url,
            username=settings.freshrss_username,
            password=settings.freshrss_api_password,
            timeout=settings.request_timeout,
        )
        logger.info("FreshRSS client initialized for %s", settings.freshrss_api_url)
    return _client


_FETCH_FULL_ARTICLE_DESCRIPTION = """Fetch full article content from original URL.

Use this tool when an RSS feed only provides a summary and you need
the complete article text. It extracts the main content from the webpage
using static fetching (no JavaScript execution) and returns it as Markdown,
so headings, lists, tables and links stay intact.

If the returned content seems incomplete (e.g., just "Loading..." or
JavaScript placeholders), this server cannot render the page - retry
with your own browser-capable tool against the original URL instead.

Args:
    url: The original article URL to fetch

Returns:
    Extracted article content as Markdown, with title, author, date, and
    method. The 'method' field is always 'static'.
"""


def create_server(host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """Create and configure the MCP server with all tools.

    Args:
        host: Host to bind for HTTP mode
        port: Port for HTTP mode

    Returns:
        Configured FastMCP server instance
    """
    server = FastMCP("freshrss", host=host, port=port)

    # Register all tools.

    # structured_output=False: FastMCP would otherwise wrap a str return in a
    # {"result": ...} model and send the listing twice, once as text and once as
    # structured content. A tool whose whole purpose is a smaller response can
    # not afford to pay for its rows twice.
    @server.tool(structured_output=False)
    async def get_unread_articles(
        limit: int = 100,
        feed_id: str | None = None,
        max_age_minutes: float | None = None,
        label: str | None = None,
        include_content: bool = True,
    ) -> str:
        """Fetch unread articles from FreshRSS.

        Use this tool to get a list of unread articles from your RSS subscriptions.
        Every article comes back with its title, link, publication date, feed_id,
        and the labels and tags it carries in FreshRSS; the summary text is
        included unless you turn it off with include_content. Summaries are
        converted from the feed's HTML to Markdown, so links, lists and tables
        survive as readable text.

        The shape follows include_content. With include_content=False you get a
        Markdown table, one row per article, which is the cheapest way to see a
        backlog; with the summaries included you get a JSON array instead, since
        an article body cannot fit in a table row.

        Articles carry feed_id but not the feed's title - call get_feeds once and
        resolve the number locally, instead of paying for a repeated title on
        every article.

        Args:
            limit: Maximum number of articles to return (default: 100)
            feed_id: Optional feed ID to filter articles by specific subscription
            max_age_minutes: Only return articles published within this many minutes
                of now. Use this for requests like "articles from the last 30
                minutes" (max_age_minutes=30) or "last 24h" (max_age_minutes=1440).
            label: Optional user label (tag) name to filter by, e.g. "news". Use
                this for requests scoped to a label, such as building a digest of
                everything tagged "news". Spell the label exactly as it appears in
                FreshRSS - matching is case-sensitive, and an unknown label simply
                yields no articles. Mutually exclusive with feed_id: the FreshRSS
                API reads one stream per request, so passing both is an error.
            include_content: Whether to include each article's summary text
                (default: True). Set it to False when you only need to see what
                is there - scanning a large backlog, counting what arrived, or
                picking a few articles to read - since the summaries dominate the
                response size. Titles, labels, tags and links still come back,
                so you can then read just the articles you chose with a single
                get_article_content call, passing all their IDs at once.

        Returns:
            The listing as text. With include_content=False, a Markdown table
            with the columns id, title, link, published, feed_id, labels
            (FreshRSS labels, including the feed's folder), tags (tags the source
            feed put on the article) and starred. Otherwise a JSON array of
            objects with those same fields plus summary, the article text as
            Markdown.
        """
        client = await get_client()
        return await articles.get_unread_articles(
            client,
            limit=limit,
            feed_id=feed_id,
            max_age_minutes=max_age_minutes,
            label=label,
            include_content=include_content,
        )

    @server.tool()
    async def get_article_content(article_ids: list[str]) -> dict[str, Any]:
        """Get the full text of articles, by ID, in one batched call.

        Pass EVERY article you need in a single call. The whole list goes to
        FreshRSS as one request, so a digest of 30 articles costs one tool
        call, not 30. Calling this once per article is the wrong shape: it is
        far slower for the user and buys nothing.

        The usual flow is two calls: get_unread_articles(include_content=False)
        to see cheaply what is there, then one call here with the IDs of every
        article you picked. Unlike get_unread_articles this addresses articles
        directly, so it also reaches articles that are already marked as read,
        and articles older than the current unread list.

        The text comes back as Markdown in the 'summary' field, carrying the
        same fields get_unread_articles reports, and in the order you asked for.
        Unknown IDs cost you nothing: they come back listed in not_found while
        every other article still arrives. For feeds that publish only a short
        excerpt, follow up with fetch_full_article on the article's link.

        Args:
            article_ids: Article IDs to fetch (from get_unread_articles). Both
                the long "tag:google.com,2005:reader/item/..." form and the
                plain numeric form work.

        Returns:
            articles (each with id, title, summary as Markdown, link,
            published, feed_id, labels, tags and starred, in the order
            requested), not_found for IDs no article exists for, and
            invalid_ids for IDs that could not be parsed
        """
        client = await get_client()
        return await articles.get_article_content(client, article_ids=article_ids)

    @server.tool()
    async def get_article_links(article_ids: list[str]) -> dict[str, Any]:
        """Build links that open articles in the FreshRSS web UI.

        Use this to give the user one clickable link that opens a whole batch of
        articles together in FreshRSS - for example every article you just
        summarized.

        Article IDs come from get_unread_articles. Both the long
        "tag:google.com,2005:reader/item/..." form and the plain numeric form
        are accepted.

        Args:
            article_ids: List of article IDs to build links for

        Returns:
            base_url, batch_urls (usually a single URL showing every article at
            once), links (one url per article), and invalid_ids for any IDs that
            could not be converted
        """
        return articles.get_article_links(article_ids=article_ids)

    @server.tool()
    async def mark_as_read(article_ids: list[str]) -> dict[str, Any]:
        """Mark articles as read in FreshRSS.

        Use this tool after processing articles to mark them as read.
        This helps keep track of which articles have been reviewed.

        Pass every article ID in one call: the whole batch goes to FreshRSS as
        a single request, so marking 50 articles costs one tool call, not 50.

        Args:
            article_ids: List of article IDs to mark as read, all in one call

        Returns:
            Operation result with success status and count of articles marked
        """
        client = await get_client()
        return await articles.mark_as_read(client, article_ids=article_ids)

    # structured_output=False for the same reason as get_unread_articles above.
    @server.tool(structured_output=False)
    async def get_feeds(format: str = "markdown") -> str:
        """List every feed as id, title and category.

        This is the lookup table for the feed_id that articles carry. Fetch it
        once per conversation, then resolve feed_id locally instead of asking
        for feed titles alongside every article - on a large batch the repeated
        titles cost far more than this whole listing does.

        One row per feed, whether it has unread articles or not, in the order
        FreshRSS reports them, which is grouped by category. The id is the bare
        number ("25"), which is exactly what every article's own feed_id holds,
        so the two match directly; get_unread_articles also takes it as
        "feed/25".

        Use get_subscriptions instead when you actually need a feed's URL or its
        unread count.

        Args:
            format: "markdown" (default) for a Markdown table with id, title and
                category columns, or "json" for the same rows as a JSON array of
                objects. Prefer markdown - it is the smaller of the two.

        Returns:
            The feed listing as text, in the requested format
        """
        client = await get_client()
        return await articles.get_feeds(client, format=format)

    @server.tool()
    async def get_subscriptions() -> list[dict[str, Any]]:
        """Get all RSS feed subscriptions with unread counts.

        Use this tool to see all your RSS subscriptions and how many
        unread articles each feed has.

        Returns:
            List of subscriptions with id, title, url, unread_count, category
        """
        client = await get_client()
        return await articles.get_subscriptions(client)

    @server.tool(description=_FETCH_FULL_ARTICLE_DESCRIPTION)
    async def fetch_full_article(url: str) -> dict[str, Any]:
        app_settings = get_settings()
        return await fetcher.fetch_full_article(
            url,
            timeout=app_settings.request_timeout,
        )

    return server


# Default server instance for module-level access
mcp = create_server()


# =============================================================================
# Entry Point
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    CLI arguments override environment variable settings.
    """
    # Get defaults from config (environment variables)
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="FreshRSS MCP Server - Connect AI applications to FreshRSS",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"freshrss-mcp {__version__}",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=settings.mcp_transport,
        help=f"Transport mode (default: {settings.mcp_transport}, env: MCP_TRANSPORT)",
    )
    parser.add_argument(
        "--host",
        default=settings.mcp_host,
        help=f"Host to bind HTTP server (default: {settings.mcp_host}, env: MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.mcp_port,
        help=f"Port for HTTP server (default: {settings.mcp_port}, env: MCP_PORT)",
    )
    return parser.parse_args()


def main() -> None:
    """Run the FreshRSS MCP server."""
    args = parse_args()
    settings = get_settings()

    # Configure logging based on settings
    _configure_logging(settings.log_level)

    logger.info("Starting FreshRSS MCP Server v%s", __version__)
    logger.info("Transport: %s", args.transport)
    logger.info("Log level: %s", settings.log_level)

    if args.transport == "stdio":
        # Use default server for STDIO mode
        mcp.run()
    else:
        # HTTP modes (SSE or Streamable HTTP)
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        server = create_server(host=args.host, port=args.port)

        # Get the appropriate Starlette app based on transport mode
        if args.transport == "sse":
            app = server.sse_app()
            mcp_endpoint = "/sse"
        else:
            app = server.streamable_http_app()
            mcp_endpoint = "/mcp"

        # Add health check endpoint
        async def health_check(request: Any) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "healthy",
                    "version": __version__,
                    "transport": args.transport,
                }
            )

        app.routes.append(Route("/health", health_check, methods=["GET"]))

        # Add API key authentication middleware (if API_KEY is set)
        # NOTE: Use pure ASGI middleware instead of BaseHTTPMiddleware
        # because BaseHTTPMiddleware is incompatible with SSE streaming responses
        if settings.api_key:
            from starlette.types import ASGIApp, Receive, Scope, Send

            class AuthMiddleware:
                def __init__(self, app: ASGIApp) -> None:
                    self.app = app

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return

                    # Skip auth for health check endpoint
                    if scope["path"] == "/health":
                        await self.app(scope, receive, send)
                        return

                    # Check Authorization header
                    headers = dict(scope.get("headers", []))
                    auth_header = headers.get(b"authorization", b"").decode()

                    if not auth_header.startswith("Bearer "):
                        response = JSONResponse(
                            {"error": "Missing or invalid Authorization header"},
                            status_code=401,
                        )
                        await response(scope, receive, send)
                        return

                    token = auth_header[7:]  # Remove "Bearer " prefix
                    if token != settings.api_key:
                        response = JSONResponse(
                            {"error": "Invalid API key"},
                            status_code=401,
                        )
                        await response(scope, receive, send)
                        return

                    await self.app(scope, receive, send)

            app.add_middleware(AuthMiddleware)  # type: ignore[arg-type]
            logger.info("API authentication enabled")

        # Add CORS middleware for browser-based clients
        app.add_middleware(
            CORSMiddleware,  # type: ignore[arg-type]
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "mcp-protocol-version",
                "mcp-session-id",
                "Authorization",
                "Content-Type",
            ],
            expose_headers=["mcp-session-id"],
        )

        logger.info("HTTP Server: http://%s:%d", args.host, args.port)
        logger.info("MCP endpoint: http://%s:%d%s", args.host, args.port, mcp_endpoint)
        logger.info("Health check: http://%s:%d/health", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
