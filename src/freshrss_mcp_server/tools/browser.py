"""Playwright browser wrapper for dynamic content fetching."""

import importlib.util
import logging

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "Install the optional extra: `uv sync --extra playwright && "
    "uv run playwright install chromium`, or use the -playwright Docker image variant."
)

# Lazy-loaded browser instance (singleton)
_playwright = None
_browser = None


def is_playwright_available() -> bool:
    """Check whether the optional playwright package is importable.

    Uses find_spec so this never triggers the actual (heavy) import.
    """
    return importlib.util.find_spec("playwright") is not None


def is_browser_running() -> bool:
    """Whether a browser instance is currently open."""
    return _browser is not None


async def _get_browser():
    """Get or create browser instance (singleton pattern).

    Returns:
        Playwright browser instance.
    """
    global _playwright, _browser

    if _browser is None:
        from playwright.async_api import async_playwright

        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        logger.info("Playwright browser initialized")

    return _browser


async def close_browser() -> None:
    """Close browser and cleanup resources.

    Should be called when the application shuts down.
    """
    global _playwright, _browser

    if _browser:
        await _browser.close()
        _browser = None
        logger.info("Playwright browser closed")

    if _playwright:
        await _playwright.stop()
        _playwright = None


async def fetch_rendered_html(url: str, timeout: int = 30) -> str:
    """Fetch page HTML after JavaScript rendering.

    Uses Playwright to load the page and wait for network idle,
    then returns the fully rendered HTML content.

    Args:
        url: The URL to fetch
        timeout: Maximum wait time in seconds

    Returns:
        Rendered HTML content as string

    Raises:
        PlaywrightError: If page loading fails
    """
    browser = await _get_browser()
    page = await browser.new_page()

    try:
        await page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
        html = await page.content()
        return html
    finally:
        await page.close()
