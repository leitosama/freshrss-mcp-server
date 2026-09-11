# FreshRSS MCP Server

## Project Overview

An MCP (Model Context Protocol) Server that connects to a self-hosted FreshRSS instance, enabling AI applications to fetch RSS subscription articles for intelligent summarization.

## Scope

### Output format

Every tool that returns article text returns **Markdown**, never HTML. Feed
summaries are converted with `markdownify` in `content.py`; scraped pages come
straight out of trafilatura's own `output_format="markdown"`, so they are never
converted twice. Raw HTML is deliberately not offered: the consumer is an LLM,
and tag noise dominated both the token count and the readability of results.

Listings are Markdown too, not just article bodies: `get_feeds` and
`get_unread_articles` render their rows with `content.to_markdown_table()`, both
through the one `tools/articles._render_listing()` that differs between them
only in its column tuple. A table is the cheapest shape that still labels its
columns - roughly 40% of the bytes of the equivalent JSON on a real 35-feed
list, because the keys are not repeated on every row.

A table row ends at its first newline, so an article body cannot live in a cell.
`get_unread_articles` therefore renders a table exactly when
`include_content=False` and falls back to a JSON array when the summaries are
included, and its errors follow whichever of the two the call was going to get.
Cells are fed straight from `model_dump(mode="json")`, so `_cell()` is what
flattens a list of labels into `Коммерсантъ, news`, a bool into `false`, and a
missing field into a blank - the table and the JSON form never disagree about a
value.

`content.to_markdown()` never raises - a body that defeats the converter
(tag soup nested a few hundred levels deep raises `RecursionError`) falls back
to `content.strip_tags()`, a stdlib `HTMLParser` stripper, so one malformed
article costs its own formatting rather than the listing it appears in.

### Tracking parameters

`utm_*` parameters are stripped by `content.strip_utm()` from the article's own
link and from every URL inside the text a tool returns.

### Static fetching

`fetch_full_article` is static-only: it fetches HTML with httpx and extracts
content with trafilatura, no JavaScript execution. Rendering JS-heavy pages
(e.g. via a headless browser) is a deliberate non-goal for this server —
that's a capability of the calling agent/harness, not something specific to
FreshRSS. A caller that needs a rendered page should use its own
browser-capable tool (e.g. `WebFetch`) against the article's original URL.
This project previously shipped an optional Playwright-based dynamic-fetch
path; it has been removed.

## Tech Stack

- **Language**: Python 3.14
- **Package Manager**: UV
- **Linter/Formatter**: Ruff (managed as a `uv` dev dependency, see `pyproject.toml`)
- **Type Checker**: ty (dev dependency)
- **MCP SDK**: mcp-python-sdk (mcp[cli] >= 1.25.0)
- **HTTP Client**: httpx (async)
- **Data Validation**: Pydantic + pydantic-settings
- **Article Extraction**: trafilatura (static only, see Scope above)
- **HTML to Markdown**: markdownify (feed summaries, see Scope above)
- **API**: FreshRSS Google Reader compatible API

## Development Guidelines

**IMPORTANT: Transport Compatibility**

This server supports three transport modes. Every code change must be tested against all three:

| Transport | Protocol | Notes |
|-----------|----------|-------|
| **stdio** | Standard I/O | Used by Claude Desktop locally, no HTTP |
| **sse** | Server-Sent Events | HTTP streaming, requires SSE-compatible middleware |
| **streamable-http** | HTTP POST/Response | Standard HTTP, recommended for new deployments |

When modifying HTTP-related code (middleware, routes, etc.):
- `BaseHTTPMiddleware` is **NOT compatible** with SSE streaming - use pure ASGI middleware instead
- Test all three modes before deploying
- SSE mode uses `/sse` endpoint, streamable-http uses `/mcp` endpoint

## Core Features

1. **Fetch Unread Articles**: Get all unread articles from FreshRSS
2. **Article Content**: Return title, content, original link, publish time, feed info
   for one or many articles per call, read or unread
3. **Full Article Scraping**: Scrape full content for summary-only RSS feeds
4. **Mark as Read**: Mark articles as read

## Project Structure

