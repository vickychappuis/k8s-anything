"""Unit tests for evals/check.py. Stdlib only.

Run: python3 -m unittest discover -s tests -v
Most tests feed synthetic objects straight into the check functions; the end-to-end
test at the bottom needs `kubectl` (for `kubectl kustomize`) and is skipped without it.
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("check", os.path.join(REPO, "evals", "check.py"))
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


# ---------------------------------------------------------------- fixture builders
def deployment(name, labels=None, replicas=None, strategy=None, probes=None, ports=None,
               image=None, mounts=None, env=None, command=None, kind="Deployment"):
    labels = labels or {"app.kubernetes.io/name": name}
    c = {"name": "app", "image": image or name + ":1.0"}
    c.update(probes or {})
    if ports:
        c["ports"] = ports
    if env:
        c["env"] = env
    if command:
        c["command"] = command
    pod = {"metadata": {"labels": labels}, "spec": {"containers": [c]}}
    if mounts:
        c["volumeMounts"] = [{"name": "v%d" % i, "mountPath": p} for i, p in enumerate(mounts)]
        pod["spec"]["volumes"] = [{"name": "v%d" % i, "emptyDir": {}} for i in range(len(mounts))]
    spec = {"selector": {"matchLabels": labels}, "template": pod}
    if replicas is not None:
        spec["replicas"] = replicas
    if strategy:
        spec["strategy"] = {"type": strategy}
    return {"apiVersion": "apps/v1", "kind": kind, "metadata": {"name": name}, "spec": spec}


def job(name, kind="Job"):
    pod = {"metadata": {"labels": {"app.kubernetes.io/name": name}},
           "spec": {"restartPolicy": "Never", "containers": [{"name": "m", "image": "x:1"}]}}
    if kind == "CronJob":
        return {"kind": "CronJob", "metadata": {"name": name},
                "spec": {"schedule": "* * * * *", "jobTemplate": {"spec": {"template": pod}}}}
    return {"kind": "Job", "metadata": {"name": name}, "spec": {"template": pod}}


def service(name, selector, target=None):
    port = {"name": "http", "port": 80}
    if target is not None:
        port["targetPort"] = target
    return {"kind": "Service", "metadata": {"name": name},
            "spec": {"selector": selector, "ports": [port]}}


def hpa(name, target, kind="Deployment"):
    return {"kind": "HorizontalPodAutoscaler", "metadata": {"name": name},
            "spec": {"scaleTargetRef": {"kind": kind, "name": target}, "maxReplicas": 3}}


def pdb(name, selector):
    return {"kind": "PodDisruptionBudget", "metadata": {"name": name},
            "spec": {"minAvailable": 1, "selector": selector}}


NS = {"kind": "Namespace", "metadata": {"name": "ns"}}
READY = {"readinessProbe": {"httpGet": {"path": "/healthz", "port": "http"}}}
HTTP_PORT = [{"name": "http", "containerPort": 8080}]


def run_overlay(exp, objs, ov="prod"):
    ck = check.Checker()
    check.check_overlay(ck, exp, ov, objs)
    return ck


def statuses(ck, needle):
    return [r["status"] for r in ck.results if needle in r["name"]]


class Base(unittest.TestCase):
    def assertStatus(self, ck, needle, status):
        got = statuses(ck, needle)
        self.assertTrue(got, "no check matching %r in %s" % (needle, [r["name"] for r in ck.results]))
        self.assertEqual(set(got), {status}, "%r: %s" % (needle, ck.results))


# ---------------------------------------------------------------------- rendering
def have_kubectl():
    try:
        return subprocess.run(["kubectl", "version", "--client"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


# Real `kubectl kustomize` output shapes that a hand-written YAML subset parser got
# wrong or crashed on: block indentation indicators (|2-), |+ chomping, single-quoted
# and double-quoted scalars wrapped over lines, explicit '? ' keys for long keys,
# '---' inside block scalars, quoted keys.
TRICKY_YAML = """apiVersion: v1
data:
  dq: "\\tword0 word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11
    word12 SECRET_KEY word14"
  keep: |+
    end


  lead: |2-
      two leading spaces
    none
  literal: |
    a
    ---
    b: c
  sq: 'a: word0 word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11
    word12 it''s'
  ? xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  : longkey
  "yes": "no"
