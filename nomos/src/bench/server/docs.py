"""
Doc-rendering helper for the Nomos web server.

Single source of truth for what docs exist, what they're called in the
UI, and how their markdown is converted to HTML body fragments. The
frontend's `<DocViewer>` consumes the output of `render_doc_html` and
inserts it into a styled container — so we emit body-only HTML here,
not full <html>…</html> documents.

If you want to share a doc as a standalone offline file (single HTML
with inlined CSS), use `tools/render_doc.py` instead — that's a
separate path for export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import markdown

# nomos/src/bench/server/docs.py → parents[3] is nomos/
PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = PACKAGE_ROOT / "docs"


# Curated metadata + display order for the docs the UI exposes.
# Adding a new doc: add a row here and create docs/<slug>.md.
DOC_META: dict[str, dict[str, Any]] = {
    "tutorial":       {"title": "Tutorial",                "order": 1,
                       "blurb": "Library micro-world walkthrough"},
    "methodology":    {"title": "Methodology",             "order": 2,
                       "blurb": "Five principles, six layers, three operations"},
    "benchmark":      {"title": "Benchmark (v0.5)",        "order": 3,
                       "blurb": "What we're building, decided + deferred"},
    "findings":       {"title": "Findings",                "order": 4,
                       "blurb": "What was built, proven, and what bent"},
    "next_steps":     {"title": "Next Steps",              "order": 5,
                       "blurb": "Roadmap, four tiers, decision guide"},
    "lit_review":     {"title": "Literature Review",       "order": 6,
                       "blurb": "42 related papers, honest positioning"},
    "open_decisions": {"title": "Open Decisions",          "order": 7,
                       "blurb": "Architectural choices still being settled"},
}


def list_docs() -> list[dict[str, Any]]:
    """Return [{slug, title, blurb, order}, …] for docs that exist on disk."""
    items: list[dict[str, Any]] = []
    for slug, meta in DOC_META.items():
        if (DOCS_ROOT / f"{slug}.md").exists():
            items.append({"slug": slug, **meta})
    return sorted(items, key=lambda d: d["order"])


def render_doc_html(slug: str) -> str | None:
    """
    Render `docs/<slug>.md` to an HTML body fragment.

    Returns None if the slug is unknown or its file is missing.
    Uses the same markdown extensions as `tools/render_doc.py` so the
    behavior of tables, fenced code, attribute lists, and inline SVG
    matches the offline-export rendering.
    """
    if slug not in DOC_META:
        return None
    md_path = DOCS_ROOT / f"{slug}.md"
    if not md_path.exists():
        return None

    raw = md_path.read_text()

    # Match render_doc.py's SVG pre-processing so inline <svg> blocks
    # aren't fractured by markdown's paragraph parser (see the
    # tutorial.md derivation-chain bug fixed in d811cf2).
    raw = _flatten_inline_svg(raw)

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "smarty"],
        extension_configs={
            "toc": {"toc_depth": "2-3", "anchorlink": False},
        },
    )
    return md.convert(raw)


def _flatten_inline_svg(text: str) -> str:
    """
    Strip blank lines + comment-only lines from inline <svg>…</svg> blocks.

    Python markdown otherwise treats those as paragraph boundaries inside
    raw HTML and wraps SVG children in <p> tags. Same logic as
    `tools/render_doc.py`; duplicated here to keep this module
    self-contained.
    """
    import re

    def _flatten(match: "re.Match[str]") -> str:
        block = match.group(0)
        cleaned: list[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("<!--") and stripped.endswith("-->"):
                continue
            cleaned.append(stripped if cleaned else line)
        return "\n".join(cleaned)

    return re.sub(r"<svg\b.*?</svg>", _flatten, text, flags=re.DOTALL)
