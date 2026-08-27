# FreshRSS MCP Server

## Project Overview

An MCP (Model Context Protocol) Server that connects to a self-hosted FreshRSS instance, enabling AI applications to fetch RSS subscription articles for intelligent summarization.

## Tech Stack

- **Language**: Python 3.14
- **Package Manager**: UV
- **Linter/Formatter**: Ruff (managed as a `uv` dev dependency, see `pyproject.toml`)
- **Type Checker**: ty (dev dependency)
- **MCP SDK**: mcp-python-sdk (mcp[cli] >= 1.25.0)
- **HTTP Client**: httpx (async)
- **Data Validation**: Pydantic + pydantic-settings
- **Article Extraction**: trafilatura (static), Playwright (dynamic, optional)
- **Browser Automation**: Playwright (optional `playwright` extra, disabled by default)
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
2. **Article Content**: Return title, summary/content, original link, publish time, feed info
3. **Full Article Scraping**: Scrape full content for summary-only RSS feeds
4. **Mark as Read**: Mark articles as read

## Project Structure

```
src/freshrss_mcp_server/
├── __init__.py            # Package exports
├── server.py              # MCP Server entry point
├── config.py              # Settings management
├── exceptions.py          # Custom exceptions
├── api/
│   ├── __init__.py
│   ├── client.py          # FreshRSS API client
│   └── models.py          # Pydantic data models
└── tools/
    ├── __init__.py
    ├── articles.py        # Article-related tools
    ├── fetcher.py         # Full article fetcher (static + optional dynamic)
    └── browser.py         # Playwright browser wrapper (lazy import)

Dockerfile                 # Default image: no browser, dynamic fetch unavailable
Dockerfile.playwright      # Optional variant: adds Chromium (not published)
.github/workflows/         # CI: publish default image, build-validate playwright image
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_unread_articles` | Fetch unread articles list |
| `get_article_content` | Get single article content |
| `fetch_full_article` | Scrape full content from original URL (supports `force_dynamic` for JS sites, requires optional Playwright extra) |
| `get_article_links` | Build FreshRSS web UI links for one or many articles |
| `mark_as_read` | Mark articles as read |
| `get_subscriptions` | Get subscription feeds list |

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

# Optional: Dynamic fetch / Playwright (defaults shown; requires the "playwright" extra)
ENABLE_DYNAMIC_FETCH=false  # Enable Playwright for JS-rendered pages
BROWSER_TIMEOUT=30          # Playwright page load timeout in seconds

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

# Optional: dynamic (JS-rendered) fetch support
uv sync --extra playwright
uv run playwright install chromium

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
#   "transport": "streamable-http",
#   "dynamic_fetch": {"enabled": false, "playwright_installed": false}
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

### Graceful Shutdown

The server handles SIGTERM and SIGINT signals gracefully:
- Closes the Playwright browser instance, if one was started (no-op when dynamic fetch
  is disabled or not installed)
- Cleans up resources before exit

This is important for container deployments and systemd services.

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

The default `Dockerfile` (the only variant published to GHCR):
- Has no browser installed — dynamic fetch unavailable, `ENABLE_DYNAMIC_FETCH=false`
- Health check configuration
- Streamable HTTP as default transport

For dynamic fetch, build `Dockerfile.playwright` yourself (not published — CI only
builds it to validate it still works):

```bash
docker build -f Dockerfile.playwright -t freshrss-mcp:playwright .
```

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
ENABLE_DYNAMIC_FETCH=false
API_KEY=your-secret-key  # For public access security
```

Railway builds from `Dockerfile` (no browser) by default. For dynamic fetch, point
Railway at `Dockerfile.playwright` instead (Settings > Build > Dockerfile Path) and set
`ENABLE_DYNAMIC_FETCH=true`.

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

Sync with the `playwright` extra first (`uv sync --extra playwright`), otherwise
`tools/browser.py`'s lazy `playwright.async_api` import can't be resolved.

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
| `ghcr.io/astral-sh/uv:X.Y.Z` | `COPY --from=` in both Dockerfiles | Dependabot's `docker` ecosystem parses `FROM` lines only. `COPY --from` support is [dependabot-core#12988](https://github.com/dependabot/dependabot-core/pull/12988) — check if it's merged; delete this row once it ships. |
| Python version coherence | `Dockerfile`, `Dockerfile.playwright`, `.python-version`, `pyproject.toml` (`requires-python`), `[tool.ruff] target-version` | A `python:*-slim` bump from Dependabot only touches the Docker tag. The other four spots drift unless updated together, by hand. |
| Chromium version | `playwright install --with-deps chromium` in `Dockerfile.playwright` | Floats with whatever `playwright` package version is pinned; not a separate manifest entry. |

### Handling `@claude` on Dependabot PRs

`.github/workflows/claude.yml` responds to an `@claude` mention in a PR or
issue comment/review, or an issue assignment — same as any other
`@claude`-triggered workflow. It is **not** wired to run automatically on
Dependabot PRs; you have to invoke it.

**When to reach for it:**
- A major-version bump that needs judgement.
- The Python version bump specifically — it needs the five-file
  coordinated update above.
- Red CI on a Dependabot PR that needs diagnosing.
- "What actually changed transitively in this `uv.lock` diff?"

**When not to:** patch/minor PRs — auto-merge will take those once CI is
green, so there's usually nothing to do.

Example prompts, left as comments on the PR:

- `@claude this bumps python to 3.15-slim — update .python-version, requires-python and the ruff target-version to match, and confirm both Dockerfiles still build`
- `@claude summarize what changed transitively in uv.lock here and flag anything risky`
- `@claude the playwright image build failed on this bump — diagnose and fix`
- `@claude check what Dependabot can't see: the ghcr.io/astral-sh/uv COPY --from tag, and python version alignment across all 5 files`

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
| `/reader/api/0/stream/contents/...` | Get article content |
| `/reader/api/0/unread-count` | Get unread counts |
| `/reader/api/0/edit-tag` | Mark read/starred |

## Usage Flow

1. AI calls `get_unread_articles` to fetch unread article list
2. AI analyzes titles and summaries to determine importance
3. For incomplete summaries, AI calls `fetch_full_article` to get full content
   - If content appears incomplete (JS placeholders) and the tool description
     indicates dynamic fetch is available, retry with `force_dynamic=True`
4. AI generates summary report for all articles, linking each one via the
   `freshrss_url` the article already carries
5. For "open all of these in FreshRSS", AI calls `get_article_links` to get one
   URL covering the whole batch
6. After user reads, AI calls `mark_as_read` to mark as read
