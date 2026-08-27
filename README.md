# FreshRSS MCP Server

An MCP (Model Context Protocol) server that connects to a self-hosted FreshRSS instance, enabling AI applications to fetch and manage RSS subscription articles.

## Features

- **Fetch Unread Articles**: Get all unread articles from your RSS subscriptions
- **Article Content**: Access full article content with title, summary, link, and publication date
- **Full Article Scraping**: Extract complete article text from original URLs (for summary-only feeds), with optional browser rendering for JS-heavy pages
- **Mark as Read**: Mark articles as read after processing
- **Subscription Management**: View all subscriptions with unread counts

## Installation

### Prerequisites

- Python 3.14+
- [UV](https://docs.astral.sh/uv/) package manager
- A self-hosted [FreshRSS](https://freshrss.org/) instance with API enabled

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/freshrss-mcp-server.git
cd freshrss-mcp-server
```

2. Install dependencies:
```bash
uv sync
```

**Optional: dynamic (JS-rendered) fetch.** By default, `fetch_full_article` only does
static fetching (trafilatura), which covers most feeds. For JS-heavy pages, install the
optional Playwright extra:
```bash
uv sync --extra playwright
uv run playwright install chromium
```
and set `ENABLE_DYNAMIC_FETCH=true` (see Configuration below).

3. Create `.env` file with your FreshRSS credentials:
```bash
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

Create a `.env` file with the following variables:

```bash
# Required: FreshRSS API
FRESHRSS_API_URL=https://your-freshrss-instance/api/greader.php
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_api_password

# Optional: Link building
# Public URL of the FreshRSS web UI. Defaults to FRESHRSS_API_URL without
# "/api/greader.php". Set it when the two differ (e.g. Docker Compose).
FRESHRSS_BASE_URL=https://your-freshrss-instance

# Optional: Request settings
REQUEST_TIMEOUT=30
DEFAULT_ARTICLE_LIMIT=100

# Optional: MCP Server (defaults shown)
MCP_TRANSPORT=sse           # "stdio", "sse", or "streamable-http"
MCP_HOST=::                 # HTTP server host (:: = all interfaces)
MCP_PORT=8080               # HTTP server port

# Optional: Dynamic content fetching (requires the "playwright" extra, see Installation)
ENABLE_DYNAMIC_FETCH=false  # Enable browser rendering for JS-heavy sites
BROWSER_TIMEOUT=30          # Page load timeout in seconds

# Optional: API Authentication (for remote deployments)
API_KEY=your-secret-key     # If set, clients must use Authorization: Bearer <key>

# Optional: Logging
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### FreshRSS API Setup

1. In FreshRSS, go to Settings > Profile
2. Enable "Allow API access"
3. Set an API password (different from your login password)
4. Use this API password in your `.env` file

## Usage

### Transport Modes

The server supports three transport modes:

| Mode | Use Case | Endpoint |
|------|----------|----------|
| **SSE** | Remote deployment (legacy clients) | `/sse` |
| **Streamable HTTP** | Remote deployment (recommended) | `/mcp` |
| **STDIO** | Local (Claude Desktop direct) | N/A |

### Running the Server

**SSE Mode** (default):
```bash
uv run freshrss-mcp
```

**Streamable HTTP Mode** (recommended for new deployments):
```bash
uv run freshrss-mcp --transport streamable-http
```

**STDIO Mode** (for Claude Desktop local):
```bash
uv run freshrss-mcp --transport stdio
```

**CLI Options**:
```
--transport {stdio,sse,streamable-http}  Transport mode (default: sse)
--host HOST              HTTP server host (default: ::)
--port PORT              HTTP server port (default: 8080)
--version                Show version
```

### Health Check

For SSE and Streamable HTTP modes, a health check endpoint is available:

```bash
curl http://localhost:8080/health
# {
#   "status": "healthy",
#   "version": "0.1.0",
#   "transport": "streamable-http",
#   "dynamic_fetch": {"enabled": false, "playwright_installed": false}
# }
```

### API Authentication

When `API_KEY` is set, all MCP endpoints require authentication:

```bash
curl -H "Authorization: Bearer your-secret-key" https://your-server/mcp
```

**Security notes:**
- FreshRSS credentials are server-side secrets - clients never see them
- Clients only need the `API_KEY` to access the MCP server
- Always use HTTPS for public deployments
- The `/health` endpoint does not require authentication

## Claude Desktop Configuration

### Remote Server (Recommended)

For connecting to a deployed server (Railway, Docker, etc.), use `mcp-remote`:

```json
{
  "mcpServers": {
    "freshrss": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://your-server.example.com/mcp",
        "--header", "Authorization: Bearer ${YOUR_API_KEY}"
      ]
    }
  }
}
```

### Local Server (STDIO)

For running the server locally:

```json
{
  "mcpServers": {
    "freshrss": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/freshrss-mcp-server", "freshrss-mcp", "--transport", "stdio"],
      "env": {
        "FRESHRSS_API_URL": "https://your-freshrss-instance/api/greader.php",
        "FRESHRSS_USERNAME": "your_username",
        "FRESHRSS_API_PASSWORD": "your_api_password"
      }
    }
  }
}
```

## Deployment

### Docker Deployment

Using Docker Compose (recommended):

```bash
# Create .env file with your credentials
cat > .env << EOF
FRESHRSS_API_URL=https://your-freshrss/api/greader.php
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_password
API_KEY=your-secret-key
EOF

