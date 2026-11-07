# Example: django-celery

A tiny Heroku-style Django + Celery app: a `Procfile` with `web`, `worker`, `beat` and
`release` processes, config from env (`SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`,
`ALLOWED_HOSTS`), **no Dockerfile and no docker-compose** — intended as test input
for the Procfile path. A good k8s-anything run should, among other things:

- map each Procfile process to its own workload: `web` → Deployment + Service,
  `worker` → Deployment, `beat` → Deployment, `release` → migration Job
- make `beat` a **singleton**: `replicas: 1`, `strategy: Recreate`, no HPA, no PDB
  (two schedulers would enqueue every periodic task twice)
- notice that beat writes its schedule file `celerybeat-schedule` to the working
  directory (Celery default), which fails under `readOnlyRootFilesystem` → run it
  with `--schedule /tmp/celerybeat-schedule` and an `emptyDir`
- run `release: python manage.py migrate` as a Job, not at web startup
- notice that `DEBUG` defaults to **True** when unset (`mysite/settings.py:6`) and set
  `DEBUG=False` explicitly
- notice that kubelet HTTP probes send the pod IP as `Host`, which Django rejects
  (`DisallowedHost`, 400) unless `ALLOWED_HOSTS` allows it → probe with an explicit
  `Host` header (or a TCP probe) rather than `ALLOWED_HOSTS=*`
- treat `SECRET_KEY`, `DATABASE_URL` and `REDIS_URL` as secrets, `ALLOWED_HOSTS` as config
- keep Postgres and Redis dev-only (in-cluster) and external in prod; don't rely on
  the sqlite fallback (it writes `db.sqlite3` into the working directory and isn't
  shared between pods)
- not add gunicorn at build time: it's already in `requirements.txt`

Try it: copy this folder somewhere, open Claude Code there and run `/k8s-anything:k8sify`.
Score the result with `python3 evals/check.py evals/django-celery <copy>`.
