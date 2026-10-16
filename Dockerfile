# Build: install deps, fetch the MediaPipe model, assemble the static site.
FROM ghcr.io/astral-sh/uv:0.6.1-python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
COPY web ./web
RUN uv sync --frozen --no-dev --no-editable \
 && uv run --no-sync python scripts/build_web.py

# Run: just the virtualenv and the built site.
FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build --chown=app /app/.venv /app/.venv
COPY --from=build --chown=app /app/dist /app/dist
ENV PATH=/app/.venv/bin:$PATH PSR_STATIC_DIR=/app/dist PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
CMD ["uvicorn", "psr.server.app:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
