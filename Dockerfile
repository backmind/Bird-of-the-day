# syntax=docker/dockerfile:1.7
#
# Bird of the Day — self-contained microservice container.
#
# Build (host arch):
#     docker build -t bird-of-the-day .
#
# Build (multi-arch):
#     docker buildx build --platform linux/amd64,linux/arm64 -t bird-of-the-day .
#
# Run:
#     docker run -d --name botd \
#       -p 8080:8080 \
#       -e EBIRD_API_KEY=YOUR_KEY \
#       -v botd-data:/var/lib/botd \
#       --restart unless-stopped \
#       bird-of-the-day
#
# The container serves /, /archive.html and /feed.xml on port 8080. A
# built-in cron daemon (supercronic) regenerates the site daily at 07:00 UTC.

# ============================================================================
# Stage 1 — builder
# ============================================================================
FROM python:3.12-slim AS builder

# uv from its official image: build-time only, never enters the runtime layer.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# uv defaults to hardlink mode which is unreliable across Docker layers.
# Compile bytecode at install time for faster cold starts.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /build

# Layer 1: deps only — invalidated only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Layer 2: project source. The package is intentionally NOT installed (we run
# from /app via PYTHONPATH so __file__ resolves to the source tree, which is
# what BASE_DIR depends on).
COPY scripts/ ./scripts/
COPY data/ ./data/

# ============================================================================
# Stage 2 — runtime
# ============================================================================
FROM python:3.12-slim AS runtime

ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.33
ARG BUILD_REVISION=unknown

LABEL org.opencontainers.image.source="https://github.com/backmind/Bird-of-the-day" \
      org.opencontainers.image.title="Bird of the Day" \
      org.opencontainers.image.description="Daily bird species RSS feed and static site, self-hostable." \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

# Runtime packages: nginx (HTTP server), tini (PID 1 / signal forwarding),
# curl (healthcheck + supercronic download), ca-certificates (HTTPS to eBird,
# Wikipedia, BoW, Macaulay).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        tini \
        curl \
        ca-certificates \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
        -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. uid 1000 is the conventional first regular user, friendly
# to bind-mounts from the host without permission gymnastics.
RUN useradd --system --uid 1000 --home /var/lib/botd --shell /usr/sbin/nologin botd

# Copy the prepared venv and source from the builder stage.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/data /app/data

# Container support files.
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/crontab /etc/supercronic/crontab
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/healthcheck.sh /usr/local/bin/healthcheck.sh
COPY docker/placeholder.html /app/placeholder.html

# Filesystem prep:
#   - /var/lib/botd: the volume mount point + state dir
#   - /var/log/nginx, /var/lib/nginx, /run/nginx: nginx writable dirs
#   - chown everything to botd so the unprivileged user can write
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh \
    && mkdir -p /var/lib/botd/cache /var/log/nginx /var/lib/nginx /run/nginx \
    && chown -R botd:botd /var/lib/botd /var/log/nginx /var/lib/nginx /run/nginx /app /etc/supercronic

# Make the venv's python and friends the default for the botd user.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BOTD_STATE_DIR=/var/lib/botd

EXPOSE 8080

# Anonymous volume so state persists across container restarts even when the
# user forgot to mount one. A named volume is recommended in production.
VOLUME ["/var/lib/botd"]

# The healthcheck verifies feed.xml exists, was modified within the last 36h,
# and that nginx is actually serving it. Long interval because the site only
# changes once a day; long start_period because the cold-start synchronous
# generation can take ~60s on a fresh deploy.
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

USER botd
WORKDIR /app

# tini is PID 1 → entrypoint script → exec nginx (CMD).
# CMD is split from ENTRYPOINT so users can override for debugging:
#   docker run --rm -it --entrypoint /bin/bash bird-of-the-day
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
