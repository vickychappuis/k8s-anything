# Static sites, PHP, Ruby, .NET, Rust

**Static SPA (Vite/CRA/Astro static):** build stage → `nginxinc/nginx-unprivileged`
(port 8080, non-root). SPA fallback: `try_files $uri /index.html`. Runtime config can't
use env vars directly → inject a `config.js` via ConfigMap mount.

**PHP (Laravel/Symfony):** `docker init` supports PHP; typical split is php-fpm +
nginx (two containers in one pod or `serversideup/php` all-in-one). Laravel:
`php artisan migrate` as a Job, queue worker as its own Deployment, scheduler as CronJob
running `schedule:run` every minute.

**Ruby (Rails):** Rails 7.1+ ships a production Dockerfile — use it. `db:migrate` as a
Job, Sidekiq as worker Deployment. Health: Rails 7.1 `/up`.

**.NET:** `docker init` supports it; `mcr.microsoft.com/dotnet/aspnet` runtime, port
`8080` by default in .NET 8+ images (`ASPNETCORE_HTTP_PORTS`), runs as `app` user.

**Rust:** `cargo-chef` for dependency caching; runtime distroless/cc or static musl.

**Procfile apps (Heroku-style):** each process type → one workload (web → Deployment +
Service, worker → Deployment, release → Job). Buildpacks (`pack`) reproduce the Heroku build.
