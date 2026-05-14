"""MCP server entry point for catweb-mcp."""
from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP

from .index import Index, DEFAULT_DOCS_REPO, DEFAULT_RESOURCES_REPO

_host = os.environ.get("CATWEB_MCP_HOST", "127.0.0.1")
_port = int(os.environ.get("CATWEB_MCP_PORT", "8000"))
mcp = FastMCP("catweb-mcp", host=_host, port=_port)

docs_repo = os.environ.get("CATWEB_DOCS_REPO", DEFAULT_DOCS_REPO)
resources_repo = os.environ.get("CATWEB_RESOURCES_REPO", DEFAULT_RESOURCES_REPO)
index = Index(docs_repo=docs_repo, resources_repo=resources_repo)


def _ensure_loaded() -> None:
    if not index.templates and not index.docs:
        index.refresh()


@mcp.tool()
def search(query: str, kind: str = "all", limit: int = 10) -> list[dict]:
    """Fuzzy-search across CatWeb templates and docs.

    Args:
        query: search terms (space-separated)
        kind: "all" | "templates" | "docs"
        limit: max number of results (default 10)

    Returns:
        Ranked list of matches, each with `kind`, plus type-specific fields.
    """
    _ensure_loaded()
    return index.search(query, kind=kind, limit=limit)


@mcp.tool()
def find_templates(tag: str = "", author: str = "", type: str = "",
                   source: str = "", category: str = "", limit: int = 20) -> list[dict]:
    """Filter templates by exact-ish metadata fields. Empty fields are ignored.

    Args:
        tag: tag the template must have (e.g. "UI", "script")
        author: substring of author field (e.g. "pugwares", "Jexx")
        type: "json", "upload-code", or "json,upload-code"
        source: e.g. "catwebtemplates.com" or "discord:#jsons"
        category: "page" | "component" | "snippet" | "site"
    """
    _ensure_loaded()
    return index.filter_templates(
        tag=tag or None, author=author or None, type=type or None,
        source=source or None, category=category or None, limit=limit,
    )


@mcp.tool()
def get_template(slug: str) -> dict:
    """Fetch full content of one template by folder slug (e.g. 'gif-runner').

    Returns the template's metadata, content.md (upload-code + JSON),
    and credits.md. Use after `search` or `find_templates` to retrieve
    the JSON to actually import.
    """
    _ensure_loaded()
    result = index.get_template(slug)
    if result is None:
        return {"error": f"template '{slug}' not found"}
    return result


@mcp.tool()
def get_doc(name: str) -> dict:
    """Fetch a full CatWeb documentation file by name.

    Args:
        name: one of "CatDocs", "JSONScript", "UIGPT", "README" (case-insensitive)
    """
    _ensure_loaded()
    result = index.get_doc(name)
    if result is None:
        return {"error": f"doc '{name}' not found", "available": [d.name for d in index.docs]}
    return result


@mcp.tool()
def list_tags() -> list[dict]:
    """List all template tags with their counts, sorted descending."""
    _ensure_loaded()
    return index.list_tags()


@mcp.tool()
def list_authors() -> list[dict]:
    """List all template authors with their template counts, sorted descending."""
    _ensure_loaded()
    return index.list_authors()


@mcp.tool()
def check_for_updates() -> dict:
    """Check whether either repo has new commits on GitHub vs. local cache.

    Cheap (~200ms, no download). Returns each repo's cached vs latest
    SHA. Use this before `refresh()` to avoid unnecessary tarball pulls.
    """
    return index.check_for_updates()


@mcp.tool()
def refresh(force: bool = False) -> dict:
    """Refresh the cache from GitHub.

    By default, only re-downloads repos whose commit SHA on GitHub differs
    from the cached one (cheap SHA check first). Pass force=True to
    re-download both unconditionally.
    """
    return index.refresh(force=force)


@mcp.tool()
def stats() -> dict:
    """Server stats: template/doc counts, tag/author counts, cache info."""
    _ensure_loaded()
    return index.stats()


def main() -> None:
    # FASTMCP_HOST / FASTMCP_PORT env vars control host:port when using HTTP transports.
    # CATWEB_MCP_TRANSPORT selects "stdio" (default), "sse", or "streamable-http".
    transport = os.environ.get("CATWEB_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
