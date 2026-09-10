FROM python:3.14-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies before copying source, so source edits don't
# invalidate the dependency layer.
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code and install the project itself
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Default environment variables
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=::
ENV LOG_LEVEL=INFO
# Note: MCP_PORT defaults to 8080, but Railway will inject PORT which is auto-detected

# python:*-slim has no curl; probe /health with the stdlib instead.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import os, urllib.request; port = os.environ.get('MCP_PORT') or os.environ.get('PORT') or '8080'; urllib.request.urlopen('http://localhost:' + port + '/health', timeout=5)" || exit 1

EXPOSE 8080

CMD ["freshrss-mcp"]
