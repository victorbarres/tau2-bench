#!/usr/bin/env python3
"""
Render a markdown document under docs/ to a self-contained HTML file
under docs/. The output is a single HTML file with all CSS inlined — no
external resources, works offline, can be shared as a single attachment.

Usage:
  uv run python tools/render_doc.py findings           # renders docs/findings.md → docs/findings.html
  uv run python tools/render_doc.py methodology        # renders docs/methodology.md → docs/methodology.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import markdown

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PACKAGE_ROOT / "docs"


# ============================================================================
# CSS — design goals: confident typography, generous whitespace, print-friendly.
# Body uses a serif stack (Charter / Iowan / Georgia) for long reading;
# headings + UI use a system sans-serif. One accent color for links and
# quote bars. Tables and code blocks have subtle distinction from prose.
# ============================================================================


STYLES = r"""
:root {
  --content-width: 760px;
  --font-body: 'Charter', 'Iowan Old Style', 'Apple Garamond', Baskerville, Georgia, 'Times New Roman', serif;
  --font-mono: 'SF Mono', Menlo, Consolas, 'Liberation Mono', 'Courier New', monospace;
  --font-sans: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --color-text: #1a1a1a;
  --color-muted: #6b7280;
  --color-accent: #1d4ed8;
  --color-accent-soft: #dbeafe;
  --color-border: #e5e7eb;
  --color-banner: #111827;
  --color-banner-text: #f9fafb;
  --color-bg-soft: #fafafa;
  --color-code-bg: #f3f4f6;
  --color-code-border: #e5e7eb;
}

* { box-sizing: border-box; }

html, body { margin: 0; padding: 0; }

body {
  font-family: var(--font-body);
  font-size: 17px;
  line-height: 1.65;
  color: var(--color-text);
  background: #fff;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.banner {
  background: var(--color-banner);
  color: var(--color-banner-text);
  padding: 5rem 2rem 4rem;
  border-bottom: 1px solid #1f2937;
}
.banner-inner {
  max-width: var(--content-width);
  margin: 0 auto;
}
.banner .eyebrow {
  font-family: var(--font-sans);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.78rem;
  font-weight: 600;
  color: #9ca3af;
  margin: 0 0 1rem;
}
.banner h1 {
  font-family: var(--font-sans);
  font-size: 2.6rem;
  margin: 0 0 0.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.banner .subtitle {
  font-family: var(--font-sans);
  color: #d1d5db;
  font-size: 1.15rem;
  margin: 0;
  line-height: 1.4;
}
.banner .meta {
  font-family: var(--font-sans);
  color: #9ca3af;
  font-size: 0.85rem;
  margin-top: 2rem;
}
.banner .meta a {
  color: #d1d5db;
  border-bottom: 1px solid #4b5563;
}

.container {
  max-width: var(--content-width);
  margin: 0 auto;
  padding: 3rem 2rem 6rem;
}

/* Table of contents */
.toc {
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1.5rem 2rem 1.5rem 2rem;
  margin: 0 0 3.5rem;
  font-family: var(--font-sans);
}
.toc-heading {
  font-family: var(--font-sans);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-muted);
  margin: 0 0 1rem;
}
.toc ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.toc ul ul {
  margin-left: 1rem;
  margin-top: 0.25rem;
}
.toc li {
  margin: 0.35rem 0;
  font-size: 0.95rem;
  line-height: 1.4;
}
.toc a {
  color: var(--color-text);
  text-decoration: none;
  border-bottom: none;
}
.toc a:hover {
  color: var(--color-accent);
}

/* Headings in body */
h1, h2, h3, h4, h5 {
  font-family: var(--font-sans);
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: -0.015em;
  margin-top: 3rem;
  margin-bottom: 1rem;
}
h1 {
  font-size: 2rem;
  border-bottom: 2px solid var(--color-text);
  padding-bottom: 0.5rem;
}
h2 {
  font-size: 1.55rem;
  margin-top: 3.5rem;
}
h3 {
  font-size: 1.2rem;
  color: #374151;
}
h4 {
  font-size: 1.05rem;
  color: #4b5563;
}

/* Anchor hover affordance on headings */
h1, h2, h3, h4 { position: relative; }
h2:hover::before, h3:hover::before {
  content: '§';
  position: absolute;
  left: -1.4rem;
  color: var(--color-muted);
  font-weight: 400;
}

p { margin: 1rem 0; }

