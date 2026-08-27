"""Full article fetcher with fallback to dynamic rendering."""

import logging
from typing import Any

import httpx
import trafilatura

from freshrss_mcp_server.config import get_settings
from freshrss_mcp_server.tools import browser

logger = logging.getLogger(__name__)


async def _fetch_static(url: str, timeout: int) -> str:
    """Fetch HTML using httpx (static, no JS execution).

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds

    Returns:
        HTML content as string

    Raises:
        httpx.HTTPStatusError: If HTTP request fails
        httpx.RequestError: If request fails
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; FreshRSS-MCP/1.0)",
                "Accept": "text/html,application/xhtml+xml,*/*",
            },
        )
        response.raise_for_status()
        return response.text


def _extract_content(html: str) -> dict[str, Any] | None:
    """Extract article content using trafilatura.

    Args:
        html: Raw HTML content

    Returns:
        Extracted content dict with content, title, author, date,
        or None if extraction fails
    """
    extracted = trafilatura.extract(
        html,
        include_links=True,
        include_images=False,
        include_tables=True,
        output_format="txt",
    )

    if not extracted:
        # Retry with lenient settings
        extracted = trafilatura.extract(
            html,
            include_links=True,
            include_images=False,
            include_tables=True,
            output_format="txt",
            favor_recall=True,
        )

    if not extracted:
        return None

    metadata = trafilatura.extract_metadata(html)

    result: dict[str, Any] = {"content": extracted}
    if metadata:
        if metadata.title:
            result["title"] = metadata.title
        if metadata.author:
            result["author"] = metadata.author
        if metadata.date:
            result["date"] = metadata.date

    return result


async def fetch_full_article(
    url: str,
    force_dynamic: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch full article content from original URL.

    By default, uses fast static fetching (trafilatura).
    If the returned content seems incomplete or contains only
    JavaScript placeholders, call again with force_dynamic=True.

    Args:
        url: The original article URL to fetch
        force_dynamic: Force browser rendering for JS-heavy sites (requires the
            optional "playwright" extra and ENABLE_DYNAMIC_FETCH=true)
        timeout: Request timeout in seconds for static fetch (default: 30).
            Dynamic fetch always uses BROWSER_TIMEOUT instead.

    Returns:
        Extracted article with content, title, author, date, url, and method.
        The 'method' field indicates 'static' or 'dynamic' fetch was used.
    """
    if not url:
        return {"error": True, "message": "URL is required", "code": "INVALID_INPUT"}

    settings = get_settings()
    dynamic_available = settings.enable_dynamic_fetch and browser.is_playwright_available()

    # ========== Dynamic fetch (Playwright, optional extra) ==========
    if force_dynamic:
        if not settings.enable_dynamic_fetch:
            return {
                "error": True,
                "message": (
                    "Dynamic fetch is disabled. Set ENABLE_DYNAMIC_FETCH=true to enable it "
                    "(the optional playwright extra must also be installed)."
                ),
                "code": "DYNAMIC_DISABLED",
            }

        if not browser.is_playwright_available():
            return {
                "error": True,
                "message": f"Playwright is not installed. {browser.INSTALL_HINT}",
                "code": "PLAYWRIGHT_NOT_INSTALLED",
            }

        try:
            html = await browser.fetch_rendered_html(url, timeout=settings.browser_timeout)
            result = _extract_content(html)

            if result:
                result["url"] = url
                result["method"] = "dynamic"
                return result

            return {
                "error": True,
                "message": "Could not extract content after dynamic rendering",
                "code": "EXTRACTION_FAILED",
            }

        except ImportError:
            return {
                "error": True,
                "message": f"Playwright is not installed. {browser.INSTALL_HINT}",
                "code": "PLAYWRIGHT_NOT_INSTALLED",
            }
        except Exception as e:
            message = str(e)
            if "Executable doesn't exist" in message:
                logger.error("Chromium browser missing for %s: %s", url, e)
                return {
                    "error": True,
                    "message": f"Chromium browser is not installed. {browser.INSTALL_HINT}",
                    "code": "BROWSER_NOT_INSTALLED",
                }
            logger.error("Dynamic fetch failed for %s: %s", url, e)
            return {
                "error": True,
                "message": f"Dynamic fetch failed: {e}",
                "code": "DYNAMIC_FETCH_FAILED",
            }

    # ========== Static fetch (trafilatura) ==========
    try:
        html = await _fetch_static(url, timeout)
        result = _extract_content(html)

        if result:
            result["url"] = url
            result["method"] = "static"
            return result

        failure: dict[str, Any] = {
            "error": True,
            "message": "Could not extract content from page",
            "code": "EXTRACTION_FAILED",
        }
        if dynamic_available:
            failure["hint"] = "Try calling with force_dynamic=True for JS-rendered pages"
        return failure

    except httpx.TimeoutException:
        logger.error("Timeout fetching URL: %s", url)
        return {"error": True, "message": f"Timeout fetching URL: {url}", "code": "TIMEOUT"}
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error fetching URL %s: %s", url, e.response.status_code)
        return {
            "error": True,
            "message": f"HTTP error {e.response.status_code}",
            "code": "HTTP_ERROR",
        }
    except httpx.RequestError as e:
        logger.error("Request error fetching URL %s: %s", url, e)
        return {"error": True, "message": f"Request failed: {e}", "code": "REQUEST_ERROR"}
