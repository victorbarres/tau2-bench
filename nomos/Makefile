# Nomos — top-level Makefile
#
# `make help` for available targets.

PYTHON_PORT := 8000
VITE_PORT   := 5173

.PHONY: help install dev backend frontend build oracle clean

help:  ## Show available targets
	@awk 'BEGIN { FS = ":.*?## "; printf "Targets:\n" } /^[a-zA-Z_-]+:.*?##/ { printf "  %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install:  ## Install Python + Node dependencies
	uv sync
	cd web && npm install

dev:  ## Run backend (:$(PYTHON_PORT)) and frontend (:$(VITE_PORT)) concurrently
	@echo "→ Backend: http://localhost:$(PYTHON_PORT)"
	@echo "→ Frontend: http://localhost:$(VITE_PORT)"
	@echo "→ Ctrl-C stops both."
	@trap 'kill 0' EXIT; \
	 (uv run uvicorn bench.server.app:app --reload --port $(PYTHON_PORT) --app-dir src) & \
	 (cd web && npm run dev) & \
	 wait

backend:  ## Run backend only (FastAPI on :$(PYTHON_PORT))
	uv run uvicorn bench.server.app:app --reload --port $(PYTHON_PORT) --app-dir src

frontend:  ## Run frontend only (Vite dev server on :$(VITE_PORT))
	cd web && npm run dev

build:  ## Build the React app for production
	cd web && npm run build

oracle:  ## Run the library solo-mode oracle (no LLM)
	uv run python tools/library_solo.py --oracle

clean:  ## Remove build artifacts and caches
	rm -rf web/dist web/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
