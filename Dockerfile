FROM node:22-slim AS web
WORKDIR /src/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv
WORKDIR /app
COPY server/ ./server/
COPY --from=web /src/web/dist ./server/a2a_workbench/static
RUN cd server && uv pip install --system --no-cache ".[postgres]" && cd / && rm -rf /app/server
RUN useradd --uid 10001 --create-home workbench && mkdir /data && chown workbench /data
USER workbench
ENV A2AW_HOST=0.0.0.0 A2AW_HOME=/data
VOLUME /data
EXPOSE 8484
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8484/api/health', timeout=2)"
LABEL org.opencontainers.image.title="A2A Workbench" \
      org.opencontainers.image.description="Debug, test and conformance-check A2A agents" \
      org.opencontainers.image.source="https://github.com/mittal0802/a2a-workbench" \
      org.opencontainers.image.licenses="Apache-2.0"
CMD ["a2a-workbench", "serve"]