# Start the service
docker compose up -d

# Check logs
docker compose logs -f
```

Or pull the published image directly:

```bash
docker run -p 8080:8080 \
  -e FRESHRSS_API_URL=https://your-freshrss/api/greader.php \
  -e FRESHRSS_USERNAME=your_username \
  -e FRESHRSS_API_PASSWORD=your_password \
  -e API_KEY=your-secret-key \
  ghcr.io/leitosama/freshrss-mcp-server:latest
```

Or build manually:

```bash
docker build -t freshrss-mcp .
docker run -p 8080:8080 \
  -e FRESHRSS_API_URL=https://your-freshrss/api/greader.php \
  -e FRESHRSS_USERNAME=your_username \
  -e FRESHRSS_API_PASSWORD=your_password \
  -e API_KEY=your-secret-key \
  freshrss-mcp
```

The default Docker image (`Dockerfile`):
- Has no browser installed — dynamic fetch is unavailable (`ENABLE_DYNAMIC_FETCH=false`)
- Health check configuration
- Streamable HTTP as default transport
- Is the only variant published to `ghcr.io/leitosama/freshrss-mcp-server`

### Dynamic fetch image (optional, not published)

For dynamic (JS-rendered) fetch, build the Playwright variant yourself — it is not
published, so it always builds from your own checkout:

```bash
docker build -f Dockerfile.playwright -t freshrss-mcp:playwright .
docker run -p 8080:8080 \
  -e FRESHRSS_API_URL=https://your-freshrss/api/greader.php \
  -e FRESHRSS_USERNAME=your_username \
  -e FRESHRSS_API_PASSWORD=your_password \
  freshrss-mcp:playwright
```

With Docker Compose, edit `docker-compose.yml` to set `dockerfile: Dockerfile.playwright`
(commented example already in the file) and `ENABLE_DYNAMIC_FETCH=true` in `.env`, then:

```bash
docker compose up -d --build
```

### Railway Deployment

Railway is ideal if you already have FreshRSS deployed there - services in the same project can communicate via private networking.

**Step 1: Deploy to Railway**

```bash
# In your freshrss-mcp-server directory
railway link  # Link to your existing project
railway up    # Deploy
```

**Step 2: Configure environment variables**

In Railway dashboard, add these variables:

```bash
# Use internal networking if FreshRSS is in same project (faster, no egress cost)
FRESHRSS_API_URL=http://freshrss.railway.internal:80/api/greader.php

# Your FreshRSS credentials
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_api_password

