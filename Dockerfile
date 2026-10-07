FROM node:22-slim AS web
WORKDIR /src/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY server/ ./server/
COPY --from=web /src/web/dist ./server/a2a_workbench/static
RUN cd server && uv pip install --system --no-cache .
ENV A2AW_HOST=0.0.0.0 A2AW_HOME=/data
VOLUME /data
EXPOSE 8484
CMD ["a2a-workbench", "serve"]
