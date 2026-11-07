# Example: nextjs-app

A tiny Next.js (App Router) app with **no Dockerfile** and a config that is fine on
a laptop but has the usual container pitfalls — intended as test input. A good
k8s-anything run should, among other things:

- generate a hardened multi-stage Dockerfile (non-root, tini, no `next dev`)
- notice there is **no `output: 'standalone'`** in `next.config.mjs` and either run
  `next start` from pruned `node_modules` or propose the one-line source change —
  not silently copy `.next/standalone` that the build never produces
- not assume the standalone `HOSTNAME` pitfall applies: `next start` ignores
  `HOSTNAME` and listens on all interfaces (`-H` sets it); only standalone `server.js`
  binds to `$HOSTNAME`, which in a pod is the pod name
- mount an `emptyDir` at `/app/.next/cache` so `readOnlyRootFilesystem` works
- flag `NEXT_PUBLIC_API_BASE_URL` as **build-time only** (inlined into the client
  bundle by `next build`, app/api-base.js) → a Docker build arg per environment, not a
  ConfigMap value that silently does nothing
- treat `API_SECRET` (app/api/secure/route.js) as a secret, `GREETING` (app/page.js,
  read per request) as runtime config
- use `/api/health` for probes

Try it: copy this folder somewhere, open Claude Code there and run `/k8s-anything:k8sify`.
Score the result with `python3 evals/check.py evals/nextjs-app <copy>`.