# Recommended settings
MCP_TRANSPORT=streamable-http
ENABLE_DYNAMIC_FETCH=false
API_KEY=your-secret-key
```

Railway builds from `Dockerfile` (the default, no-browser image) by default. Dynamic fetch
isn't available there unless you point Railway at `Dockerfile.playwright` instead (Settings
> Build > Dockerfile Path) and set `ENABLE_DYNAMIC_FETCH=true`.

**Step 3: Generate a public domain**

In Railway dashboard, go to Settings > Networking > Generate Domain.

## Available Tools

### `get_unread_articles`
Fetch unread articles from FreshRSS.

**Parameters:**
- `limit` (optional, default: 100): Maximum number of articles to return
- `feed_id` (optional): Filter by specific feed ID
- `max_age_minutes` (optional): Only return articles published within this many
  minutes of now (e.g. `30` for the last 30 minutes, `1440` for the last 24h)

**Returns:** List of articles with id, title, summary, link, published, feed_title,
and `freshrss_url` (a link that opens the article in the FreshRSS web UI)

### `get_article_content`
Get full content of a specific article.

**Parameters:**
- `article_id`: The article ID to fetch

**Returns:** Article with full content, including `freshrss_url`

### `get_article_links`
Build links that open articles in the FreshRSS web UI. Single articles already
carry a `freshrss_url`, so this is mainly for batches: it returns one URL that
opens every given article together.

**Parameters:**
- `article_ids`: List of article IDs to build links for. Both the long
  `tag:google.com,2005:reader/item/...` form and the plain numeric form work.

**Returns:** `base_url`, `batch_urls` (usually a single URL showing every
article at once), `links` (one url per article), and `invalid_ids` for any IDs
that could not be converted

### `mark_as_read`
Mark articles as read.

**Parameters:**
- `article_ids`: List of article IDs to mark as read

**Returns:** Operation result with success status

### `get_subscriptions`
Get all RSS feed subscriptions with unread counts.

**Returns:** List of subscriptions with id, title, url, unread_count, category

### `fetch_full_article`
Fetch full article content from original URL (for summary-only feeds).

**Parameters:**
- `url`: The original article URL to fetch
- `force_dynamic` (optional, default: false): Use browser rendering for JS-rendered pages.
  Requires the optional `playwright` extra and `ENABLE_DYNAMIC_FETCH=true` (see
  [Dynamic fetch](#dynamic-fetch-optional) below); otherwise returns an error.

**Returns:** Extracted article content with title, text, and method ('static' or 'dynamic')

#### How FreshRSS links are built

FreshRSS's Google Reader API reports article IDs as
`tag:google.com,2005:reader/item/00065a0a9a6c0360` -- the entry's internal ID in
16-digit hex. The web UI's `e:` search operator only accepts decimal IDs, so the
server converts them and builds:

```
{FRESHRSS_BASE_URL}/i/?a=normal&state=3&search=e:<id1>,<id2>,...
```

`state=3` is `STATE_READ | STATE_NOT_READ`. It is required: without it FreshRSS
falls back to your default view state, which is usually unread-only, so a link
to an already-read article would open an empty list.

#### Dynamic fetch (optional)

When `force_dynamic=True` can't be used, `fetch_full_article` returns one of:

| `code` | Meaning |
|---|---|
| `DYNAMIC_DISABLED` | `ENABLE_DYNAMIC_FETCH` is not `true` |
| `PLAYWRIGHT_NOT_INSTALLED` | The `playwright` package isn't installed |
| `BROWSER_NOT_INSTALLED` | Playwright is installed but `playwright install chromium` wasn't run |

The static-fetch error response only includes a `force_dynamic=True` hint when dynamic
fetch is actually usable, so a model won't be steered into retrying a call that's
guaranteed to fail.

## Example Workflow

1. AI calls `get_unread_articles` to fetch unread article list
2. AI analyzes titles and summaries to determine importance
3. For incomplete summaries, AI calls `fetch_full_article` to get full content
4. AI generates summary report for all articles
5. After user reviews, AI calls `mark_as_read` to mark articles as read

## Development

### MCP Inspector (Local Debugging)

Use the MCP Inspector web UI to interactively test and debug the server:

```bash
npx @modelcontextprotocol/inspector uv run python -m freshrss_mcp_server.server
```

### Running Tests

```bash
# Quick API test
uv run python -c "
import asyncio
from freshrss_mcp_server.api.client import FreshRSSClient
from freshrss_mcp_server.config import get_settings

async def test():
    settings = get_settings()
    async with FreshRSSClient(
        settings.freshrss_api_url,
        settings.freshrss_username,
        settings.freshrss_api_password,
    ) as client:
        subs = await client.get_subscriptions()
        print(f'Found {len(subs)} subscriptions')

asyncio.run(test())
"
```

### Linting & Type Checking

```bash
# Format code
ruff format .

# Check for issues
ruff check .

# Type check
uv run ty check .
```

## Tech Stack

- **Python 3.14**
- **UV** - Package manager
- **Ruff** - Linter/Formatter
- **ty** - Type checker
- **MCP SDK** - Model Context Protocol
- **httpx** - Async HTTP client
- **Pydantic** - Data validation
- **trafilatura** - Static article content extraction
- **Playwright** (optional `playwright` extra) - Dynamic content rendering (for JS-heavy sites)

## License

MIT License - see [LICENSE](LICENSE) for details.
