"""Per-service output for monorepos, multi-binary repos, compose and Procfiles."""
import json

from .support import DetectCase

SERVICE_KEYS = ["name", "path", "sources", "kind", "stack", "frameworks", "dockerfile",
                "ports", "evidence"]


def pkg(deps=None, scripts=None):
    return json.dumps({"name": "x", "dependencies": deps or {}, "scripts": scripts or {}})


class Monorepo(DetectCase):
    def test_apps_and_packages(self):
        out = self.detect({
            "package.json": json.dumps({"private": True, "workspaces": ["apps/*", "packages/*"]}),
            "apps/web/package.json": pkg({"next": "14"}, {"start": "next start -p 3001"}),
            "apps/web/Dockerfile": "FROM node\nEXPOSE 3001\n",
            "apps/api/package.json": pkg({"express": "4"}),
            "apps/api/src/server.ts": "app.listen(process.env.PORT || 4000)\n",
            "apps/jobs/package.json": pkg({"bullmq": "5"}, {"start": "node worker.js"}),
            "packages/ui/package.json": pkg({"react": "18"}),
            "apps/README.md": "not a service",
        })
        self.assertEqual([s["path"] for s in out["services"]],
                         ["apps/api", "apps/jobs", "apps/web", "packages/ui"])
        for s in out["services"]:
            self.assertEqual(list(s), SERVICE_KEYS)
            self.assertEqual(s["sources"], ["workspace"])
            self.assertEqual(s["stack"], "node")

        web = self.service(out, "apps/web")
        self.assertEqual((web["name"], web["kind"], web["frameworks"], web["dockerfile"]),
                         ("web", "web", ["next"], "apps/web/Dockerfile"))
        self.assertEqual(self.ports(web), ["3001"])
        self.assertIn({"port": "3001", "evidence": "apps/web/Dockerfile:2"}, web["ports"])
        self.assertIn({"port": "3001", "evidence": "apps/web/package.json:1"}, web["ports"])

        api = self.service(out, "apps/api")
        self.assertEqual((api["kind"], api["frameworks"], api["dockerfile"]), ("web", ["express"], None))
        self.assertEqual(api["ports"], [])

        jobs = self.service(out, "apps/jobs")
        self.assertEqual(jobs["kind"], "worker")
        self.assertEqual(self.service(out, "packages/ui")["kind"], "unknown")
        # top-level stays an aggregate
        self.assertEqual(out["frameworks"], ["express", "next"])

    def test_services_dir_mixed_stacks(self):
        out = self.detect({
            "services/py/requirements.txt": "fastapi\nuvicorn\n",
            "services/py/Dockerfile": "EXPOSE 8000\n",
            "services/go/go.mod": "module x\nrequire github.com/go-chi/chi/v5 v5.0.0\n",
            "services/empty/README.md": "",
        })
        self.assertEqual([(s["path"], s["stack"]) for s in out["services"]],
                         [("services/go", "go"), ("services/py", "python")])
        py = self.service(out, "services/py")
        self.assertEqual((py["kind"], py["frameworks"]), ("web", ["fastapi", "uvicorn"]))


class GoCommands(DetectCase):
    def test_cmd_binaries(self):
        out = self.detect({
            "go.mod": "module x\nrequire github.com/gin-gonic/gin v1.9.1\n",
            "cmd/api/main.go": ('package main\nimport "github.com/gin-gonic/gin"\n'
                                'func main() { r := gin.Default(); r.Run(":8080") }\n'),
            "cmd/worker/main.go": "package main\nfunc main() { consume() }\n",
            "cmd/migrate/main.go": "package main\nfunc main() {}\n",
            "cmd/lib/util.go": "package lib\n",
            "Dockerfile.api": "FROM golang\nEXPOSE 8080\n",
        })
        self.assertEqual([s["path"] for s in out["services"]],
                         ["cmd/api", "cmd/migrate", "cmd/worker"])
        api = self.service(out, "cmd/api")
        self.assertEqual((api["name"], api["kind"], api["stack"], api["frameworks"], api["dockerfile"]),
                         ("api", "web", "go", ["gin"], "Dockerfile.api"))
        self.assertIn({"port": "8080", "evidence": "cmd/api/main.go:3"}, api["ports"])
        self.assertIn({"port": "8080", "evidence": "Dockerfile.api:2"}, api["ports"])
        self.assertEqual(api["sources"], ["go-cmd"])
        self.assertEqual(self.service(out, "cmd/worker")["kind"], "worker")
        mig = self.service(out, "cmd/migrate")
        self.assertEqual((mig["kind"], mig["frameworks"], mig["dockerfile"]), ("unknown", [], None))

    def test_net_http(self):
        out = self.detect({
            "go.mod": "module x\n",
            "cmd/srv/main.go": 'package main\nimport "net/http"\nfunc main() { http.ListenAndServe(":9000", nil) }\n',
        })
        srv = self.service(out, "cmd/srv")
        self.assertEqual((srv["kind"], self.ports(srv)), ("web", ["9000"]))