a {
  color: var(--color-accent);
  text-decoration: none;
  border-bottom: 1px solid rgba(29, 78, 216, 0.25);
  transition: border-color 0.15s ease;
}
a:hover {
  border-bottom-color: var(--color-accent);
}

strong { font-weight: 700; color: #111827; }

em { font-style: italic; }

/* Code */
code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  background: var(--color-code-bg);
  padding: 0.12em 0.35em;
  border-radius: 3px;
  border: 1px solid var(--color-code-border);
}
pre {
  font-family: var(--font-mono);
  background: var(--color-code-bg);
  border: 1px solid var(--color-code-border);
  padding: 1rem 1.25rem;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.86em;
  line-height: 1.55;
  margin: 1.25rem 0;
}
pre code {
  background: none;
  padding: 0;
  border: none;
  font-size: 1em;
}

/* Blockquotes */
blockquote {
  border-left: 4px solid var(--color-accent);
  background: var(--color-accent-soft);
  margin: 1.5rem 0;
  padding: 1rem 1.25rem 1rem 1.5rem;
  color: #1e3a8a;
  border-radius: 0 4px 4px 0;
  font-style: normal;
}
blockquote p { margin: 0.5rem 0; }
blockquote p:first-child { margin-top: 0; }
blockquote p:last-child { margin-bottom: 0; }

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.75rem 0;
  font-family: var(--font-sans);
  font-size: 0.92rem;
  line-height: 1.4;
}
th, td {
  text-align: left;
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--color-border);
  vertical-align: top;
}
th {
  font-weight: 600;
  background: var(--color-bg-soft);
  color: #374151;
  border-bottom: 2px solid #d1d5db;
}
tbody tr:hover {
  background: rgba(29, 78, 216, 0.03);
}

/* Lists */
ul, ol {
  margin: 1rem 0;
  padding-left: 1.5rem;
}
li { margin: 0.35rem 0; }
li > p { margin: 0.4rem 0; }
li > ul, li > ol { margin: 0.4rem 0; }

/* Horizontal rule */
hr {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 3.5rem 0;
}

/* Footer */
.footer {
  max-width: var(--content-width);
  margin: 0 auto;
  padding: 2rem;
  border-top: 1px solid var(--color-border);
  font-family: var(--font-sans);
  color: var(--color-muted);
  font-size: 0.85rem;
  text-align: center;
}

/* Print styles */
@media print {
  body { font-size: 11pt; }
  .banner {
    background: #fff;
    color: var(--color-text);
    border-bottom: 2px solid var(--color-text);
    padding: 1.5rem 0 1rem;
    page-break-after: avoid;
  }
  .banner .eyebrow, .banner .subtitle, .banner .meta { color: var(--color-muted); }
  .banner .meta a { color: var(--color-muted); }
  .container { padding: 1rem 0; max-width: 100%; }
  .toc { background: none; border: 1px solid var(--color-border); }
  a { color: var(--color-text); border-bottom: 1px dotted var(--color-muted); }
  h1, h2 { page-break-after: avoid; }
  table, pre, blockquote { page-break-inside: avoid; }
  .footer { border-top: 1px solid var(--color-border); }
}

/* Responsive */
@media (max-width: 700px) {
  body { font-size: 16px; }
  .banner { padding: 3rem 1.25rem 2.5rem; }
  .banner h1 { font-size: 1.9rem; }
  .banner .subtitle { font-size: 1rem; }
  .container { padding: 2rem 1.25rem 4rem; }
  .toc { padding: 1.25rem 1.5rem; }
  h2 { font-size: 1.35rem; }
  h3 { font-size: 1.1rem; }
  table { font-size: 0.85rem; }
  th, td { padding: 0.5rem 0.6rem; }
}
"""


# ============================================================================
# HTML template — single-file, no external resources.
# ============================================================================


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{subtitle}">
<style>{styles}</style>
</head>
<body>
<header class="banner">
  <div class="banner-inner">
    <p class="eyebrow">Logic-First Domain Design</p>
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    <p class="meta">{meta}</p>
  </div>
</header>
<main class="container">
{toc_block}
{body}
</main>
<footer class="footer">
  Generated from <code>docs/{doc_stem}.md</code> via <code>tools/render_doc.py</code>.
</footer>
</body>
</html>
"""


# ============================================================================
# Renderer
# ============================================================================