```
src/freshrss_mcp_server/
├── __init__.py            # Package exports
├── server.py              # MCP Server entry point
├── config.py              # Settings management
├── content.py             # HTML -> Markdown conversion, with tag-strip fallback
├── exceptions.py          # Custom exceptions
├── api/
│   ├── __init__.py
│   ├── client.py          # FreshRSS API client
│   └── models.py          # Pydantic data models
└── tools/
    ├── __init__.py
    ├── articles.py        # Article-related tools
    └── fetcher.py         # Full article fetcher (static, trafilatura)

Dockerfile                 # Published image
.github/workflows/         # CI: lint/typecheck, publish image
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_unread_articles` | Fetch unread articles list (optionally filtered by `feed_id` **or** `label`, e.g. `label="news"`). Every article carries its `feed_id`, `labels`, `tags` and `starred` state. `include_content=False` drops the summary text and renders the listing as a Markdown table; with summaries (Markdown) it is a JSON array instead |
| `get_article_content` | Get the text of one **or many** articles by ID, as Markdown, in a single request. Reaches already-read articles, which `get_unread_articles` cannot. Returns `articles` (in the order asked for), `not_found` and `invalid_ids` |
| `fetch_full_article` | Scrape full content from original URL as Markdown (static fetch only, see Scope above) |
| `get_article_links` | Build FreshRSS web UI links for one or many articles |
| `mark_as_read` | Mark articles as read. Batched: the whole list goes out as one request |
| `get_feeds` | Feed lookup table: `id`, `title` and `category` per feed, as a Markdown table (default) or JSON. The companion to the `feed_id` articles carry - fetch it once and resolve feed names locally instead of paying for them per article |
| `get_subscriptions` | Get subscription feeds list, with each feed's URL and unread count. Use `get_feeds` instead when only the id/title/category mapping is needed |

## Environment Variables

```bash
# Required: FreshRSS API
FRESHRSS_API_URL=https://your-freshrss-instance/api/greader.php
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_api_password

# Optional: Link building
FRESHRSS_BASE_URL=       # Public URL of the FreshRSS web UI, used to build article
                         # links. Defaults to FRESHRSS_API_URL without
                         # "/api/greader.php"; set it when the two differ, e.g.
                         # Docker Compose internal hostnames.

# Optional: MCP Server (defaults shown)
MCP_TRANSPORT=sse           # "stdio", "sse", or "streamable-http"
MCP_HOST=::                 # HTTP server host (:: = all interfaces, IPv4+IPv6)
MCP_PORT=8080               # HTTP server port (Railway auto-injects PORT)

# Optional: Logging
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Optional: API Authentication (for public deployments)
API_KEY=                    # If set, requires Authorization: Bearer <key> header
```

## Running the Server

### Transport Modes

The server supports three transport modes:

| Mode | Use Case | Default |
|------|----------|---------|
| **SSE** | Remote/Self-hosted (legacy clients) | ✅ Default (0.0.0.0:8080) |
| **Streamable HTTP** | Remote/Self-hosted (modern clients) | Use `--transport streamable-http` |
| **STDIO** | Local (Claude Desktop) | Use `--transport stdio` |

### HTTP Mode (SSE/Streamable HTTP)

By default, the server starts in SSE mode for remote deployment:

```bash
# Install dependencies
uv sync

# Run with defaults (SSE on 0.0.0.0:8080)
uv run freshrss-mcp

# Or use streamable-http (recommended for new deployments)
uv run freshrss-mcp --transport streamable-http
```

Endpoints:
- **SSE mode**: `/sse` (MCP endpoint), `/health` (health check)
- **Streamable HTTP mode**: `/mcp` (MCP endpoint), `/health` (health check)

### STDIO Mode (Claude Desktop)

For local use with Claude Desktop:

```bash
# Override via CLI
uv run freshrss-mcp --transport stdio

# Or via environment variable
MCP_TRANSPORT=stdio uv run freshrss-mcp
```

### CLI Options

CLI arguments override environment variables:

```bash
uv run freshrss-mcp --help

Options:
  --transport {stdio,sse,streamable-http}  Transport mode (default: sse)
  --host HOST              HTTP server host (default: 0.0.0.0)
  --port PORT              HTTP server port (default: 8080)
  --version                Show version
```

### MCP Client Configuration (Claude Desktop)

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

## Production Features

### Health Check Endpoint

Available at `/health` for SSE and Streamable HTTP modes:

```bash
curl http://localhost:8080/health
# {
#   "status": "healthy",
#   "version": "0.1.0",
#   "transport": "streamable-http"
# }
```

Use for:
- Load balancer health checks
- Kubernetes liveness/readiness probes
- Monitoring systems

### API Authentication