class ComposeServices(DetectCase):
    def test_build_contexts(self):
        out = self.detect({
            "docker-compose.yml": (
                "services:\n"
                "  api:\n    build: ./api\n    ports:\n      - \"8000:8000\"\n"
                "  worker:\n    build: ./api\n    command: celery -A app worker -l info\n"
                "  front:\n    build:\n      context: ./web\n      dockerfile: Dockerfile.prod\n"
                "    expose:\n      - \"3000\"\n"
                "  db:\n    image: postgres:16\n    ports:\n      - 5432:5432\n"),
            "api/requirements.txt": "django\ncelery\n",
            "api/Dockerfile": "EXPOSE 8000\n",
            "web/package.json": pkg({"vite": "5"}),
            "web/Dockerfile.prod": "FROM nginx\n",
        })
        self.assertEqual([(s["name"], s["path"]) for s in out["services"]],
                         [("api", "api"), ("worker", "api"), ("front", "web")])
        api = self.service(out, "api", "api")
        self.assertEqual((api["kind"], api["stack"], api["frameworks"], api["dockerfile"]),
                         ("web", "python", ["celery", "django"], "api/Dockerfile"))
        self.assertIn({"port": "8000", "evidence": "docker-compose.yml:5"}, api["ports"])
        self.assertIn({"port": "8000", "evidence": "api/Dockerfile:1"}, api["ports"])
        self.assertEqual(api["sources"], ["compose"])
        self.assertIn("docker-compose.yml:2", api["evidence"])
        worker = self.service(out, "api", "worker")
        self.assertEqual(worker["kind"], "worker")
        self.assertEqual(worker["ports"], [{"port": "8000", "evidence": "api/Dockerfile:1"}])
        front = self.service(out, "web")
        self.assertEqual((front["kind"], front["dockerfile"], self.ports(front)),
                         ("web", "web/Dockerfile.prod", ["3000"]))

    def test_compose_in_subdir_and_merge_with_workspace(self):
        out = self.detect({
            "ops/compose.yaml": "services:\n  api:\n    build:\n      context: ../apps/api\n",
            "apps/api/package.json": pkg({"fastify": "4"}),
            "apps/admin/package.json": pkg({"next": "14"}),
        })
        self.assertEqual([(s["name"], s["path"], s["sources"]) for s in out["services"]],
                         [("admin", "apps/admin", ["workspace"]),
                          ("api", "apps/api", ["compose", "workspace"])])

    def test_build_flow_mapping(self):
        out = self.detect({
            "compose.yml": "services:\n  api:\n    build: {context: ./api, dockerfile: Dockerfile.dev}\n",
            "api/requirements.txt": "flask\n",
            "api/Dockerfile.dev": "EXPOSE 5000\n",
        })
        api = self.service(out, "api", "api")
        self.assertEqual((api["dockerfile"], api["stack"], self.ports(api)),
                         ("api/Dockerfile.dev", "python", ["5000"]))

    def test_command_ports_and_exec_form(self):
        out = self.detect({
            "compose.yml": (
                "services:\n"
                "  a:\n    build: ./api\n"
                "    command: [\"gunicorn\", \"--bind\", \"0.0.0.0:9000\", \"app:app\"]\n"
                "  b:\n    build: ./api\n    command:\n      - uvicorn\n      - main:app\n"
                "      - --port=7000\n"),
            "api/requirements.txt": "flask\n",
        })
        a = self.service(out, "api", "a")
        self.assertEqual((a["kind"], a["ports"]),
                         ("web", [{"port": "9000", "evidence": "compose.yml:4"}]))
        b = self.service(out, "api", "b")
        self.assertEqual((b["kind"], b["ports"]),
                         ("web", [{"port": "7000", "evidence": "compose.yml:7"}]))

    def test_worker_flags_do_not_make_a_worker(self):
        out = self.detect({
            "compose.yml": ("services:\n  api:\n    build: .\n"
                            "    command: gunicorn app:app --worker-class gevent -b 0.0.0.0:8000\n"),
            "requirements.txt": "flask\n",
        })
        self.assertEqual(self.service(out, ".", "api")["kind"], "web")

    def test_build_context_outside_root_or_remote(self):
        out = self.detect({
            "compose.yml": ("services:\n  a:\n    build: ../elsewhere\n"
                            "  b:\n    build: https://github.com/x/y.git#main\n"),
        })
        self.assertEqual([(s["name"], s["path"]) for s in out["services"]],
                         [("a", "../elsewhere"), ("b", "https://github.com/x/y.git#main")])
        self.assertEqual(out["services"][0]["stack"], None)


