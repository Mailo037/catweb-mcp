"""Repo fetch + in-memory index of CatWeb docs and templates."""
from __future__ import annotations

import io
import os
import re
import json
import time
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx
import yaml

CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h

DEFAULT_DOCS_REPO = "Mailo037/catweb-docs"
DEFAULT_RESOURCES_REPO = "Mailo037/catweb-additional-resources"


def cache_root() -> Path:
    base = os.environ.get("CATWEB_MCP_CACHE")
    if base:
        return Path(base)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "catweb-mcp"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "catweb-mcp"


@dataclass
class Template:
    slug: str
    title: str
    author: str
    category: str
    tags: list[str]
    type: str
    source: str
    description: str
    folder: Path = field(repr=False)

    def to_summary(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "type": self.type,
            "source": self.source,
            "description": self.description,
        }


@dataclass
class Doc:
    name: str          # e.g. "CatDocs", "JSONScript"
    filename: str      # e.g. "CatDocs.md"
    headings: list[str]
    body: str = field(repr=False)
    path: Path = field(repr=False)


class Index:
    def __init__(self, docs_repo: str = DEFAULT_DOCS_REPO, resources_repo: str = DEFAULT_RESOURCES_REPO):
        self.docs_repo = docs_repo
        self.resources_repo = resources_repo
        self.root = cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.templates: list[Template] = []
        self.docs: list[Doc] = []
        self.last_refresh: float = 0.0

    # ---------- fetch ----------

    def _gh_headers(self) -> dict:
        headers = {"User-Agent": "catweb-mcp"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _latest_sha(self, repo: str, branch: str = "main") -> str | None:
        """Return latest commit SHA on `branch` of `repo`, or None on failure."""
        url = f"https://api.github.com/repos/{repo}/commits/{branch}"
        try:
            with httpx.Client(follow_redirects=True, timeout=15) as client:
                r = client.get(url, headers={**self._gh_headers(), "Accept": "application/vnd.github.sha"})
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
                # fallback: full commit JSON
                r = client.get(url, headers=self._gh_headers())
                if r.status_code == 200:
                    return r.json().get("sha")
        except httpx.HTTPError:
            return None
        return None

    def _meta_path(self) -> Path:
        return self.root / "meta.json"

    def _load_meta(self) -> dict:
        p = self._meta_path()
        if p.exists():
            try: return json.loads(p.read_text(encoding="utf-8"))
            except Exception: return {}
        return {}

    def _save_meta(self, meta: dict) -> None:
        self._meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def _fetch_tarball(self, repo: str, dest: Path) -> None:
        """Download repo tarball from GitHub and extract into dest (replacing it)."""
        url = f"https://api.github.com/repos/{repo}/tarball"
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            r = client.get(url, headers=self._gh_headers())
            r.raise_for_status()
            data = r.content
        # Extract to a temp dir, then atomically swap into dest.
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                tar.extractall(tmp)
            entries = list(Path(tmp).iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise RuntimeError(f"Unexpected tarball layout for {repo}")
            src = entries[0]
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(src), str(dest))

    def check_for_updates(self) -> dict:
        """Compare cached commit SHAs against GitHub. Cheap (~200ms, no download).

        Returns each repo's cached SHA, latest SHA, and whether they differ.
        """
        meta = self._load_meta()
        out: dict = {}
        for key, repo in (("docs", self.docs_repo), ("resources", self.resources_repo)):
            cached = (meta.get(key) or {}).get("sha")
            latest = self._latest_sha(repo)
            out[key] = {
                "repo": repo,
                "cached_sha": cached,
                "latest_sha": latest,
                "up_to_date": bool(cached) and cached == latest,
            }
        out["any_outdated"] = any(not r["up_to_date"] for r in out.values() if isinstance(r, dict))
        return out

    def refresh(self, force: bool = False) -> dict:
        """Re-fetch repos if their commit SHA on GitHub differs from cached (or force=True).

        Without force, this only re-downloads repos that actually changed —
        the SHA check is ~200ms and avoids a multi-megabyte tarball pull
        when nothing has moved.
        """
        meta = self._load_meta()
        updated: dict[str, dict] = {}
        for key, repo, dest in (
            ("docs", self.docs_repo, self._docs_dir()),
            ("resources", self.resources_repo, self._resources_dir()),
        ):
            cached_sha = (meta.get(key) or {}).get("sha")
            latest_sha = self._latest_sha(repo)
            needs_download = force or not dest.exists() or not cached_sha or (latest_sha and cached_sha != latest_sha)
            if needs_download:
                self._fetch_tarball(repo, dest)
                meta[key] = {"sha": latest_sha, "fetched_at": time.time(), "repo": repo}
                updated[key] = {"changed": True, "from": cached_sha, "to": latest_sha}
            else:
                updated[key] = {"changed": False, "sha": cached_sha}
        self._save_meta(meta)
        self.last_refresh = time.time()
        self._build()
        return {
            "templates": len(self.templates),
            "docs": len(self.docs),
            "repos": updated,
        }

    def _docs_dir(self) -> Path:
        return self.root / "catweb-docs"

    def _resources_dir(self) -> Path:
        return self.root / "catweb-additional-resources"

    # ---------- index ----------

    def _build(self) -> None:
        self.templates = self._load_templates(self._resources_dir())
        self.docs = self._load_docs(self._docs_dir())

    def _load_docs(self, root: Path) -> list[Doc]:
        out: list[Doc] = []
        for md in sorted(root.glob("*.md")):
            text = md.read_text(encoding="utf-8", errors="replace")
            headings = [m.group(1).strip() for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)]
            out.append(Doc(name=md.stem, filename=md.name, headings=headings, body=text, path=md))
        return out

    def _load_templates(self, root: Path) -> list[Template]:
        out: list[Template] = []
        skip_dirs = {"template", "encoder by file.rbx", ".git", ".github", ".claude"}
        for sub in sorted(root.iterdir()):
            if not sub.is_dir() or sub.name in skip_dirs:
                continue
            info = sub / "info.md"
            if not info.exists():
                continue
            fm, body = self._parse_frontmatter(info.read_text(encoding="utf-8", errors="replace"))
            if not fm:
                continue
            tags = fm.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            out.append(Template(
                slug=sub.name,
                title=str(fm.get("title", sub.name)),
                author=str(fm.get("author", "")),
                category=str(fm.get("category", "")),
                tags=[str(t) for t in tags],
                type=str(fm.get("type", "")),
                source=str(fm.get("source", "")),
                description=body.strip(),
                folder=sub,
            ))
        return out

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        if not text.startswith("---"):
            return {}, text
        end = text.find("\n---", 3)
        if end < 0:
            return {}, text
        try:
            fm = yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError:
            fm = {}
        body = text[end + 4 :].lstrip("\n")
        return fm if isinstance(fm, dict) else {}, body

    # ---------- queries ----------

    def search(self, query: str, kind: str = "all", limit: int = 10) -> list[dict]:
        q = query.lower().strip()
        results: list[tuple[int, dict]] = []
        if kind in ("all", "templates"):
            for t in self.templates:
                score = self._score(q, t.title, t.description, " ".join(t.tags), t.author, t.slug)
                if score > 0:
                    results.append((score, {"kind": "template", **t.to_summary()}))
        if kind in ("all", "docs"):
            for d in self.docs:
                score = self._score(q, d.name, " ".join(d.headings), d.body[:5000])
                if score > 0:
                    results.append((score, {"kind": "doc", "name": d.name, "filename": d.filename, "headings": d.headings[:20]}))
        results.sort(key=lambda r: r[0], reverse=True)
        return [r[1] for r in results[:limit]]

    @staticmethod
    def _score(q: str, *fields: str) -> int:
        if not q:
            return 0
        score = 0
        terms = [t for t in re.split(r"\s+", q) if t]
        for f in fields:
            fl = f.lower()
            for term in terms:
                if term in fl:
                    # exact word match gets higher weight
                    score += 3 if re.search(rf"\b{re.escape(term)}\b", fl) else 1
        return score

    def filter_templates(self, tag: str | None = None, author: str | None = None,
                         type: str | None = None, source: str | None = None,
                         category: str | None = None, limit: int = 20) -> list[dict]:
        out: list[dict] = []
        for t in self.templates:
            if tag and tag.lower() not in (s.lower() for s in t.tags):
                continue
            if author and author.lower() not in t.author.lower():
                continue
            if type and type.lower() not in t.type.lower():
                continue
            if source and source.lower() not in t.source.lower():
                continue
            if category and category.lower() != t.category.lower():
                continue
            out.append(t.to_summary())
            if len(out) >= limit:
                break
        return out

    def get_template(self, slug: str) -> dict | None:
        for t in self.templates:
            if t.slug == slug:
                content = (t.folder / "content.md").read_text(encoding="utf-8", errors="replace") if (t.folder / "content.md").exists() else ""
                credits = (t.folder / "credits.md").read_text(encoding="utf-8", errors="replace") if (t.folder / "credits.md").exists() else ""
                return {**t.to_summary(), "content": content, "credits": credits}
        return None

    def get_doc(self, name: str) -> dict | None:
        target = name.lower().removesuffix(".md")
        for d in self.docs:
            if d.name.lower() == target:
                return {"name": d.name, "filename": d.filename, "headings": d.headings, "content": d.body}
        return None

    def list_tags(self) -> list[dict]:
        counts: dict[str, int] = {}
        for t in self.templates:
            for tag in t.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    def list_authors(self) -> list[dict]:
        counts: dict[str, int] = {}
        for t in self.templates:
            if t.author:
                counts[t.author] = counts.get(t.author, 0) + 1
        return [{"author": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    def stats(self) -> dict:
        return {
            "templates": len(self.templates),
            "docs": [d.name for d in self.docs],
            "tags": len(self.list_tags()),
            "authors": len(self.list_authors()),
            "last_refresh": self.last_refresh,
            "cache_root": str(self.root),
        }
