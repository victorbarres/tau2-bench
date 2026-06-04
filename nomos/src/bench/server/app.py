"""
Nomos web server — FastAPI backend (v0).

v0 surface: serves the docs index and rendered HTML for each doc.
Future endpoints will land here as the benchmark UI grows:
domains, tasks, runs (with SSE), grading, leaderboard.

Run locally:
    make dev                                   # backend + frontend
    make backend                               # backend only
    uv run uvicorn bench.server.app:app \
        --reload --port 8000 --app-dir src     # raw uvicorn

For dev, CORS is permissive to localhost:5173 so the Vite dev server
can call /api/* directly. In a production build the React bundle
should be served from the same origin.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from bench import __version__
from bench.server.docs import list_docs, render_doc_html

app = FastAPI(title="Nomos", version=__version__)

# Permissive CORS for the Vite dev server. Tighten / remove for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns the package version."""
    return {"status": "ok", "name": "Nomos", "version": __version__}


@app.get("/api/docs")
def docs_index() -> JSONResponse:
    """Return the list of available docs with display metadata."""
    return JSONResponse(list_docs())


@app.get("/api/docs/{slug}", response_class=HTMLResponse)
def doc_content(slug: str) -> str:
    """
    Return the rendered HTML body for the named doc.

    The frontend's <DocViewer> inserts this into a styled container
    via dangerouslySetInnerHTML — so the response is a body fragment,
    not a full HTML document.
    """
    html = render_doc_html(slug)
    if html is None:
        raise HTTPException(status_code=404, detail=f"unknown doc: {slug!r}")
    return html