class ProcfileServices(DetectCase):
    def test_processes(self):
        out = self.detect({
            "requirements.txt": "flask\ncelery\n",
            "Procfile": ("web: gunicorn app:app --bind 0.0.0.0:$PORT\n"
                         "worker: celery -A app worker\nrelease: flask db upgrade\n"
                         "clock: python clock.py\n"),
        })
        self.assertEqual([s["name"] for s in out["services"]], ["web", "worker", "release", "clock"])
        web = self.service(out, ".", "web")
        self.assertEqual((web["kind"], web["stack"], web["frameworks"], web["sources"]),
                         ("web", "python", ["celery", "flask"], ["procfile"]))
        self.assertEqual(web["ports"], [{"port": "$PORT", "evidence": "Procfile:1"}])
        self.assertEqual(self.service(out, ".", "worker")["kind"], "worker")
        self.assertEqual(self.service(out, ".", "release")["kind"], "unknown")
        self.assertEqual(self.service(out, ".", "release")["ports"], [])

    def test_web_with_worker_class_flag(self):
        out = self.detect({
            "requirements.txt": "fastapi\n",
            "Procfile": ("web: gunicorn main:app --worker-class=uvicorn.workers.UvicornWorker "
                         "--bind 0.0.0.0:$PORT\nworker: python -m rq.cli worker\n"),
        })
        self.assertEqual(self.service(out, ".", "web")["kind"], "web")
        self.assertEqual(self.service(out, ".", "worker")["kind"], "worker")

    def test_procfile_in_subdirectory(self):
        out = self.detect({"backend/Procfile": "web: bundle exec puma -p 5000\n",
                           "backend/Gemfile": "gem 'rails'\n"})
        web = self.service(out, "backend", "web")
        self.assertEqual((web["stack"], web["frameworks"], self.ports(web)), ("ruby", ["rails"], ["5000"]))
        self.assertEqual(web["evidence"], ["backend/Procfile:1"])


class SingleApp(DetectCase):
    def test_root_app_is_one_service(self):
        out = self.detect({"package.json": pkg({"express": "4"}), "Dockerfile": "EXPOSE 3000\n"})
        self.assertEqual(len(out["services"]), 1)
        s = out["services"][0]
        self.assertEqual((s["name"], s["path"], s["sources"], s["kind"], s["dockerfile"]),
                         ("app", ".", ["root"], "web", "Dockerfile"))
        self.assertEqual(s["ports"], [{"port": "3000", "evidence": "Dockerfile:1"}])

    def test_no_stack_no_service(self):
        self.assertEqual(self.detect({"README.md": "hi"})["services"], [])

    def test_crlf_everywhere(self):
        out = self.detect({
            "docker-compose.yml": "services:\r\n  api:\r\n    build: ./api\r\n    ports:\r\n      - \"80:8000\"\r\n",
            "api/requirements.txt": "fastapi\r\n",
            "api/Procfile": "web: uvicorn main:app --port 8000\r\n",
        })
        api = self.service(out, "api", "api")
        self.assertEqual((api["kind"], api["frameworks"], self.ports(api)), ("web", ["fastapi"], ["8000"]))
        self.assertIn({"port": "8000", "evidence": "api/Procfile:1"}, self.service(out, "api", "web")["ports"])