For public deployments, enable simple API key authentication by setting `API_KEY`:

```bash
# Enable authentication
API_KEY=your-secret-key uv run freshrss-mcp --transport streamable-http

# Client requests must include header
curl -H "Authorization: Bearer your-secret-key" http://localhost:8080/mcp
```

**Note**: This is a simple API key authentication, not OAuth 2.1 compliant. For internal/personal use only. The `/health` endpoint does not require authentication.

## Deployment

### Docker Deployment

Using Docker Compose (recommended):

```bash
# Create .env file with your credentials
cat > .env << EOF
FRESHRSS_API_URL=https://your-freshrss/api/greader.php
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_password
EOF

# Start the service
docker compose up -d

# Check logs
docker compose logs -f
```

Or pull the published image:

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

The `Dockerfile` (published to GHCR):
- Health check configuration
- Streamable HTTP as default transport

### Railway Deployment

Railway is ideal if you already have FreshRSS deployed there - services in the same project can communicate via private networking.

**Step 1: Create a new service in your FreshRSS project**

```bash
# In your freshrss-mcp-server directory
railway link  # Link to your existing project
railway up    # Deploy
```

**Step 2: Configure environment variables**

In Railway dashboard, add these variables to the freshrss-mcp service:

```bash
# Use internal networking to connect to FreshRSS (faster, no egress cost)
FRESHRSS_API_URL=http://freshrss.railway.internal:80/api/greader.php

# Your FreshRSS credentials
FRESHRSS_USERNAME=your_username
FRESHRSS_API_PASSWORD=your_api_password

# Recommended settings
MCP_TRANSPORT=streamable-http
API_KEY=your-secret-key  # For public access security
```

> **Note**: Replace `freshrss` in the URL with your actual FreshRSS service name. Check your service name in Railway dashboard.

**Step 3: Generate a public domain**

In Railway dashboard, go to Settings > Networking > Generate Domain.

**Benefits of Railway deployment:**
- **Private networking**: Uses `*.railway.internal` for fast internal communication
- **No egress fees**: Internal traffic is free ($0.10/GB saved on public traffic)
- **Auto-scaling**: Railway handles scaling automatically
- **Health checks**: Configured via `railway.toml`

**Using with MCP clients:**

```json
{
  "mcpServers": {
    "freshrss": {
      "url": "https://your-app.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-key"
      }
    }
  }
}
```

## Development Commands

**IMPORTANT**: Run these commands after every code change.

### Linting & Formatting (Ruff)

Ruff is a managed `dev` dependency (`pyproject.toml`), not a standalone
`uv tool install` — run it through `uv run` so the version matches CI and
`uv.lock` exactly.

```bash
# Check for linting issues
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Check formatting without changes
uv run ruff format --check .
```

### Type Checking (ty)

```bash
# Type check the project
uv run ty check .

# Type check specific directory
uv run ty check src/
```

### All-in-One (run after code changes)

```bash
uv run ruff format . && uv run ruff check --fix . && uv run ty check .
```

This is exactly what `.github/workflows/ci.yml` enforces on every push and
PR (plus `uv lock --check` and an import smoke test) — a clean run here
means CI will be clean too.

### MCP Inspector (Local Debugging)

Use the MCP Inspector web UI to interactively test and debug the server:

```bash
npx @modelcontextprotocol/inspector uv run python -m freshrss_mcp_server.server
```

This opens a browser interface where you can:
- View available tools and their schemas
- Execute tools with custom parameters
- Inspect request/response payloads

### Quick API Test

```bash
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
        articles = await client.get_unread_articles(limit=5)
        print(f'Found {len(articles)} unread articles')

asyncio.run(test())
"
```

## Dependency Maintenance

Dependabot, a CI quality gate, and three security scanners keep this repo
current. Full detail lives in `.github/dependabot.yml` and the workflows
under `.github/workflows/`; this section is the operating summary.

### The Friday/Saturday rhythm

Dependabot opens PRs every **Friday 06:00 UTC** across three ecosystems
(`github-actions`, `docker`, `uv`), grouped so minor+patch land as one PR
per ecosystem. `.github/workflows/ci.yml` (lint, format, type-check,
import smoke test) plus CodeQL/zizmor/OSV-Scanner gate every PR, and
`.github/workflows/dependabot-auto-merge.yml` auto-merges patch/minor
bumps once those checks are green — deliberately timed so that's usually
done before Saturday (the actual dev day for this project). Majors are
never auto-merged and wait for review.

