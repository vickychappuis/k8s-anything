"""Procfiles, env files, existing k8s/Helm/Kustomize, walking, and output robustness."""
import json
import os

from .support import DetectCase

TOP_LEVEL_KEYS = [
    "path", "stacks", "frameworks", "dockerfiles", "expose_ports", "compose_files",
    "compose_services", "compose_container_ports", "procfiles", "procfile_processes",
    "env_files", "env_keys", "existing_helm_charts", "existing_kustomizations",
    "existing_k8s_manifests", "existing_deploy_dir",
]


class Procfiles(DetectCase):
    def test_root_and_subdirectory(self):
        out = self.detect({
            "Procfile": "web: gunicorn app:app\r\nworker: celery -A app worker\r\n# x: y\r\n",
            "services/api/Procfile": "release: ./migrate\nweb: node server.js\n",
        })
        self.assertEqual(out["procfiles"], ["Procfile", "services/api/Procfile"])
        self.assertEqual(out["procfile_processes"], ["release", "web", "worker"])

    def test_procfile_variants_not_matched(self):
        out = self.detect({"Procfile.dev": "web: x\n", "docs/Procfile.md": "web: x\n"})
        self.assertEqual(out["procfiles"], [])


class EnvFiles(DetectCase):
    def test_env_files_and_keys(self):
        out = self.detect({
            ".env": "A=1\r\nexport B=2\r\n# C=3\r\n  D = 4\r\n",
            ".env.example": "E=\n",
            "config/prod.env": "F=x\n",
            ".envrc": "G=1\n",
            "environment.yml": "H=1\n",
        })
        self.assertEqual(out["env_files"], [".env", ".env.example", "config/prod.env"])
        self.assertEqual(out["env_keys"], ["A", "B", "D", "E", "F"])


class ExistingK8s(DetectCase):
    def test_helm_kustomize_and_manifests(self):
        out = self.detect({
            "charts/app/Chart.yaml": "apiVersion: v2\nname: app\n",
            "charts/app/templates/deploy.yaml": "apiVersion: apps/v1\nkind: Deployment\n",
            "k8s/kustomization.yaml": "resources: [svc.yaml]\n",
            "k8s/svc.yaml": "apiVersion: v1\nkind: Service # comment\n",
            "k8s/quoted.yml": 'apiVersion: batch/v1\nkind: "CronJob"\r\n',
            "k8s/multi.yaml": "---\nkind: ConfigMap\n---\napiVersion: apps/v1\nkind: StatefulSet\n",
            "other/Kustomization": "resources: []\n",
            "other/not.yaml": "spec:\n  kind: Deployment\n",
        })
        self.assertEqual(out["existing_helm_charts"], ["charts/app/Chart.yaml"])
        self.assertEqual(out["existing_kustomizations"], ["k8s/kustomization.yaml", "other/Kustomization"])
        self.assertEqual(out["existing_k8s_manifests"],
                         ["charts/app/templates/deploy.yaml", "k8s/multi.yaml", "k8s/quoted.yml", "k8s/svc.yaml"])
        self.assertEqual(out["existing_deploy_dir"], [])

    def test_root_deploy_dir_reported_separately(self):
        out = self.detect({"deploy/k8s/base/deployment.yaml": "kind: Deployment\n"})
        self.assertEqual(out["existing_deploy_dir"], ["deploy"])
        self.assertEqual(out["existing_k8s_manifests"], [])

    def test_nested_deploy_dir_is_scanned(self):
        out = self.detect({"apps/api/deploy/deployment.yaml": "kind: Deployment\n"})
        self.assertEqual(out["existing_deploy_dir"], [])
        self.assertEqual(out["existing_k8s_manifests"], ["apps/api/deploy/deployment.yaml"])


class Walking(DetectCase):
    def test_empty_dir(self):
        out = self.detect({})
        self.assertEqual(list(out), TOP_LEVEL_KEYS + ["services"])
        for k in TOP_LEVEL_KEYS[1:]:
            self.assertEqual(out[k], [], k)
        self.assertEqual(out["services"], [])

    def test_pruned_dirs(self):
        out = self.detect({"node_modules/express/package.json": '{"dependencies":{"next":"1"}}',
                           ".venv/lib/requirements.txt": "flask\n",
                           "vendor/go.mod": "module x\n"})
        self.assertEqual(out["stacks"], [])

    def test_max_depth(self):
        out = self.detect({"a/b/c/d/package.json": "{}", "a/b/c/d/e/go.mod": "module x\n"})
        self.assertEqual(out["stacks"], ["node"])

    def test_paths_with_spaces_and_quotes(self):
        files = {
            'my app/sub "dir"/package.json': '{"dependencies": {"express": "4"}}',
            "it's here/Dockerfile": "EXPOSE 8080\n",
            "a\\b/requirements.txt": "flask\n",
        }
        out = self.detect(files, sub='root with "quotes" & spaces')
        self.assertTrue(out["path"].endswith('root with "quotes" & spaces'))
        self.assertEqual(out["stacks"], ["node", "python"])
        self.assertEqual(out["frameworks"], ["express", "flask"])
        self.assertEqual(out["dockerfiles"], ["it's here/Dockerfile"])

    def test_non_utf8_content_and_filename(self):
        root = os.path.join(self.tmp, "app")
        os.makedirs(root)
        try:
            open(os.path.join(os.fsencode(root), b"bad\xffname.env"), "wb").close()
        except OSError:  # some filesystems refuse non-UTF-8 names (APFS does)
            pass
        out = self.detect({"requirements.txt": b"flask\n\xff\xfe\n", ".env": b"K=\xff\n"})
        self.assertEqual(out["frameworks"], ["flask"])
        self.assertIn("K", out["env_keys"])

    def test_big_file_skipped(self):
        out = self.detect({"requirements.txt": "flask\n" + "#" * 1_100_000})
        self.assertEqual(out["stacks"], ["python"])
        self.assertEqual(out["frameworks"], [])

    def test_fifo_does_not_hang(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo")
        root = os.path.join(self.tmp, "app")
        os.makedirs(root)
        os.mkfifo(os.path.join(root, "requirements.txt"))
        os.mkfifo(os.path.join(root, ".env"))
        out = self.detect({})
        self.assertEqual(out["stacks"], ["python"])

    def test_symlink_loop(self):
        root = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(root, "a"))
        os.symlink("..", os.path.join(root, "a", "loop"))
        os.symlink("missing", os.path.join(root, "package.json"))
        out = self.detect({"a/go.mod": "module x\n"})
        self.assertEqual(out["stacks"], ["go", "node"])


class Cli(DetectCase):
    def test_not_a_directory(self):
        r = self.run_cli(os.path.join(self.tmp, "nope"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")
        self.assertIn(b"not a directory", r.stderr)

    def test_output_is_ascii_json(self):
        out_raw = self.run_cli(self.tmp).stdout
        out_raw.decode("ascii")
        json.loads(out_raw)

    def test_example_app(self):
        from .support import REPO
        r = self.run_cli(os.path.join(REPO, "examples", "flask-redis"))
        out = json.loads(r.stdout)
        self.assertEqual(out["frameworks"], ["flask"])
        self.assertEqual(out["compose_container_ports"], ["5000"])
        web = self.service(out, ".", "web")
        self.assertEqual(web["kind"], "web")
        self.assertEqual(web["stack"], "python")
        self.assertEqual(self.ports(web), ["5000"])
        self.assertEqual([s["name"] for s in out["services"]], ["web"])
