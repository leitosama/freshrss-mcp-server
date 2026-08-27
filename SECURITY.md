# Security Policy

## Supported Versions

This is a small, self-hosted personal project. Only the latest published
build is supported — the `:latest` image on GHCR (built from `main`) and
the most recent `v*.*.*` release tag. There are no backported security
fixes for older tags; if you're running an older version, update.

## Reporting a Vulnerability

Please report security issues via
[GitHub private vulnerability reporting](security/advisories/new)
(Security tab → Report a vulnerability) rather than a public issue. This
is a pet project maintained best-effort — expect a response typically
within a week, not an SLA.

## What Runs Automatically

- **[CodeQL](security/code-scanning)** — static analysis of the
  Python source, on every PR and weekly.
- **[zizmor](security/code-scanning)** — static analysis of the
  GitHub Actions workflows themselves (template injection, unpinned
  actions, excessive permissions).
- **[OSV-Scanner](security/code-scanning)** — CVE scanning of Python
  dependencies via `uv.lock`, on every PR and weekly. See "Known gap"
  below for why this exists alongside Dependabot.
- **Dependabot** — weekly version updates for GitHub Actions, the Docker
  base image, and Python dependencies (`uv.lock`).
- **Secret scanning + push protection** — GitHub's built-in scanning for
  committed credentials.

## Known Gap: Dependabot Alerts Don't Cover Python Dependencies

GitHub's dependency graph does not currently parse `uv.lock`, so
Dependabot *security alerts* (as distinct from its version-update PRs,
which do work) do not cover this project's Python dependencies.
**OSV-Scanner is the compensating control** for that gap — see above.

## Scope Notes

A few things worth being explicit about, since they're genuine security
properties of this project rather than oversights:

- **`API_KEY` is a simple bearer-token check, not OAuth 2.1.** It's
  intended for internal/personal use only — see the README and CLAUDE.md.
- **`FRESHRSS_API_PASSWORD` is a FreshRSS *API* password**, generated in
  FreshRSS's own settings, not your FreshRSS account password.
- **The published image (`ghcr.io/leitosama/freshrss-mcp-server`) is the
  no-browser `Dockerfile` variant.** `Dockerfile.playwright` (dynamic
  fetch / Chromium) is never published — build it yourself if you need it.
