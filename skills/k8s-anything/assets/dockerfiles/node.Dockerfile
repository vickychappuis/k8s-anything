# syntax=docker/dockerfile:1
# PORT/EXPOSE default to 3000: set both to the port found in Discover.
# Node.js server. Replace APP_ENTRY with the built entry file (e.g. dist/server.js).
# Lockfile other than npm? swap `npm ci` for `pnpm i --frozen-lockfile` /
# `yarn install --immutable` / `bun install --frozen-lockfile`.
# Next.js: see references/stacks/node.md (standalone output, different COPY lines).
ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build --if-present && npm prune --omit=dev

FROM node:${NODE_VERSION}-slim
# tini as PID 1 so SIGTERM reaches node and zombies are reaped.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
ENV NODE_ENV=production PORT=3000
WORKDIR /app
COPY --from=build /app /app
USER 10001:10001
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "APP_ENTRY"]
