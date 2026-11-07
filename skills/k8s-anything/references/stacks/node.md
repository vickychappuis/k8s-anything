# Node.js / TypeScript

**Detect:** `package.json`. Framework from deps: `next`, `express`, `fastify`, `@nestjs/core`, `hono`, `remix`, `nuxt`.

**Port:** `process.env.PORT` usually; defaults — Express/Fastify: whatever's in code,
Next.js `3000`, NestJS `3000`. Check for `localhost` binds (Fastify defaults to
`127.0.0.1` → must pass `host: '0.0.0.0'`).

**Build:** respect the lockfile (`package-lock.json` → `npm ci`, `pnpm-lock.yaml` →
`pnpm i --frozen-lockfile`, `yarn.lock`, `bun.lockb`). Monorepo (turbo/nx) → build
context is repo root, use `turbo prune --docker` / `pnpm deploy`.

**Next.js:** set `output: 'standalone'` and copy `.next/standalone` + `.next/static` +
`public`. `NEXT_PUBLIC_*` vars are baked at build time → build args, not runtime env (flag this).

**Runtime image:** `node:<lts>-slim` or `gcr.io/distroless/nodejs<lts>-debian12`.
`NODE_ENV=production`. Node handles SIGTERM only if the app does — check for
`process.on('SIGTERM')`; otherwise use `tini` or `--init`.

**Health:** often missing — propose `/healthz` returning 200.

**Resources:** `100m / 128Mi` request, `512Mi` limit. Set `--max-old-space-size` ≈ 75% of the memory limit.
