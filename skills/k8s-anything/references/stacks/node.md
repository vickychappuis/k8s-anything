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
- Check `next.config.*` for `output: 'standalone'` first.
  - **Present** → runtime stage copies `.next/standalone` → `./`, `.next/static` →
    `.next/static`, and `public/`; `CMD ["node", "server.js"]`. Set
    `ENV HOSTNAME=0.0.0.0`: in a pod `HOSTNAME` is the pod name, and standalone
    `server.js` binds to it.
  - **Absent** → `.next/standalone` doesn't exist; don't copy it. Adding the option
    is a source change (propose it: much smaller image). Until approved, run
    `next start` from production deps: build stage `npm run build && npm prune
    --omit=dev && rm -rf .next/cache`; runtime copies `package.json`,
    `next.config.*`, `node_modules`, `public/`, `.next`; `CMD ["node",
    "node_modules/next/dist/bin/next", "start", "-H", "0.0.0.0"]` (not `npm start`:
    npm in the signal path). `next start` reads `PORT` and ignores `HOSTNAME`.
- `readOnlyRootFilesystem` → `emptyDir` at `/app/.next/cache` (ISR / image
  optimization) in both modes.
- `NEXT_PUBLIC_*` are inlined by `next build` into client **and** server bundles →
  a setting on the pod does nothing. In the build stage: `ARG NEXT_PUBLIC_X` +
  `ENV NEXT_PUBLIC_X=${NEXT_PUBLIC_X}` before `npm run build`; one image per
  environment. Keep them out of ConfigMaps; flag it in the report. Never put a
  secret in a `NEXT_PUBLIC_*` var.
- Server-only env (no prefix) is read at runtime only in dynamic code (route
  handlers, pages using `connection()`/`cookies()`/`headers()` or `dynamic =
  'force-dynamic'`). A statically prerendered page freezes the value at build —
  check before promising runtime config.
- `ENV NEXT_TELEMETRY_DISABLED=1` in build and runtime stages.

**Health:** often missing → propose `/healthz` (source change).

**Resources:** `100m / 128Mi`, limit `512Mi`; `NODE_OPTIONS=--max-old-space-size=384`
(≈75% of the limit).