**Expected steady state: zero open Dependabot PRs most Saturdays.** If
there's a backlog, something (CI, a required check, auto-merge itself) is
stuck — check `.github/workflows/dependabot-auto-merge.yml`'s runs before
assuming the bumps themselves are the problem.

### What Dependabot can't see

No scheduled steward runs against these — they only get caught by whoever
(you, or `@claude`) is looking. Check this list occasionally, especially
after a `docker` or `uv` ecosystem bump:

| Thing | Where | Why it's invisible to Dependabot |
|---|---|---|
| `ghcr.io/astral-sh/uv:X.Y.Z` | `COPY --from=` in `Dockerfile` | Dependabot's `docker` ecosystem parses `FROM` lines only. `COPY --from` support is [dependabot-core#12988](https://github.com/dependabot/dependabot-core/pull/12988) — check if it's merged; delete this row once it ships. |
| Python version coherence | `Dockerfile`, `.python-version`, `pyproject.toml` (`requires-python`), `[tool.ruff] target-version` | A `python:*-slim` bump from Dependabot only touches the Docker tag. The other three spots drift unless updated together, by hand. |

### Handling `@claude` on Dependabot PRs

`.github/workflows/claude.yml` responds to an `@claude` mention in a PR or
issue comment/review, or an issue assignment — same as any other
`@claude`-triggered workflow. It is **not** wired to run automatically on
Dependabot PRs; you have to invoke it.

**When to reach for it:**
- A major-version bump that needs judgement.
- The Python version bump specifically — it needs the four-file
  coordinated update above.
- Red CI on a Dependabot PR that needs diagnosing.
- "What actually changed transitively in this `uv.lock` diff?"

**When not to:** patch/minor PRs — auto-merge will take those once CI is
green, so there's usually nothing to do.

Example prompts, left as comments on the PR:

- `@claude this bumps python to 3.15-slim — update .python-version, requires-python and the ruff target-version to match, and confirm the Dockerfile still builds`
- `@claude summarize what changed transitively in uv.lock here and flag anything risky`
- `@claude check what Dependabot can't see: the ghcr.io/astral-sh/uv COPY --from tag, and python version alignment across all 4 files`

**Two things to get right when Claude pushes to a `dependabot/*` branch:**

1. **Include `[dependabot skip]` in the commit message.** Dependabot stops
   rebasing a PR once anyone else pushes to its branch, unless the commit
   message contains `[dependabot skip]` (case-insensitive). Omitting this
   silently breaks that PR's ability to pick up further upstream changes.
2. **Don't push to a PR you expect auto-merge to take.** A push resets
   review state and can race the auto-merge workflow. Reserve `@claude`
   for majors and the Python bump, where auto-merge was never going to
   fire anyway.

## FreshRSS API Reference

