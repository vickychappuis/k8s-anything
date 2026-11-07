# syntax=docker/dockerfile:1
# Next.js 16 (App Router). Generated from k8s-anything node.Dockerfile template.
# next.config.mjs has no `output: 'standalone'`, so the build emits no standalone
# server: the runtime runs `next start` from production-pruned node_modules (bigger
# image). Adding standalone is a proposed source change — see K8S_REPORT.md.
ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# NEXT_PUBLIC_* is inlined into the client bundle by `next build` (app/api-base.js:5):
# it is fixed per image. Build one image per environment, e.g.
#   docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com .
# Setting it on the pod at runtime has no effect. Never pass secrets here.
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Drop the build cache: at runtime /app/.next/cache is an emptyDir.
RUN npm run build && npm prune --omit=dev && rm -rf .next/cache

FROM node:${NODE_VERSION}-slim
# tini as PID 1 so SIGTERM reaches node and zombies are reaped.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
ENV NODE_ENV=production PORT=3000 NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=build /app/package.json /app/next.config.mjs ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/public ./public
COPY --from=build /app/.next ./.next
USER 10001:10001
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
# `next start` reads PORT (default 3000); -H makes the 0.0.0.0 bind explicit.
CMD ["node", "node_modules/next/dist/bin/next", "start", "-H", "0.0.0.0"]
