"""
Nomos — runnable benchmark and authoring environment for logic-first
agent tasks.

This is the Python package that backs the web server and (later) the
MCP server, run orchestrator, grader, and reference policy agents.
For v0 it contains only the web server's scaffolding.

Layout:
    bench/
        server/   — FastAPI app serving docs (v0); will grow to host
                    the REST + SSE API for runs, tasks, leaderboard, …
        core/     — (planned) shared World / Solve / Grader Python
        mcp/      — (planned) FastMCP server per domain
        agents/   — (planned) reference policy agents
"""

__version__ = "0.1.0"