API Source: https://github.com/FreshRSS/FreshRSS/blob/edge/p/api/greader.php

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/accounts/ClientLogin` | Login, get Auth token |
| `/reader/api/0/subscription/list` | Get subscription list |
| `/reader/api/0/stream/contents/...` | Get a stream's articles |
| `/reader/api/0/stream/items/contents` | Get articles by ID, in one batch |
| `/reader/api/0/unread-count` | Get unread counts |
| `/reader/api/0/edit-tag` | Mark read/starred |

### Fetching articles by ID

`get_article_content` reads `/reader/api/0/stream/items/contents` rather than
scanning a stream. Its quirks are worth knowing before touching that code path:

- **POST only.** The route is gated on the presence of an `i` parameter, so a
  GET, or a POST with no IDs, falls through to `badRequest()`. The empty-list
  short circuit in `get_articles_by_ids` is required, not an optimization.
- **No action token.** `checkToken()` guards only the endpoints that write
  (`edit-tag`, `rename-tag`, `disable-tag`, `mark-all-as-read`), so this one
  needs the auth header alone - skipping `_ensure_action_token()` saves a full
  round trip per call.
- **Repeated `i=` fields**, form-encoded. FreshRSS re-parses the raw body itself
  because PHP collapses duplicate keys, which is why the body is built with
  `urlencode` on a list of pairs, exactly as `_edit_tag` does.
- **All three ID forms work** - long `tag:...`, bare hex, and decimal - since
  FreshRSS normalizes with `hex2dec(basename(...))` unless the value is all
  digits with no leading zero. The same three forms `links.to_entry_id` handles.
- **Items come back in date order**, not the order they were asked for, and
  **unknown IDs are dropped silently** with no error. Both are why the tool layer
  pairs the response back up against the request by entry ID.
- The response carries **no `continuation`**: the ID list is the page. It is
  otherwise serialized exactly like `stream/contents`, so `StreamContents` parses
  both.
- The body is read with a 1 MiB cap, hence the `MAX_IDS_PER_REQUEST` chunking.

### Article labels and tags

`stream/contents` returns a `categories` list per article, built by
`FreshRSS_Entry::toGReader()`. It mixes three things, which
`Article.labels` / `Article.tags` / `Article.starred` split apart:

- `user/-/label/<name>` - the feed's folder **and** every label on the entry,
  reported identically, so `labels` cannot tell them apart without a second lookup
- `user/-/state/...` - `com.google/read`, `com.google/starred`, and the
  FreshRSS-specific `org.freshrss/main|important|hidden` feed priorities
- a bare `<name>` - a tag the source feed put on the item itself

No request parameter turns these on; they arrive with every article already.

### Feed IDs

FreshRSS addresses a feed as `feed/<numeric id>`, in `subscription/list` and in
every entry's `origin.streamId` alike. Two helpers bridge the two spellings:

- `models.to_feed_id()` strips the prefix, so `get_feeds` reports the bare `25`
- `client.build_feed_stream_id()` puts it back, so `get_unread_articles` takes
  `feed_id` as either `25` or `feed/25`

A non-numeric stream ID is passed through untouched by both, which keeps a
deliberately built stream (a state, a label) from being mangled into `feed/...`.

An article's own `feed_id` is reported in the bare form too:
`ArticleResponse.from_article()` runs `origin.streamId` through `to_feed_id()`,
so a row from `get_unread_articles` and a row from `get_feeds` are string-equal
on the number and match without any unwrapping. The feed's *title* is
deliberately not on the article - `get_feeds` is where that comes from, fetched
once instead of repeated per article.

## Tool output: structured vs unstructured

FastMCP decides this from the return annotation, and the default is expensive:
a tool returning `str` has its value wrapped in a `{"result": ...}` model and
sent **twice**, once as text content and once as `structuredContent`. Measured on
the real subscription list, `get_subscriptions` puts 11.4 KB on the wire for
5.9 KB of JSON.

`get_feeds` and `get_unread_articles` are therefore registered with
`@server.tool(structured_output=False)`, which drops the output schema and sends
one text block - for `get_unread_articles` that holds either the Markdown table
or the JSON array, whichever `include_content` selected. Any future tool whose
point is a small response wants the same treatment; tools whose callers parse
the payload should keep the structured form, which is why `get_article_content`
still does.

## Usage Flow

0. For a session that will touch many articles, AI calls `get_feeds` once and
   keeps the table: articles carry only the bare `feed_id`, and the feed's name
   and category are resolved from that table - by matching the number directly -
   rather than repeated on each article
1. AI calls `get_unread_articles` to fetch unread article list
   - For a digest scoped to one user label, pass `label` (e.g. `label="news"`);
     it is mutually exclusive with `feed_id` and matches the label name exactly
   - For a large backlog, pass `include_content=False` for a first pass: the
     summaries dominate the response, while titles, `labels` and `tags` are
     usually enough to pick what is worth reading, and `get_article_content`
     then fetches the text of the ones picked. That pass comes back as a
     Markdown table, one row per article; with summaries it is a JSON array
2. AI analyzes titles, labels/tags and summaries to determine importance
   - Summaries are already Markdown, so links, lists and tables read directly;
     no HTML unwrapping needed
3. AI calls `get_article_content` **once, with every chosen ID**, to read those
   articles: the batch costs one request, comes back in the order asked for, and
   unlike `get_unread_articles` reaches articles already marked as read
   - IDs nothing exists for come back under `not_found` while every other
     article still arrives, so one dead ID never costs the batch
4. For incomplete summaries, AI calls `fetch_full_article` to get full content
   - If content still appears incomplete (JS placeholders), that's a static-fetch
     limitation by design (see Scope) — retry with the agent's own browser-capable
     tool against the article's original URL instead
5. AI generates summary report for all articles
6. AI calls `get_article_links` to get URL(s) linking the articles back into
   FreshRSS, for the report or for "open all of these in FreshRSS"
7. After user reads, AI calls `mark_as_read` to mark as read, again passing every
   ID in a single call
