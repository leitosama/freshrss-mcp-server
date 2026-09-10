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
using static fetching (no JavaScript execution).

If the returned content seems incomplete (e.g., just "Loading..." or
JavaScript placeholders), this server cannot render the page - retry
with your own browser-capable tool against the original URL instead.

Args:
    url: The original article URL to fetch

Returns:
    Extracted article content with title, text, author, date, and method.
    The 'method' field is always 'static'.
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

    # Register all tools
    @server.tool()
    async def get_unread_articles(
        limit: int = 100,
        feed_id: str | None = None,
        max_age_minutes: float | None = None,
        label: str | None = None,
        include_content: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch unread articles from FreshRSS.

        Use this tool to get a list of unread articles from your RSS subscriptions.
        Every article comes back with its title, link, publication date, and the
        labels and tags it carries in FreshRSS; the summary text is included
        unless you turn it off with include_content.

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
                response size. Titles, labels, tags and links still come back, so
                you can then call get_article_content or fetch_full_article for
                just the articles you chose.

        Returns:
            List of articles with id, title, summary (omitted when
            include_content is False), link, published, feed_title, feed_id,
            labels (FreshRSS labels, including the feed's folder), tags (tags the
            source feed put on the article), starred, and freshrss_url (a link
            that opens the article in the FreshRSS web UI)
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
    async def get_article_content(article_id: str) -> dict[str, Any]:
        """Get full content of a specific article.

        Use this tool to retrieve the complete content of a single article
        when you need more details than the summary provides.

        Args:
            article_id: The article ID to fetch (from get_unread_articles)

        Returns:
            Article with full content including id, title, content, link,
            published, labels, tags, starred, and freshrss_url (a link that opens
            the article in the FreshRSS web UI)
        """
        client = await get_client()
        return await articles.get_article_content(client, article_id=article_id)

    @server.tool()
    async def get_article_links(article_ids: list[str]) -> dict[str, Any]:
        """Build links that open articles in the FreshRSS web UI.

        Use this to give the user one clickable link that opens a whole batch of
        articles together in FreshRSS - for example every article you just
        summarized. Single articles already carry a freshrss_url field from
        get_unread_articles and get_article_content, so reach for this tool
        mainly for batches.

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

        Args:
            article_ids: List of article IDs to mark as read

        Returns:
            Operation result with success status and count of articles marked
        """
        client = await get_client()
        return await articles.mark_as_read(client, article_ids=article_ids)

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
