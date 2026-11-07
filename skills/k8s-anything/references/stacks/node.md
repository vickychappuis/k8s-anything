# Node.js / TypeScript

**Detect:** `package.json`. Frameworks: `next`, `express`, `fastify`, `@nestjs/core`,
`hono`, `nuxt`, `react-router` (v7, formerly Remix), `astro`.

**Template:** `assets/dockerfiles/node.Dockerfile` (tini as PID 1, UID 10001).

**Port & bind:** usually `process.env.PORT`. Defaults: Next.js/NestJS `3000`.
Fastify binds `127.0.0.1` unless `host: '0.0.0.0'` — that's a source change; check
for an env override first.

**Lockfiles:** `package-lock.json` → `npm ci`; `pnpm-lock.yaml` → `pnpm i
--frozen-lockfile`; `yarn.lock` → `yarn install --immutable`; `bun.lock` (text, Bun
1.2+) or legacy `bun.lockb` → `bun install --frozen-lockfile`. Monorepo (turbo/nx/pnpm
workspaces): build context is the repo root; use `turbo prune --docker` or `pnpm deploy`.

**Signals:** Node as PID 1 ignores SIGTERM unless the app handles it. Run under tini
(baked into the image). `docker run --init` has no effect in Kubernetes.

**Next.js:**
- `output: 'standalone'` in `next.config.*`; runtime stage copies
  `.next/standalone`, `.next/static` → `.next/static`, and `public/`; `CMD ["node", "server.js"]`.
- Set `ENV HOSTNAME=0.0.0.0`: in a pod `HOSTNAME` is the pod name, and standalone
  `server.js` binds to it.
- `readOnlyRootFilesystem` → `emptyDir` at `/app/.next/cache` (ISR / image optimization).
- `NEXT_PUBLIC_*` are inlined at build time → build args per environment, not runtime
  env. Flag it.

**Health:** often missing → propose `/healthz` (source change).

**Resources:** `100m / 128Mi`, limit `512Mi`; `NODE_OPTIONS=--max-old-space-size=384`
(≈75% of the limit).