kind: ConfigMap
metadata:
  name: tricky
---
apiVersion: v1
kind: List
items:
- apiVersion: v1
  kind: Namespace
  metadata:
    name: n
"""


class RenderTest(Base):
    def test_decode_json_stream(self):
        self.assertEqual(check.decode_json_stream(' {"a": 1}\n{"b": [2]}\n\n'),
                         [{"a": 1}, {"b": [2]}])
        self.assertEqual(check.decode_json_stream(""), [])
        with self.assertRaises(ValueError):
            check.decode_json_stream('{"a": 1} {')

    def test_empty_render_is_no_objects(self):
        self.assertEqual(check.to_objects("  \n"), [])

    @unittest.skipUnless(have_kubectl(), "kubectl not installed")
    def test_tricky_yaml_decoded_exactly(self):
        objs = check.to_objects(TRICKY_YAML)
        self.assertEqual([check.kind_of(o) for o in objs], ["ConfigMap", "Namespace"])
        data = objs[0]["data"]
        self.assertEqual(data["dq"], "\tword0 word1 word2 word3 word4 word5 word6 word7 word8 "
                                     "word9 word10 word11 word12 SECRET_KEY word14")
        self.assertEqual(data["keep"], "end\n\n\n")
        self.assertEqual(data["lead"], "  two leading spaces\nnone")
        self.assertEqual(data["literal"], "a\n---\nb: c\n")
        self.assertTrue(data["sq"].endswith("word12 it's"))
        self.assertEqual(data["x" * 131], "longkey")
        self.assertEqual(data["yes"], "no")
        self.assertNotIn("annotations", objs[0]["metadata"], "no-op annotate must leave no trace")

    @unittest.skipUnless(have_kubectl(), "kubectl not installed")
    def test_undecodable_yaml_raises(self):
        with self.assertRaises(check.RenderError):
            check.to_objects("a: [unclosed\n")


# ------------------------------------------------------------------- Dockerfiles
class DockerfileTest(Base):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.app)

    def write(self, rel, text):
        p = os.path.join(self.app, rel)
        if os.path.dirname(rel):
            os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def run_df(self, exp, prod_objs=None):
        ck = check.Checker()
        check.check_dockerfiles(ck, exp, self.app, prod_objs)
        return ck

    def test_good_dockerfile(self):
        self.write("Dockerfile", "FROM python:3.12 AS b\nUSER root\nFROM python:3.12-slim\nUSER 10001:10001\n")
        self.write(".dockerignore", ".git\n")
        ck = self.run_df({})
        self.assertTrue(all(r["status"] == "pass" for r in ck.results), ck.results)

    def test_root_latest_missing_ignore(self):
        self.write("Dockerfile", "FROM node:latest\nUSER 10001\nFROM node:22\nUSER node\n")
        ck = self.run_df({})
        self.assertStatus(ck, "non-root USER", "fail")
        self.assertStatus(ck, ":latest", "fail")
        self.assertStatus(ck, ".dockerignore", "fail")

    def test_untagged_base_is_latest(self):
        self.write("Dockerfile", "FROM python AS build\nFROM build\nUSER 1000\n")
        self.assertStatus(self.run_df({}), ":latest", "fail")
        self.write("Dockerfile", "FROM --platform=$BUILDPLATFORM golang:1.23 AS b\n"
                                 "FROM localhost:5000/team/base:1.2\nFROM b\nFROM scratch\n"
                                 "FROM alpine@sha256:abc\nFROM ${BASE}\nUSER 1000\n")
        self.assertStatus(self.run_df({}), ":latest", "pass")
        self.write("Dockerfile", "FROM localhost:5000/team/base\nUSER 1000\n")
        self.assertStatus(self.run_df({}), ":latest", "fail")

    def test_multiple_dockerfiles(self):
        self.write("cmd/api/Dockerfile", "FROM golang:1.23\nUSER 65532\n")
        self.write("cmd/worker/Dockerfile", "FROM golang:1.23\n")
        self.write("cmd/api/.dockerignore", "x\n")
        ck = self.run_df({"dockerfiles": ["cmd/api/Dockerfile", "cmd/worker/Dockerfile"]})
        self.assertEqual(check.Checker.status(ck, "cmd/api/Dockerfile runs as numeric non-root USER"), "pass")
        self.assertEqual(check.Checker.status(ck, "cmd/worker/Dockerfile runs as numeric non-root USER"), "fail")
        self.assertEqual(check.Checker.status(ck, ".dockerignore for cmd/api/Dockerfile"), "pass")
        self.assertEqual(check.Checker.status(ck, ".dockerignore for cmd/worker/Dockerfile"), "fail")
        missing = self.run_df({"dockerfiles": ["nope/Dockerfile"]})
        self.assertStatus(missing, "nope/Dockerfile exists", "fail")

    def test_forbidden_cmd_in_dockerfile_or_prod_command(self):
        self.write("Dockerfile", "FROM python:3.12\nUSER 1000\nCMD [\"gunicorn\"]\n")
        exp = {"forbidden_cmd_patterns": [r"manage\.py\s+runserver"]}
        self.assertStatus(self.run_df(exp), "dev server", "pass")
        bad = deployment("web", command=["python", "manage.py", "runserver"])
        self.assertStatus(self.run_df(exp, [bad]), "dev server", "fail")

    def test_build_args_keys(self):
        self.write("Dockerfile", "FROM node:22\nARG NEXT_PUBLIC_API_URL\nUSER 1001\n")
        ck = self.run_df({"build_args_keys": ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_*", "NEXT_PUBLIC_GA_ID"]})
        self.assertEqual(ck.status("build arg NEXT_PUBLIC_API_URL declared (ARG)"), "pass")
        self.assertEqual(ck.status("build arg NEXT_PUBLIC_* declared (ARG)"), "pass")
        self.assertEqual(ck.status("build arg NEXT_PUBLIC_GA_ID declared (ARG)"), "fail")


class UnchangedTest(Base):
    def test_unchanged_files(self):
        app = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, app)
        shutil.copy(os.path.join(REPO, "examples/flask-redis/app.py"), app)
        with open(os.path.join(app, "requirements.txt"), "w") as f:
            f.write("changed\n")
        ck = check.Checker()
        check.check_unchanged(ck, {"source": "examples/flask-redis",
                                   "unchanged_files": ["app.py", "requirements.txt", "gone.py"]}, app)
        self.assertEqual(ck.status("source unchanged: app.py"), "pass")
        self.assertEqual(ck.status("source unchanged: requirements.txt"), "fail")
        self.assertEqual(ck.status("source unchanged: gone.py"), "fail")


# ---------------------------------------------------------------------- services
WEB = {"name": "web", "kind": "web", "health_path": "/healthz", "port": 8080}


class ServicesTest(Base):
    def good_objs(self):
        lab_web = {"app.kubernetes.io/name": "web"}
        lab_beat = {"app.kubernetes.io/name": "beat"}
        return [
            NS,
            deployment("web", probes=READY, ports=HTTP_PORT),
            service("web", lab_web, "http"),
            hpa("web", "web"),
            pdb("web", {"matchLabels": lab_web}),
            deployment("worker", probes={"livenessProbe": {"exec": {"command": ["true"]}}}),
            deployment("beat", labels=lab_beat, replicas=1, strategy="Recreate"),
            job("migrate"),
            job("cleanup", kind="CronJob"),
        ]

    EXP = {"services": [WEB, {"name": "worker", "kind": "worker"},
                        {"name": "beat", "kind": "singleton"},
                        {"name": "migrate", "kind": "job"},
                        {"name": "cleanup", "kind": "cronjob"}]}

    def test_all_good(self):
        ck = run_overlay(self.EXP, self.good_objs())
        failed = [r for r in ck.results if r["status"] != "pass"
                  and "NetworkPolicy" not in r["name"]]
        self.assertEqual(failed, [])

    def mutate(self, name, fn):
        objs = self.good_objs()
        for o in objs:
            if check.name_of(o) == name and o["kind"] in check.WORKLOAD_KINDS:
                fn(o)
        return objs

    def test_web_wrong_readiness_path(self):
        objs = self.mutate("web", lambda o: o["spec"]["template"]["spec"]["containers"][0]
                           .update({"readinessProbe": {"httpGet": {"path": "/"}}}))
        self.assertStatus(run_overlay(self.EXP, objs), "web web: readiness", "fail")

    def test_web_without_service(self):
        objs = [o for o in self.good_objs() if o["kind"] != "Service"]
        self.assertStatus(run_overlay(self.EXP, objs), "Service targets port", "fail")
        exp = {"services": [{"name": "web", "kind": "web"}]}
        self.assertStatus(run_overlay(exp, objs), "has a Service", "fail")

    def test_web_service_wrong_port(self):
        objs = self.good_objs()
        objs[2] = service("web", {"app.kubernetes.io/name": "web"}, 9999)
        self.assertStatus(run_overlay(self.EXP, objs), "Service targets port 8080", "fail")
        objs[2] = service("web", {"app.kubernetes.io/name": "web"}, 8080)
        self.assertStatus(run_overlay(self.EXP, objs), "Service targets port 8080", "pass")

    def test_worker_with_service_and_http_probe(self):
        objs = self.mutate("worker", lambda o: o["spec"]["template"]["spec"]["containers"][0]
                           .update(READY))
        objs.append(service("worker", {"app.kubernetes.io/name": "worker"}))
        ck = run_overlay(self.EXP, objs)
        self.assertStatus(ck, "worker worker: no Service", "fail")
        self.assertStatus(ck, "worker worker: no HTTP probes", "fail")

    def test_worker_with_tcp_or_grpc_probe(self):
        for probe in ({"tcpSocket": {"port": 8080}}, {"grpc": {"port": 9090}}):
            objs = self.mutate("worker", lambda o: o["spec"]["template"]["spec"]["containers"][0]
                               .update({"livenessProbe": probe}))
            self.assertStatus(run_overlay(self.EXP, objs), "worker worker: no HTTP probes", "fail")

    def test_singleton_with_hpa_fails(self):
        objs = self.good_objs() + [hpa("beat", "beat")]
        ck = run_overlay(self.EXP, objs)
        self.assertStatus(ck, "beat: not targeted by an HPA", "fail")
        # and the HPA'd singleton sets replicas, so the HPA check fails too
        self.assertStatus(ck, "HPA beat owns replicas", "fail")

    def test_singleton_selected_by_pdb_fails(self):
        objs = self.good_objs() + [pdb("all", {})]  # empty selector = every pod
        self.assertStatus(run_overlay(self.EXP, objs), "beat: not selected by a PDB", "fail")
        objs = self.good_objs() + [pdb("other", {"matchExpressions": [
            {"key": "app.kubernetes.io/name", "operator": "In", "values": ["beat"]}]})]
        self.assertStatus(run_overlay(self.EXP, objs), "beat: not selected by a PDB", "fail")

    def test_singleton_replicas_and_strategy(self):
        objs = self.mutate("beat", lambda o: o["spec"].update(replicas=2, strategy={"type": "RollingUpdate"}))
        ck = run_overlay(self.EXP, objs)
        self.assertStatus(ck, "beat: replicas 1", "fail")
        self.assertStatus(ck, "beat: strategy Recreate", "fail")
        objs = self.mutate("beat", lambda o: o["spec"].pop("strategy"))
        self.assertStatus(run_overlay(self.EXP, objs), "beat: strategy Recreate", "fail")

    def test_job_wrong_kind_and_missing(self):
        objs = [o for o in self.good_objs() if check.name_of(o) not in ("migrate", "cleanup")]
        objs.append(deployment("migrate"))
        ck = run_overlay(self.EXP, objs)
        self.assertStatus(ck, "job migrate is a Job", "fail")
        self.assertStatus(ck, "cronjob cleanup is a CronJob", "fail")

    def test_name_prefix_and_component_label_match(self):
        objs = self.good_objs()
        for o in objs:
            if o["kind"] != "Namespace":
                o["metadata"]["name"] = "acme-" + o["metadata"]["name"]
        for o in objs:
            if o["kind"] == "HorizontalPodAutoscaler":
                o["spec"]["scaleTargetRef"]["name"] = "acme-web"
        ck = run_overlay(self.EXP, objs)
        self.assertStatus(ck, "is a", "pass")
        comp = deployment("x", labels={"app": "x"})
        comp["metadata"]["labels"] = {"app.kubernetes.io/component": "worker"}
        self.assertIs(check.find_workload([comp], {"name": "worker", "kind": "worker"}), comp)

    def test_overlays_restriction(self):
        exp = {"services": [{"name": "migrate", "kind": "job", "overlays": ["prod"]}]}
        ck = run_overlay(exp, [NS], ov="dev")
        self.assertEqual(statuses(ck, "migrate"), [])

    def test_unknown_kind(self):
        ck = run_overlay({"services": [{"name": "x", "kind": "daemon"}]}, [NS])
        self.assertStatus(ck, "known kind", "fail")

    def test_hpa_target_with_replicas_or_missing(self):
        objs = [NS, deployment("web", replicas=3), hpa("web", "web"), hpa("ghost", "ghost")]
        ck = run_overlay({}, objs)
        self.assertStatus(ck, "HPA web owns replicas", "fail")
        self.assertStatus(ck, "HPA ghost owns replicas", "fail")
        ck = run_overlay({}, [NS, deployment("web"), hpa("web", "web")])
        self.assertStatus(ck, "HPA web owns replicas", "pass")


# -------------------------------------------------------- overlay-level checks
class OverlayTest(Base):
    def test_legacy_readiness(self):
        exp = {"health_path": "/healthz"}
        self.assertStatus(run_overlay(exp, [NS, deployment("a", probes=READY)]), "readiness on", "pass")
        self.assertStatus(run_overlay(exp, [NS, deployment("a")]), "readiness on", "fail")

    def test_namespace_pdb_netpol(self):
        ck = run_overlay({}, [deployment("a")])
        self.assertStatus(ck, "has Namespace", "fail")
        self.assertStatus(ck, "PodDisruptionBudget", "fail")
        self.assertStatus(ck, "NetworkPolicy", "fail")
        self.assertEqual(statuses(run_overlay({}, [NS], ov="dev"), "PodDisruptionBudget"), [])

    def test_secret_keys(self):
        exp = {"secret_or_dropped_keys": ["SECRET_KEY"]}
        cm = {"kind": "ConfigMap", "metadata": {"name": "c"}, "data": {"SECRET_KEY": "x"}}
        self.assertStatus(run_overlay(exp, [NS, cm]), "not in any ConfigMap", "fail")
        envd = deployment("a", env=[{"name": "SECRET_KEY", "value": "x"}])
        self.assertStatus(run_overlay(exp, [NS, envd]), "not in any ConfigMap", "fail")
        ref = deployment("a", env=[{"name": "SECRET_KEY", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}])
        self.assertStatus(run_overlay(exp, [NS, ref]), "not in any ConfigMap", "pass")
        sec = {"kind": "Secret", "metadata": {"name": "s"}, "stringData": {"SECRET_KEY": "x"}}
        self.assertStatus(run_overlay(exp, [NS, sec]), "no inlined Secret", "fail")
        self.assertStatus(run_overlay(exp, [NS, sec], ov="dev"), "not in any ConfigMap", "pass")

    def test_dev_only_images(self):
        exp = {"dev_only_images": ["redis"]}
        r = deployment("redis", image="docker.io/library/redis:7-alpine")
        self.assertStatus(run_overlay(exp, [NS, r], ov="dev"), "redis image present", "pass")
        self.assertStatus(run_overlay(exp, [NS, r], ov="prod"), "redis image absent", "fail")
        self.assertStatus(run_overlay(exp, [NS, deployment("a", image="redis-exporter:1")]),
                          "redis image absent", "pass")

    def test_required_emptydir_paths(self):
        exp = {"services": [{"name": "web", "kind": "web"}, {"name": "worker", "kind": "worker"}],
               "required_emptydir_paths": ["/tmp"]}
        objs = [NS, deployment("web", mounts=["/tmp"]), deployment("worker")]
        ck = run_overlay(exp, objs)
        self.assertEqual(ck.status("prod: web emptyDir at /tmp"), "pass")
        self.assertEqual(ck.status("prod: worker emptyDir at /tmp"), "fail")
        exp2 = {"required_emptydir_paths": {"web": ["/tmp", "/app/.next/cache"]}}
        ck = run_overlay(exp2, objs)
        self.assertEqual(ck.status("prod: web emptyDir at /app/.next/cache"), "fail")
        # a hostPath/configMap volume at the path is not an emptyDir
        d = deployment("web")
        d["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] = [{"name": "c", "mountPath": "/tmp"}]
        d["spec"]["template"]["spec"]["volumes"] = [{"name": "c", "configMap": {"name": "x"}}]
        ck = run_overlay({"required_emptydir_paths": ["/tmp"]}, [NS, d])
        self.assertStatus(ck, "emptyDir at /tmp", "fail")


    def test_required_emptydir_respects_service_overlays(self):
        exp = {"services": [{"name": "web", "kind": "web", "overlays": ["prod"]}],
               "required_emptydir_paths": ["/tmp"]}
        ck = run_overlay(exp, [NS], ov="dev")
        self.assertEqual(statuses(ck, "emptyDir"), [])
        self.assertStatus(run_overlay(exp, [NS], ov="prod"), "web emptyDir at /tmp", "fail")

    def test_empty_overlay_is_still_checked(self):
        ck = check.run_checks({"source": "x", "services": [{"name": "web"}]}, "/nonexistent",
                              validate=False, renderer=lambda path: ([], ""))
        self.assertEqual(ck.status("overlay prod builds"), "pass")
        self.assertEqual(ck.status("prod: has Namespace"), "fail")
        self.assertEqual(ck.status("prod: web web is a Deployment/StatefulSet"), "fail")
        self.assertFalse(ck.summary()["ok"])


class SchemaTest(Base):
    def test_valid(self):
        with open(os.path.join(REPO, "evals", "flask-redis", "expect.json")) as f:
            self.assertEqual(check.schema_errors(json.load(f)), [])
        self.assertEqual(check.schema_errors({"source": "x", "_comment": "ok", "services": [
            {"name": "w", "kind": "worker", "overlays": ["prod"]}],
            "required_emptydir_paths": {"w": ["/tmp"]}, "weights": {"report": 2}}), [])

    def test_typos_and_bad_types_are_errors(self):
        bad = {"secret_keys": ["X"], "overlays": "prod", "weights": {"reprot": 1},
               "forbidden_cmd_patterns": ["("],
               "services": [{"name": "a", "knd": "worker"}, {"kind": "web"},
                            {"name": "a", "kind": "daemon"}]}
        errs = "\n".join(check.schema_errors(bad))
        for needle in ("'source'", "unknown key 'secret_keys'", "'overlays' must be",
                       "'weights'", "bad regex", "unknown field 'knd'", "services[1] needs",
                       "kind must be one of", "unique"):
            self.assertIn(needle, errs)

    def test_main_rejects_invalid_expect(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "expect.json"), "w") as f:
            json.dump({"source": "examples/x", "secret_keys": ["SECRET_KEY"]}, f)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main([d, d]), 2)
        self.assertIn("secret_keys", err.getvalue())


class ReportTest(Base):
    def test_report(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        ck = check.Checker()
        check.check_report(ck, {"report_mentions": ["redis"]}, d)
        self.assertStatus(ck, "K8S_REPORT.md exists", "fail")
        with open(os.path.join(d, "K8S_REPORT.md"), "w") as f:
            f.write("# Evidence\napp.py:3 uses Redis\n## Assumptions\n## Open questions\n"
                    "## Checklist\n## Validation\n")
        ck = check.Checker()
        check.check_report(ck, {"report_mentions": ["redis", "celery"]}, d)
        self.assertEqual([r["name"] for r in ck.results if r["status"] == "fail"],
                         ["report mentions 'celery'"])


# --------------------------------------------------------------- score & output
class ScoreTest(Base):
    def test_weighted_score_and_skip(self):
        ck = check.Checker({"report": 1, "security": 3})
        ck.check("a", True, category="security")
        ck.check("b", False, category="report")
        ck.skip("c", "not run", category="validation")
        s = ck.summary()
        self.assertEqual((s["passed"], s["failed"], s["skipped"], s["total"]), (1, 1, 1, 2))
        self.assertEqual(s["score"], 75.0)
        self.assertFalse(s["ok"])
        only_skip = check.Checker()
        only_skip.skip("x", "y")
        self.assertFalse(only_skip.summary()["ok"], "nothing ran must not count as success")

    def test_weights_override(self):
        ck = check.Checker({"report": 10})
        ck.check("r", True, category="report")
        self.assertEqual(ck.results[0]["weight"], 10)


@unittest.skipUnless(have_kubectl(), "kubectl not installed")
class EndToEndTest(Base):
    """Render a tiny kustomize tree with kubectl and run main() on it."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.app = os.path.join(self.root, "app")
        self.ev = os.path.join(self.root, "eval")
        base = os.path.join(self.app, "deploy", "k8s", "base")
        os.makedirs(base)
        os.makedirs(self.ev)
        files = {
            "Dockerfile": "FROM python:3.12-slim\nUSER 10001\n",
            ".dockerignore": ".git\n",
            "deploy/k8s/K8S_REPORT.md": "# Evidence\nproc:1\n# Assumptions\n# Open questions\n"
                                        "# Checklist\n# Validation\n",
            "deploy/k8s/base/kustomization.yaml": "resources:\n- beat.yaml\n",
            "deploy/k8s/base/beat.yaml": json.dumps(deployment("beat", replicas=1, strategy="Recreate")),
        }
        for ov in ("dev", "prod"):
            files["deploy/k8s/overlays/%s/kustomization.yaml" % ov] = (
                "namespace: x-%s\nresources:\n- ../../base\n- ns.yaml\n" % ov
                + ("- hpa.yaml\n" if ov == "prod" else ""))
            files["deploy/k8s/overlays/%s/ns.yaml" % ov] = "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: x-%s\n" % ov
        files["deploy/k8s/overlays/prod/hpa.yaml"] = json.dumps(
            dict(hpa("beat", "beat"), apiVersion="autoscaling/v2"))
        for rel, text in files.items():
            p = os.path.join(self.app, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        with open(os.path.join(self.ev, "expect.json"), "w") as f:
            json.dump({"source": "examples/none", "services": [{"name": "beat", "kind": "singleton"}]}, f)

    def test_json_output_flags_singleton_with_hpa(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check.main(["--json", "--no-validate", self.ev, self.app])
        out = json.loads(buf.getvalue())
        self.assertEqual(rc, 1)
        by = {r["name"]: r["status"] for r in out["checks"]}
        self.assertEqual(by["overlay prod builds"], "pass")
        self.assertEqual(by["dev: singleton beat: not targeted by an HPA"], "pass")
        self.assertEqual(by["prod: singleton beat: not targeted by an HPA"], "fail")
        self.assertEqual(by["k8sa-validate PASS (exit 0)"], "skip")
        self.assertEqual(out["skipped"], 1)
        self.assertLess(out["score"], 100)

    def test_broken_overlay_fails(self):
        with open(os.path.join(self.app, "deploy/k8s/overlays/dev/kustomization.yaml"), "a") as f:
            f.write("- missing.yaml\n")
        ck = check.run_checks({"services": []}, self.app, validate=False)
        self.assertEqual(ck.status("overlay dev builds"), "fail")
        self.assertEqual(ck.status("overlay prod builds"), "pass")



@unittest.skipUnless(have_kubectl(), "kubectl not installed")
class NegativeFixturesTest(Base):
    """A bad run, rendered by real kubectl: every planted defect must FAIL its check."""

    def test_bad_manifests_fail(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        web = deployment("web", replicas=3, ports=HTTP_PORT, image="acme/web:latest",
                         env=[{"name": "SECRET_KEY", "value": "hunter2"}])  # no readiness
        worker = deployment("worker", probes={"readinessProbe": {"tcpSocket": {"port": 8080}}})
        beat = deployment("beat", replicas=2)  # RollingUpdate by default
        cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "cfg"},
              "data": {"settings.env": "DEBUG=0\nSECRET_KEY=hunter2\n"}}
        res = [dict(o, apiVersion="apps/v1") for o in (web, worker, beat)] + [
            cm, dict(service("web", {"app.kubernetes.io/name": "web"}, "http"), apiVersion="v1"),
            dict(hpa("web", "web"), apiVersion="autoscaling/v2"),
            dict(hpa("beat", "beat"), apiVersion="autoscaling/v2"),
            {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "bad"}}]
        files = {"Dockerfile": "FROM python\nUSER 10001\nCMD flask run\n",
                 ".dockerignore": "x\n",
                 "deploy/k8s/overlays/prod/res.yaml": "\n---\n".join(json.dumps(o) for o in res),
                 "deploy/k8s/overlays/prod/kustomization.yaml": "resources:\n- res.yaml\n"}
        for rel, text in files.items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        exp = {"source": "examples/none", "overlays": ["prod"], "health_path": "/healthz",
               "forbidden_cmd_patterns": [r"flask\s+run"], "secret_or_dropped_keys": ["SECRET_KEY"],
               "services": [{"name": "web", "kind": "web"}, {"name": "worker", "kind": "worker"},
                            {"name": "beat", "kind": "singleton"}]}
        self.assertEqual(check.schema_errors(exp), [])
        ck = check.run_checks(exp, root, validate=False)
        self.assertEqual(ck.status("overlay prod builds"), "pass")
        for name in ("Dockerfile: no :latest base images",
                     "doesn't run dev server (flask\\s+run)",
                     "prod: web web: readiness on /healthz",
                     "prod: worker worker: no HTTP probes",
                     "prod: singleton beat: replicas 1",
                     "prod: singleton beat: strategy Recreate",
                     "prod: singleton beat: not targeted by an HPA",
                     "prod: HPA web owns replicas (no replicas field on Deployment/web)",
                     "prod: SECRET_KEY not in any ConfigMap",
                     "prod: has PodDisruptionBudget"):
            self.assertEqual(ck.status(name), "fail", name)
        self.assertFalse(ck.summary()["ok"])


if __name__ == "__main__":
    unittest.main()
