# One file, two production images (docs/DEPLOY.md):
#   app   (default target) Django/gunicorn, the Celery workers and beat. OCR tools and the
#         embedding model are baked in, so a container needs no network to answer a question.
#   proxy Caddy with the built React app; terminates HTTPS and proxies the API to `web`.
#
#   docker build -t tenderlens:latest .
#   docker build --target proxy -t tenderlens-proxy:latest .
#
# Build tools (uv, node, the Hugging Face download) live in throwaway stages only.

ARG PYTHON_IMAGE=python:3.12-slim-trixie

# --- 1. React app ----------------------------------------------------------------------
FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build
# The Content-Security-Policy needs the hash of every inline <script> in index.html; computing
# it from the build means an edit to that script can never silently break the page.
COPY deploy/caddy/csp.mjs ./
RUN node csp.mjs dist/index.html > csp.caddy && cat csp.caddy

# --- 2. Python dependencies + embedding model ------------------------------------------
FROM ${PYTHON_IMAGE} AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project --extra copilot
# Baked in rather than downloaded at start: web and the default worker both load it, a cold
# start must not depend on huggingface.co being up or rate-limiting us, and the layer is
# cached until the model changes. Only the PyTorch weights + tokenizer (~470 MB), not the
# ONNX/OpenVINO copies. A fine-tuned model is a local path instead (EMBEDDING_MODEL=/models/x).
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
RUN mkdir -p /opt/hf && if [ -n "$EMBEDDING_MODEL" ] && [ "$EMBEDDING_MODEL" != fake ]; then \
      HF_HOME=/opt/hf HF_HUB_DISABLE_TELEMETRY=1 /opt/venv/bin/python -c \
      "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], \
      ignore_patterns=['onnx/*', 'openvino/*', '*.onnx', '*.bin', '*.h5', '*.msgpack', '*.ot'])" \
      "$EMBEDDING_MODEL"; fi \
    && chmod -R a+rX /opt/hf   # hub writes some cache files 0600; the app user must read them

# --- 3. proxy: Caddy + the static React app --------------------------------------------
FROM caddy:2.10-alpine AS proxy
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=ui /ui/csp.caddy /etc/caddy/csp.caddy
COPY --from=ui /ui/dist /srv
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tail -1

# --- 4. app: Django, Celery ------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 MEDIA_ROOT=/app/media
# Copilot OCR for scanned tender pages: ocrmypdf + Tesseract (English and Hindi) + Ghostscript.
# libgomp1: OpenMP runtime the bid price model (LightGBM) needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ocrmypdf tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin ghostscript libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1001 --create-home --home-dir /home/app app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
WORKDIR /app
# Code stays root-owned (read-only for the app user); only media and the beat schedule
# are writable, and both are volumes in production.
COPY . .
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput >/dev/null \
    && mkdir -p /app/media /var/lib/celery && chown app:app /app/media /var/lib/celery
USER app
EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["web"]