PAGE_META = {
    "findings": {
        "title": "Findings",
        "subtitle": "What was built, what was proven, what bent",
        "meta": "Companion to <a href=\"methodology.html\">methodology.html</a> "
                "(the framework) and <a href=\"next_steps.html\">next_steps.html</a> "
                "(the roadmap).",
    },
    "methodology": {
        "title": "Methodology",
        "subtitle": "Five principles, six layers, three operations",
        "meta": "Companion to <a href=\"findings.html\">findings.html</a> "
                "(the empirical writeup) and <a href=\"next_steps.html\">next_steps.html</a> "
                "(the roadmap).",
    },
    "next_steps": {
        "title": "Next Steps",
        "subtitle": "A tiered roadmap for extending this work",
        "meta": "Companion to <a href=\"methodology.html\">methodology.html</a> "
                "(the framework) and <a href=\"findings.html\">findings.html</a> "
                "(the empirical writeup).",
    },
    "lit_review": {
        "title": "Literature Review",
        "subtitle": "Related work — benchmarks, logic policy, formal methods, test synthesis",
        "meta": "Background context for <a href=\"methodology.html\">methodology.html</a>. "
                "Built from 42 papers gathered by parallel research agents; full "
                "bibliography in <a href=\"references.bib\">references.bib</a>.",
    },
    "tutorial": {
        "title": "Tutorial",
        "subtitle": "A library micro-world — the methodology on the smallest non-trivial example",
        "meta": "The fastest way to understand what the methodology does. "
                "Read this first; then "
                "<a href=\"methodology.html\">methodology.html</a> for the framework "
                "and <a href=\"findings.html\">findings.html</a> for the results.",
    },
}


def render(doc_stem: str) -> Path:
    """
    Render `docs/<doc_stem>.md` to a single self-contained
    `docs/<doc_stem>.html`. Returns the path written.

    The H1 from the source markdown is stripped from the body (it's
    duplicated in the banner instead). PAGE_META supplies the banner
    title / subtitle / cross-link; falls back to a titled stem otherwise.
    """
    src = DOCS_DIR / f"{doc_stem}.md"
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    out = DOCS_DIR / f"{doc_stem}.html"

    raw = src.read_text()

    # Pre-process inline <svg>…</svg> blocks so Python markdown leaves them
    # intact. Indented child lines and HTML comments would otherwise cause
    # the parser to split the SVG across multiple <p> blocks, which produces
    # broken markup like `<p><line .../>` outside the parent <svg>. Drop
    # blank lines, drop comment-only lines, and de-indent. Authors can keep
    # readable SVG source; this preserves it as one raw HTML block.
    def _flatten_svg(match: re.Match) -> str:
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

    raw = re.sub(r"<svg\b.*?</svg>", _flatten_svg, raw, flags=re.DOTALL)

    # Run markdown with the extensions we need.
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "smarty"],
        extension_configs={
            "toc": {
                "marker": "",        # we'll inject manually
                "permalink": False,
                "title": "",
                "anchorlink": False,
                "toc_depth": "2-3",  # H2 and H3 only — keeps the index tight
            },
        },
    )
    body_html = md.convert(raw)

    # Strip the top-level H1 from the body (it's already in the banner).
    body_html = re.sub(r"<h1\b[^>]*>.*?</h1>", "", body_html, count=1, flags=re.DOTALL)

    # The toc extension exposes a self-contained <div class="toc">...</div>.
    # Strip its wrapper so we can use our own styled container.
    toc_inner = re.sub(r"^<div class=\"toc\">|</div>\s*$", "", md.toc.strip(), flags=re.MULTILINE)

    toc_block = (
        f'<nav class="toc">'
        f'<p class="toc-heading">Contents</p>'
        f'{toc_inner}'
        f'</nav>'
        if toc_inner.strip() else ""
    )

    meta = PAGE_META.get(doc_stem, {
        "title": doc_stem.title(),
        "subtitle": "",
        "meta": "",
    })

    html = TEMPLATE.format(
        title=meta["title"],
        subtitle=meta["subtitle"],
        meta=meta["meta"],
        styles=STYLES,
        toc_block=toc_block,
        body=body_html,
        doc_stem=doc_stem,
    )

    out.write_text(html)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry: render one or more document stems to HTML."""
    parser = argparse.ArgumentParser(
        description="Render a docs/ markdown file to a self-contained HTML page.",
    )
    parser.add_argument(
        "doc_stems",
        nargs="+",
        help="document stem(s) to render, e.g. 'findings' or 'methodology'",
    )
    args = parser.parse_args(argv)

    for stem in args.doc_stems:
        out = render(stem)
        size_kb = out.stat().st_size / 1024
        print(f"Wrote {out.relative_to(PACKAGE_ROOT)} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
