# Build context MUST be this package directory, not the repository root.
# The sibling .dockerignore admits only production package metadata/source.
FROM ghcr.io/vectorize-io/hindsight-api:1.2.1@sha256:662109ece429871a81e036427fb93fbb09ba9dc4b01d320d356f114c0e1aedd8

USER root
COPY pyproject.toml /opt/homelab-hindsight-specialists/pyproject.toml
COPY src/ /opt/homelab-hindsight-specialists/src/

# The upstream v1.2.1 lock uses MCP 1.30.0. Resolve/install our declared
# MCP 2.3.0 pin normally (including compatible FastMCP), not --no-deps or
# an import-path overlay. Keep the native image's local-model dependencies/cache.
RUN uv pip install --python /app/api/.venv/bin/python --no-cache /opt/homelab-hindsight-specialists \
    && uv pip check --python /app/api/.venv/bin/python \
    && /app/api/.venv/bin/python -c "from importlib.metadata import version; from homelab_hindsight_specialists.server import create_app; assert version('hindsight-api-slim') == '1.2.1'; assert version('mcp') == '2.3.0'"

USER hindsight
WORKDIR /app
# Upstream host/port/provider/model/worker defaults remain inherited. Supply the
# two extension slots and key references at runtime; no credentials live here.
CMD ["/app/api/.venv/bin/hindsight-specialist-api"]
