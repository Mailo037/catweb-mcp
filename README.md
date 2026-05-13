# catweb-mcp

An MCP (Model Context Protocol) server that exposes search over two CatWeb repos so AI agents can find the right docs and templates without crawling everything:

- **[catweb-docs](https://github.com/Mailo037/catweb-docs)** — CatDocs, JSONScript, UIGPT specifications
- **[catweb-additional-resources](https://github.com/Mailo037/catweb-additional-resources)** — community templates (JSON + upload codes) with metadata

The server downloads tarballs of both repos on startup (one HTTP call each, ~1–3s), extracts them to a local cache, and indexes the frontmatter of every template's `info.md`. Queries then run instantly against the in-memory index.

## Tools

| Tool | What it does |
|------|--------------|
| `search(query, kind, limit)` | Fuzzy search across templates and docs |
| `find_templates(tag, author, type, source, category, limit)` | Filter templates by metadata |
| `get_template(slug)` | Full content of one template (info + JSON + credits) |
| `get_doc(name)` | Full content of a doc file (`CatDocs`, `JSONScript`, `UIGPT`, `README`) |
| `list_tags()` | All tags with counts |
| `list_authors()` | All authors with counts |
| `refresh()` | Force re-download both repos |
| `stats()` | Index stats and cache info |

## Install

```bash
# from source
git clone https://github.com/Mailo037/catweb-mcp
cd catweb-mcp
pip install .
```

Or with `pipx` / `uv`:

```bash
pipx install git+https://github.com/Mailo037/catweb-mcp
# or
uv tool install git+https://github.com/Mailo037/catweb-mcp
```

## Configure in Claude Code

Add this to your user-level MCP config (`~/.claude/settings.json` or via `claude mcp add`):

```json
{
  "mcpServers": {
    "catweb": {
      "command": "catweb-mcp"
    }
  }
}
```

Or via CLI:

```bash
claude mcp add catweb catweb-mcp
```

## Configure in Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "catweb": {
      "command": "catweb-mcp"
    }
  }
}
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CATWEB_DOCS_REPO` | `Mailo037/catweb-docs` | override docs repo (e.g. for forks) |
| `CATWEB_RESOURCES_REPO` | `Mailo037/catweb-additional-resources` | override resources repo |
| `CATWEB_MCP_CACHE` | `%LOCALAPPDATA%\catweb-mcp` / `~/.cache/catweb-mcp` | cache directory |
| `GITHUB_TOKEN` | (unset) | raises GitHub rate limit from 60/hr to 5000/hr |

## Example queries

Once configured, ask Claude things like:

- *"Search for a typewriter effect template"* → `search("typewriter")`
- *"Show me all templates tagged 'UI' from Jexx"* → `find_templates(tag="UI", author="Jexx")`
- *"Get the JSON for gif-runner"* → `get_template("gif-runner")`
- *"What does the JSONScript Action ID 88 do?"* → `get_doc("JSONScript")` then read the relevant section

## License

MIT — see [LICENSE](./LICENSE).
