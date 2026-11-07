# Static sites, PHP, Ruby, .NET, Rust, Procfile apps

**Static SPA (Vite, CRA, Astro static):** build stage → `nginxinc/nginx-unprivileged`
(port 8080, UID 101 → set `runAsUser: 101`). SPA fallback `try_files $uri /index.html`.
Read-only root FS needs `emptyDir` at `/tmp` and `/var/cache/nginx`. Runtime config
can't come from env → mount a `config.js` from a ConfigMap.

**PHP (Laravel / Symfony):** `docker init` supports PHP. php-fpm + nginx (two
containers in one pod) or an all-in-one image (`serversideup/php`). Laravel:
`php artisan migrate` as a Job, queue worker as its own Deployment, scheduler as a
CronJob running `schedule:run` every minute. Writable: `storage/`, `bootstrap/cache`.

**Ruby (Rails 7.1+):** use the Dockerfile Rails generates. It runs as UID **1000** →
set `runAsUser/runAsGroup/fsGroup: 1000`. Writable paths for a read-only root FS:
`/rails/tmp`, `/rails/log` (or `RAILS_LOG_TO_STDOUT`), and bootsnap's cache under
`tmp/`. `db:migrate` as a Job; Sidekiq as a worker Deployment. Health: `/up`.

**.NET 8+:** `mcr.microsoft.com/dotnet/aspnet` listens on `8080`
(`ASPNETCORE_HTTP_PORTS`) and has a non-root `app` user, UID **1654** → set
`runAsUser: 1654` (or `USER $APP_UID` in the Dockerfile).

**Rust:** `cargo-chef` for dependency caching; runtime `gcr.io/distroless/cc-debian12`
(or static musl + `distroless/static`).

**Procfile apps (Heroku-style):** each process type → one workload: `web` →
Deployment + Service, `worker` → Deployment, `release` → Job. Buildpacks (`pack`)
reproduce the Heroku build.
