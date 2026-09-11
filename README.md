# FreshRSS MCP Server

An MCP (Model Context Protocol) server that connects to a self-hosted FreshRSS instance, enabling AI applications to fetch and manage RSS subscription articles.

## Features

- **Fetch Unread Articles**: Get all unread articles from your RSS subscriptions
- **Article Content**: Fetch the text of one or many articles by ID in a single
  call, with title, link and publication date - read articles included
- **Markdown Output**: Article text is converted from HTML to Markdown, so tool
  results stay readable and cheap for an LLM to consume
- **Clean Links**: `utm_*` tracking parameters are stripped from article links
  and from URLs inside article text
- **Full Article Scraping**: Extract complete article text from original URLs (for summary-only feeds), via static fetching
- **Mark as Read**: Mark articles as read after processing
- **Subscription Management**: View all subscriptions with unread counts
- **Compact Feed Listing**: A Markdown (or JSON) table of id, title and category,
  so feed names are resolved from one small lookup instead of being repeated
  on every article

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

`fetch_full_article` does static fetching only (httpx + trafilatura); rendering
JS-heavy pages is intentionally out of scope for this server (see
[Available Tools](#fetch_full_article)) — use your own browser-capable tool
against the original URL for those.

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
#   "transport": "streamable-http"
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

The Docker image (`Dockerfile`):
- Health check configuration
- Streamable HTTP as default transport
- Is published to `ghcr.io/leitosama/freshrss-mcp-server`

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
API_KEY=your-secret-key
```

Railway builds from `Dockerfile` by default.

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
- `label` (optional): Filter by user label (tag) name, e.g. `news`. Spell it exactly
  as it appears in FreshRSS - matching is case-sensitive. Mutually exclusive with
  `feed_id`: the FreshRSS API reads one stream per request, so passing both returns
  an `INVALID_ARGS` error.
- `include_content` (optional, default: `true`): Include each article's summary
  text. Set it to `false` to scan a large backlog cheaply - the summaries are by
  far the largest part of the response, and everything else, labels and tags
  included, still comes back. Fetch the text of the articles you picked with
  `get_article_content` afterwards, passing all their IDs in one call, or with
  `fetch_full_article` for feeds that publish only an excerpt.

**Returns:** The listing as text, in one of two shapes.

With `include_content=false`, a Markdown table with the columns `id`, `title`,
`link`, `published`, `feed_id`, `labels`, `tags` and `starred`:

```
id | title | link | published | feed_id | labels | tags | starred
--- | --- | --- | --- | --- | --- | --- | ---
00065b2d06c813f8 | Два человека пострадали при ракетном ударе | https://www.kommersant.ru/doc/8941373 | 2026-09-11T03:44:29Z | 38 | Коммерсантъ, news | Происшествия | false
```

With the summaries included it is a JSON array of objects with those same fields
plus `summary`, the article text as Markdown. A table row ends at its first
newline, so an article body cannot go in a cell - which is why the table is
offered only for the summary-less listing.

`feed_id` is the bare number, exactly as `get_feeds` reports it, and the feed's
title is deliberately not repeated on every article: call `get_feeds` once and
resolve the number against it.

Labels and tags always come back, on every article:

| Field | What it holds |
|---|---|
| `labels` | Names of the FreshRSS labels on the article, taken from the API's `user/-/label/...` categories. The feed's folder is reported the same way, so it appears here too. |
| `tags` | Tags the source feed itself put on the item (the RSS `<category>` entries), which FreshRSS passes through unprefixed. |
| `starred` | Whether the article is a favourite in FreshRSS. |

They cost no extra request: FreshRSS already sends them with every article.

### `get_article_content`
Get the text of one or more articles by ID. The whole list goes to FreshRSS as a
single request, so a digest of 30 articles costs one call rather than 30.

Unlike `get_unread_articles` this addresses articles directly, so it also reaches
articles that are already marked as read, and articles older than the current
unread list.

**Parameters:**
- `article_ids`: List of article IDs to fetch. Both the long
  `tag:google.com,2005:reader/item/...` form and the plain numeric form work.

**Returns:**

| Field | What it holds |
|---|---|
| `articles` | The articles found, **in the order requested**, each carrying the same fields `get_unread_articles` reports: the text is in `summary`, as Markdown, alongside `feed_id`, `labels`, `tags` and `starred` |
| `not_found` | IDs that parsed fine but have no article behind them in FreshRSS |
| `invalid_ids` | IDs that could not be parsed at all |

A missing article is partial success, not a failed call: one dead ID never costs
you the rest of the batch.

### `get_article_links`
Build links that open articles in the FreshRSS web UI, for one article or a
whole batch at once - it returns one URL that opens every given article
together.

**Parameters:**
- `article_ids`: List of article IDs to build links for. Both the long
  `tag:google.com,2005:reader/item/...` form and the plain numeric form work.

**Returns:** `base_url`, `batch_urls` (usually a single URL showing every
article at once), `links` (one url per article), and `invalid_ids` for any IDs
that could not be converted

### `mark_as_read`
Mark articles as read. Batched as well: the whole list goes out as one request,
so marking 50 articles costs one call.

**Parameters:**
- `article_ids`: List of article IDs to mark as read, all in one call

**Returns:** Operation result with success status

### `get_feeds`
List every feed as `id`, `title` and `category` - the lookup table for the
`feed_id` that articles carry.

Fetch it once and resolve feed names locally rather than asking for a feed title
alongside every article: on a large batch the repeated titles cost far more than
this whole listing. One row per feed, whether it has unread articles or not, in
the order FreshRSS reports them, which is grouped by category.

**Parameters:**
- `format` (optional, default: `markdown`): `markdown` for a Markdown table, or
  `json` for the same rows as a JSON array of objects. Markdown is the smaller
  of the two - the column names are not repeated on every row.

**Returns:** The listing as text. For example:

```
id | title | category
--- | --- | ---
25 | "Коммерсантъ". В мире | Коммерсантъ
38 | "Коммерсантъ". Происшествия | Коммерсантъ
19 | Хабр: Новости | tech_media
```

The `id` is the bare number, which is exactly what every article's own `feed_id`
holds, so the two match directly with no unwrapping. `get_unread_articles` also
accepts it as `feed/25` when filtering.

Use `get_subscriptions` instead when you need a feed's URL or unread count.

### `get_subscriptions`
Get all RSS feed subscriptions with unread counts.

**Returns:** List of subscriptions with id, title, url, unread_count, category

### `fetch_full_article`
Fetch full article content from original URL (for summary-only feeds). Static
fetching only (httpx + trafilatura) — no JavaScript execution. Rendering
JS-heavy pages is intentionally out of scope for this server; use your own
browser-capable tool against the original URL for those.

**Parameters:**
- `url`: The original article URL to fetch

**Returns:** Extracted article content as Markdown, with title, author, date
and method (always 'static')

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

## Example Workflow

0. For a session that will touch many articles, AI calls `get_feeds` once and keeps
   the table, so each article only needs its bare `feed_id` to resolve a feed name
1. AI calls `get_unread_articles` to fetch unread article list
   - To build a digest of one label, pass `label` (e.g. `get_unread_articles(label="news")`)
   - For a large backlog, pass `include_content=false` first: titles, labels and
     tags are enough to decide what is worth reading, and that pass comes back as
     a compact Markdown table
2. AI analyzes titles, labels/tags and summaries to determine importance
   - Summaries arrive as Markdown, so links, lists and tables are readable as-is
3. AI calls `get_article_content` once, with the IDs of every article it picked,
   to read them in a single request
4. For incomplete summaries, AI calls `fetch_full_article` to get full content
5. AI generates summary report for all articles
6. After user reviews, AI calls `mark_as_read` to mark articles as read, again
   passing every ID in one call

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
- **markdownify** - HTML to Markdown conversion for feed summaries

## License

MIT License - see [LICENSE](LICENSE) for details.
