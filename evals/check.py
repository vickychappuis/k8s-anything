#!/usr/bin/env python3
"""Score a k8s-anything run against an eval's expectations.

Usage: evals/check.py [--json] [--quiet] [--no-validate] <eval-dir> <app-dir-after-run>
       evals/check.py --print-source <eval-dir>
  <eval-dir>  contains expect.json (schema: evals/README.md)
  <app-dir>   the target app after the agent ran (Dockerfile(s), deploy/k8s/)

Checks properties, not an exact diff: agent output is not deterministic, but a good
run must satisfy every expectation. Exit 0 if no check fails, 1 otherwise (2 on a
usage error). Skipped checks (--no-validate) are reported as SKIP, never as PASS.

Stdlib only. Needs `kubectl` (offline): `kubectl kustomize` renders each overlay and
`kubectl annotate --local -o json` turns the YAML into JSON with kubectl's own
decoder, so checks work on structure, not on regexes over text and not on a
hand-written YAML parser. Runs bin/k8sa-validate from this repo.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATE = os.path.join(REPO, "bin", "k8sa-validate")

KINDS = ("web", "worker", "singleton", "job", "cronjob")
WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "Pod")
EXPECTED_KINDS = {
    "web": ("Deployment", "StatefulSet"),
    "worker": ("Deployment", "StatefulSet"),
    "singleton": ("Deployment", "StatefulSet"),
    "job": ("Job",),
    "cronjob": ("CronJob",),
}
LONG_RUNNING = ("web", "worker", "singleton")
# A worker serves no port, so a probe that connects to one is wrong (exec is fine).
NETWORK_PROBES = ("httpGet", "tcpSocket", "grpc")

# Default weight per check category; expect.json "weights" overrides any of them.
DEFAULT_WEIGHTS = {
    "build": 3,       # overlays render
    "security": 3,    # non-root, secrets, dev-only images
    "services": 3,    # per-service workload shape
    "validation": 3,  # k8sa-validate
    "container": 2,   # Dockerfile hygiene
    "source": 2,      # app source untouched
    "manifests": 2,   # namespace, probes, PDB, NetworkPolicy, HPA
    "report": 1,      # K8S_REPORT.md content
}
REPORT_SECTIONS = ("Evidence", "Assumptions", "Open questions", "Checklist", "Validation")


# ---------------------------------------------------------------------- rendering
# kubectl has no "kustomize -o json". `kubectl annotate --local -o json` decodes the
# rendered YAML with kubectl's own (sigs.k8s.io/yaml) decoder and prints JSON, offline:
# --local never contacts a server, and an empty KUBECONFIG makes sure of it. Removing
# an annotation key nobody uses is the no-op edit it needs; it leaves an empty
# metadata.annotations, which to_objects() drops again.
NOOP_ANNOTATION = "k8sa.invalid/eval-noop-"


def decode_json_stream(text):
    """Concatenated JSON values (kubectl prints one per object) -> list."""
    dec, out, i = json.JSONDecoder(), [], 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return out
        obj, i = dec.raw_decode(text, i)
        out.append(obj)


def _flatten(objs):
    out = []
    for o in objs:
        if isinstance(o, dict) and kind_of(o) == "List" and isinstance(o.get("items"), list):
            out.extend(_flatten(o["items"]))
        elif isinstance(o, dict):
            out.append(o)
    return out


def to_objects(yaml_text):
    """Rendered multi-doc YAML -> list of objects, via kubectl. Raises RenderError."""
    if not yaml_text.strip():
        return []
    fd, kubeconfig = tempfile.mkstemp(prefix="k8sa-eval-kubeconfig-")
    os.close(fd)
    env = dict(os.environ, KUBECONFIG=kubeconfig)
    try:
        r = subprocess.run(["kubectl", "annotate", "--local", "-f", "-", "-o", "json",
                            NOOP_ANNOTATION], input=yaml_text, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, env=env)
    except OSError as e:
        raise RenderError("kubectl not runnable: %s" % e)
    finally:
        os.remove(kubeconfig)
    if r.returncode != 0:
        raise RenderError("kubectl could not decode the rendered YAML: %s" % r.stderr.strip())
    try:
        objs = _flatten(decode_json_stream(r.stdout))
    except ValueError as e:
        raise RenderError("unexpected kubectl output: %s" % e)
    for o in objs:
        md = o.get("metadata")
        if isinstance(md, dict) and md.get("annotations") == {}:
            del md["annotations"]
    return objs


class RenderError(Exception):
    pass


def render(path):
    """kubectl kustomize <path> -> (list of objects, error string)."""
    try:
        r = subprocess.run(["kubectl", "kustomize", path], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
    except OSError as e:
        return None, "kubectl not runnable: %s" % e
    if r.returncode != 0:
        return None, r.stderr.strip()
    try:
        return to_objects(r.stdout), ""
    except RenderError as e:
        return None, str(e)


# ------------------------------------------------------------------ object helpers
def get(obj, *path):
    for p in path:
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list) and isinstance(p, int) and p < len(obj):
            obj = obj[p]
        else:
            return None
    return obj


def kind_of(o):
    return o.get("kind", "") if isinstance(o, dict) else ""


def name_of(o):
    return get(o, "metadata", "name") or ""


def pod_template(o):
    k = kind_of(o)
    if k == "Pod":
        return o
    if k == "CronJob":
        return get(o, "spec", "jobTemplate", "spec", "template") or {}
    return get(o, "spec", "template") or {}


def pod_labels(o):
    return get(pod_template(o), "metadata", "labels") or {}


def containers(o, init=True):
    spec = get(pod_template(o), "spec") or {}
    cs = list(spec.get("containers") or [])
    if init:
        cs += list(spec.get("initContainers") or [])
    return [c for c in cs if isinstance(c, dict)]


def selects(selector, labels):
    """Label-selector semantics. A Service selector is a plain map; a LabelSelector
    has matchLabels/matchExpressions. An empty LabelSelector ({}) selects all."""
    if selector is None:
        return False
    if not isinstance(selector, dict):
        return False
    if "matchLabels" in selector or "matchExpressions" in selector:
        ml = selector.get("matchLabels") or {}
        exprs = selector.get("matchExpressions") or []
    else:
        ml, exprs = selector, []
    if any(str(labels.get(k)) != str(v) for k, v in ml.items()):
        return False
    for e in exprs:
        key, op, vals = e.get("key"), e.get("operator"), [str(v) for v in e.get("values") or []]
        has = key in labels
        if op == "In" and not (has and str(labels[key]) in vals):
            return False
        if op == "NotIn" and has and str(labels[key]) in vals:
            return False
        if op == "Exists" and not has:
            return False
        if op == "DoesNotExist" and has:
            return False
    return True


def services_selecting(objs, w):
    labels = pod_labels(w)
    return [s for s in objs if kind_of(s) == "Service" and get(s, "spec", "selector")
            and selects(get(s, "spec", "selector"), labels)]


def hpas_targeting(objs, w):
    return [h for h in objs if kind_of(h) == "HorizontalPodAutoscaler"
            and get(h, "spec", "scaleTargetRef", "name") == name_of(w)
            and get(h, "spec", "scaleTargetRef", "kind") in (None, kind_of(w))]


def pdbs_selecting(objs, w):
    labels = pod_labels(w)
    return [p for p in objs if kind_of(p) == "PodDisruptionBudget"
            and selects(get(p, "spec", "selector"), labels)]


def image_basename(image):
    image = str(image or "").split("@", 1)[0]
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[0]


def emptydir_mounts(w):
    vols = get(pod_template(w), "spec", "volumes") or []
    empty = {v.get("name") for v in vols if isinstance(v, dict) and "emptyDir" in v}
    return {m.get("mountPath") for c in containers(w) for m in c.get("volumeMounts") or []
            if m.get("name") in empty}


def find_workload(objs, svc):
    """Match a service entry to a rendered workload: exact name, then a
    namePrefix/nameSuffix variant, then the app.kubernetes.io/component label."""
    want = svc.get("workload") or svc["name"]
    expected = EXPECTED_KINDS.get(svc.get("kind"), WORKLOAD_KINDS)
    ws = [o for o in objs if kind_of(o) in WORKLOAD_KINDS]
    ws.sort(key=lambda o: kind_of(o) not in expected)  # right kind first
    for match in (lambda o: name_of(o) == want,
                  lambda o: name_of(o).endswith("-" + want) or name_of(o).startswith(want + "-"),
                  lambda o: get(o, "metadata", "labels", "app.kubernetes.io/component") == want):
        hits = [o for o in ws if match(o)]
        if hits:
            return hits[0]
    return None


# ---------------------------------------------------------------- expect.json schema
STR_LIST_KEYS = ("overlays", "dockerfiles", "forbidden_cmd_patterns", "build_args_keys",
                 "unchanged_files", "secret_or_dropped_keys", "dev_only_images",
                 "report_mentions")
TOP_KEYS = STR_LIST_KEYS + ("source", "prompt", "health_path", "services",
                            "required_emptydir_paths", "weights")
SERVICE_KEYS = ("name", "workload", "kind", "health_path", "port", "overlays")


def _str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def schema_errors(exp):
    """A typo in expect.json must not silently drop checks (a false PASS), so unknown
    keys and wrong types are usage errors. Keys starting with '_' are comments."""
    if not isinstance(exp, dict):
        return ["expect.json must be an object"]
    errs = []
    for k in exp:
        if k not in TOP_KEYS and not k.startswith("_"):
            errs.append("unknown key %r" % k)
    if not isinstance(exp.get("source"), str) or not exp.get("source"):
        errs.append("'source' (string) is required")
    for k in ("prompt", "health_path"):
        if k in exp and not isinstance(exp[k], str):
            errs.append("%r must be a string" % k)
    for k in STR_LIST_KEYS:
        if k in exp and not _str_list(exp[k]):
            errs.append("%r must be a list of strings" % k)
    for pat in exp.get("forbidden_cmd_patterns") or []:
        try:
            re.compile(pat)
        except (re.error, TypeError) as e:
            errs.append("bad regex %r in forbidden_cmd_patterns: %s" % (pat, e))
    w = exp.get("weights", {})
    if not isinstance(w, dict) or any(k not in DEFAULT_WEIGHTS or isinstance(v, bool)
                                      or not isinstance(v, (int, float)) for k, v in w.items()):
        errs.append("'weights' must map categories (%s) to numbers" % ", ".join(DEFAULT_WEIGHTS))
    services = exp.get("services", [])
    if not isinstance(services, list):
        errs.append("'services' must be a list")
        services = []
    names = []
    for i, svc in enumerate(services):
        if not isinstance(svc, dict) or not isinstance(svc.get("name"), str) or not svc["name"]:
            errs.append("services[%d] needs a 'name' string" % i)
            continue
        names.append(svc["name"])
        for k in svc:
            if k not in SERVICE_KEYS and not k.startswith("_"):
                errs.append("services[%d] (%s): unknown field %r" % (i, svc["name"], k))
        if svc.get("kind", "web") not in KINDS:
            errs.append("services[%d] (%s): kind must be one of %s"
                        % (i, svc["name"], ", ".join(KINDS)))
        if "overlays" in svc and not _str_list(svc["overlays"]):
            errs.append("services[%d] (%s): 'overlays' must be a list of strings" % (i, svc["name"]))
    if len(set(names)) != len(names):
        errs.append("service names must be unique")
    req = exp.get("required_emptydir_paths")
    if req is not None:
        if isinstance(req, dict):
            for n, paths in req.items():
                if not _str_list(paths):
                    errs.append("required_emptydir_paths[%r] must be a list of strings" % n)
        elif not _str_list(req):
            errs.append("'required_emptydir_paths' must be a list of strings or a map")
    return errs


# ------------------------------------------------------------------------ checker
class Checker(object):
    def __init__(self, weights=None):
        self.results = []
        self.weights = dict(DEFAULT_WEIGHTS)
        self.weights.update(weights or {})

    def check(self, name, ok, detail="", category="manifests"):
        self.results.append({"name": name, "status": "pass" if ok else "fail",
                             "category": category, "weight": self.weights.get(category, 1),
                             "detail": "" if ok else str(detail or "")})

    def skip(self, name, reason, category="manifests"):
        self.results.append({"name": name, "status": "skip", "category": category,
                             "weight": self.weights.get(category, 1), "detail": reason})

    def summary(self):
        ran = [r for r in self.results if r["status"] != "skip"]
        passed = [r for r in ran if r["status"] == "pass"]
        total_w = sum(r["weight"] for r in ran)
        score = 100.0 * sum(r["weight"] for r in passed) / total_w if total_w else 0.0
        return {"passed": len(passed), "failed": len(ran) - len(passed),
                "skipped": len(self.results) - len(ran), "total": len(ran),
                "score": round(score, 1), "ok": len(passed) == len(ran) and bool(ran)}

    def status(self, name):
        for r in self.results:
            if r["name"] == name:
                return r["status"]
        return None


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except (IOError, OSError):
        return None


def final_stage(df):
    parts = re.split(r"^\s*FROM\s", df, flags=re.M | re.I)
    return parts[-1] if len(parts) > 1 else df


def latest_bases(df):
    """FROM images that resolve to :latest, explicitly or by having no tag. Earlier
    stage names, scratch, digests and ${VAR} images (unknown) are not flagged."""
    stages, bad = set(), []
    for line in re.findall(r"^\s*FROM\s+(.+)$", df, re.M | re.I):
        toks = [t for t in line.split() if not t.startswith("--")]
        if not toks:
            continue
        image = toks[0]
        if len(toks) >= 3 and toks[1].lower() == "as":
            stages.add(toks[2].lower())
        if image.lower() in stages or image == "scratch" or "@" in image or "$" in image:
            continue
        last = image.rsplit("/", 1)[-1]
        if ":" not in last or last.split(":", 1)[1] == "latest":
            bad.append(image)
    return bad


def check_dockerfiles(ck, exp, app, prod_objs=None):
    paths = exp.get("dockerfiles") or ["Dockerfile"]
    texts = []
    for rel in paths:
        df = read(os.path.join(app, rel))
        ck.check("%s exists" % rel, df is not None, category="container")
        df = df or ""
        texts.append(df)
        users = re.findall(r"^\s*USER\s+(\S+)", final_stage(df), re.M | re.I)
        ck.check("%s runs as numeric non-root USER" % rel,
                 users and re.match(r"^[1-9]\d*(:\d+)?$", users[-1]),
                 "USER=%s" % (users[-1] if users else None), category="security")
        bad = latest_bases(df)
        ck.check("%s: no :latest base images" % rel, not bad,
                 "latest or untagged: %s" % ", ".join(bad), category="container")
        d = os.path.dirname(rel)
        ignores = [os.path.join(app, rel + ".dockerignore"), os.path.join(app, d, ".dockerignore"),
                   os.path.join(app, ".dockerignore")]
        ck.check(".dockerignore for %s" % rel if len(paths) > 1 else ".dockerignore exists",
                 any(os.path.exists(p) for p in ignores), category="container")

    # Dev servers must not ship: look at Dockerfiles and prod container commands.
    cmds = []
    for o in prod_objs or []:
        for c in containers(o):
            cmds.append(" ".join(str(x) for x in (c.get("command") or []) + (c.get("args") or [])))
    haystack = "\n".join(texts + cmds)
    for bad in exp.get("forbidden_cmd_patterns", []):
        m = re.search(bad, haystack)
        ck.check("doesn't run dev server (%s)" % bad, not m,
                 "matched %r" % (m.group(0) if m else ""), category="container")

    # Build-time keys (e.g. NEXT_PUBLIC_*) must be ARGs: they are inlined at build.
    args = set(re.findall(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)", "\n".join(texts), re.M | re.I))
    for key in exp.get("build_args_keys", []):
        if key.endswith("*"):
            ok = any(a.startswith(key[:-1]) for a in args)
        else:
            ok = key in args
        ck.check("build arg %s declared (ARG)" % key, ok, "ARGs: %s" % ", ".join(sorted(args)),
                 category="container")


def check_unchanged(ck, exp, app):
    for rel in exp.get("unchanged_files", []):
        orig = os.path.join(REPO, exp.get("source", ""), rel)
        now = os.path.join(app, rel)
        try:
            with open(orig, "rb") as a, open(now, "rb") as b:
                same, detail = a.read() == b.read(), "content differs"
        except (IOError, OSError) as e:
            same, detail = False, str(e)
        ck.check("source unchanged: %s" % rel, same, detail, category="source")


def check_service(ck, ov, objs, svc):
    sname, skind = svc["name"], svc.get("kind", "web")
    label = "%s: %s %s" % (ov, skind, sname)
    if skind not in KINDS:
        ck.check("%s: known kind" % label, False, "kind must be one of %s" % ", ".join(KINDS),
                 category="services")
        return
    if ov not in svc.get("overlays", [ov]):
        return
    w = find_workload(objs, svc)
    expected = EXPECTED_KINDS[skind]
    ck.check("%s is a %s" % (label, "/".join(expected)), w is not None and kind_of(w) in expected,
             "not found" if w is None else "found %s/%s" % (kind_of(w), name_of(w)),
             category="services")
    if w is None or kind_of(w) not in expected:
        return
    probes = [(p, c.get(p)) for c in containers(w, init=False)
              for p in ("readinessProbe", "livenessProbe", "startupProbe") if c.get(p)]

    if skind == "web":
        path = svc.get("health_path")
        ready = [pr for p, pr in probes if p == "readinessProbe"]
        if path:
            ok = any(get(pr, "httpGet", "path") == path for pr in ready)
        else:
            ok = bool(ready)
        ck.check("%s: readiness%s" % (label, " on " + path if path else ""), ok,
                 "readiness paths: %s" % [get(pr, "httpGet", "path") for pr in ready],
                 category="services")
        svcs = services_selecting(objs, w)
        port = svc.get("port")
        if port is None:
            ck.check("%s: has a Service" % label, svcs, "no Service selects its pods",
                     category="services")
        else:
            named = {cp.get("name"): cp.get("containerPort") for c in containers(w, init=False)
                     for cp in c.get("ports") or [] if cp.get("name")}
            def hits(sp):
                tp = sp.get("targetPort", sp.get("port"))
                return tp == port or str(tp) == str(port) or named.get(tp) == port
            ok = any(hits(sp) for s in svcs for sp in get(s, "spec", "ports") or [])
            ck.check("%s: Service targets port %s" % (label, port), ok,
                     "Services: %s" % [name_of(s) for s in svcs], category="services")
    elif skind == "worker":
        svcs = services_selecting(objs, w)
        ck.check("%s: no Service" % label, not svcs,
                 "selected by %s" % [name_of(s) for s in svcs], category="services")
        net = ["%s.%s" % (p, h) for p, pr in probes for h in NETWORK_PROBES if h in pr]
        ck.check("%s: no HTTP probes" % label, not net, "network probes: %s" % net,
                 category="services")
    elif skind == "singleton":
        reps = get(w, "spec", "replicas")
        ck.check("%s: replicas 1" % label, reps in (None, 1), "replicas=%s" % reps,
                 category="services")
        if kind_of(w) == "Deployment":
            strat = get(w, "spec", "strategy", "type") or "RollingUpdate (default)"
            ck.check("%s: strategy Recreate" % label, strat == "Recreate", "strategy=%s" % strat,
                     category="services")
        hpas = hpas_targeting(objs, w)
        ck.check("%s: not targeted by an HPA" % label, not hpas,
                 "HPA %s" % [name_of(h) for h in hpas], category="services")
        pdbs = pdbs_selecting(objs, w)
        ck.check("%s: not selected by a PDB" % label, not pdbs,
                 "PDB %s" % [name_of(p) for p in pdbs], category="services")


def check_overlay(ck, exp, ov, objs):
    kinds = [kind_of(o) for o in objs]
    ck.check("%s: has Namespace" % ov, "Namespace" in kinds)

    services = exp.get("services")
    if services:
        for svc in services:
            s = dict(svc)
            if s.get("kind", "web") == "web" and "health_path" not in s and exp.get("health_path"):
                s["health_path"] = exp["health_path"]
            check_service(ck, ov, objs, s)
    elif exp.get("health_path"):
        path = exp["health_path"]
        ok = any(get(c, "readinessProbe", "httpGet", "path") == path
                 for o in objs for c in containers(o, init=False))
        ck.check("%s: readiness on %s" % (ov, path), ok)

    # Secrets: never in ConfigMaps or plain env values; never inlined in prod Secrets.
    cm_blob = json.dumps([[o.get("data"), o.get("binaryData")] for o in objs
                          if kind_of(o) == "ConfigMap"])
    env_plain = {e.get("name") for o in objs for c in containers(o) for e in c.get("env") or []
                 if isinstance(e, dict) and "value" in e}
    for key in exp.get("secret_or_dropped_keys", []):
        where = []
        if key in cm_blob:
            where.append("ConfigMap")
        if key in env_plain:
            where.append("env value")
        ck.check("%s: %s not in any ConfigMap" % (ov, key), not where, "found in %s" % where,
                 category="security")
    if ov == "prod":
        sec_blob = json.dumps([[o.get("data"), o.get("stringData")] for o in objs
                               if kind_of(o) == "Secret"])
        for key in exp.get("secret_or_dropped_keys", []):
            ck.check("prod: no inlined Secret values for %s" % key, key not in sec_blob,
                     category="security")

    images = {image_basename(c.get("image")) for o in objs for c in containers(o)}
    for img in exp.get("dev_only_images", []):
        want = ov == "dev"
        ck.check("%s: %s image %s" % (ov, img, "present" if want else "absent"),
                 (img in images) == want, "images: %s" % sorted(images), category="security")

    # HPA owns replicas: its target must exist and must not set spec.replicas.
    for h in [o for o in objs if kind_of(o) == "HorizontalPodAutoscaler"]:
        ref = get(h, "spec", "scaleTargetRef") or {}
        tgt = [o for o in objs if name_of(o) == ref.get("name")
               and kind_of(o) == ref.get("kind", kind_of(o)) and kind_of(o) in WORKLOAD_KINDS]
        ok = bool(tgt) and get(tgt[0], "spec", "replicas") is None
        ck.check("%s: HPA %s owns replicas (no replicas field on %s/%s)"
                 % (ov, name_of(h), ref.get("kind"), ref.get("name")), ok,
                 "target not found" if not tgt else "replicas=%s" % get(tgt[0], "spec", "replicas"))

    # Writable paths a read-only root filesystem needs (e.g. /tmp, /app/.next/cache).
    req = exp.get("required_emptydir_paths")
    if req:
        by_name = dict((s["name"], s) for s in services or [])
        if isinstance(req, dict):
            targets = [(n, paths) for n, paths in req.items()]
        else:
            names = [s["name"] for s in services or [] if s.get("kind", "web") in LONG_RUNNING]
            targets = [(n, req) for n in names] or [(None, req)]
        for sname, paths in targets:
            svc = by_name.get(sname) or {"name": sname}
            if ov not in svc.get("overlays", [ov]):
                continue  # service not expected in this overlay
            if sname is None:
                ws = [o for o in objs if kind_of(o) in ("Deployment", "StatefulSet")]
            else:
                w = find_workload(objs, svc)
                ws = [w] if w is not None else []
            for p in paths:
                ok = bool(ws) and all(p in emptydir_mounts(w) for w in ws)
                ck.check("%s: %s emptyDir at %s" % (ov, sname or "workloads", p), ok,
                         "no workload" if not ws else "emptyDir mounts: %s"
                         % sorted(m for w in ws for m in emptydir_mounts(w)), category="security")

    if ov == "prod":
        ck.check("prod: has PodDisruptionBudget", "PodDisruptionBudget" in kinds)
        ck.check("prod: has NetworkPolicy", "NetworkPolicy" in kinds)


def check_report(ck, exp, k8s):
    report = read(os.path.join(k8s, "K8S_REPORT.md"))
    ck.check("K8S_REPORT.md exists", report is not None, category="report")
    report = report or ""
    for section in REPORT_SECTIONS:
        ck.check("report has '%s'" % section,
                 re.search(r"^#+\s*" + section, report, re.M | re.I), category="report")
    ck.check("report cites file:line evidence", re.search(r"\b[\w./-]+\.\w+:\d+", report),
             category="report")
    for word in exp.get("report_mentions", []):
        ck.check("report mentions '%s'" % word, word.lower() in report.lower(), category="report")


def run_checks(exp, app, validate=True, renderer=render):
    ck = Checker(exp.get("weights"))
    k8s = os.path.join(app, "deploy", "k8s")
    rendered, errors = {}, {}
    for ov in exp.get("overlays", ["dev", "prod"]):
        rendered[ov], errors[ov] = renderer(os.path.join(k8s, "overlays", ov))

    check_dockerfiles(ck, exp, app, rendered.get("prod"))
    check_unchanged(ck, exp, app)
    for ov, objs in rendered.items():
        ck.check("overlay %s builds" % ov, objs is not None,
                 (errors[ov] or "")[:200], category="build")
    for ov, objs in rendered.items():
        if objs is not None:  # an overlay that renders nothing still fails its checks
            check_overlay(ck, exp, ov, objs)

    if not validate:
        ck.skip("k8sa-validate PASS (exit 0)", "--no-validate", category="validation")
    elif os.path.isdir(k8s):
        try:
            r = subprocess.run([VALIDATE, k8s], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True)
            detail = "exit=%d%s" % (r.returncode, " (INCONCLUSIVE: no validator ran)"
                                    if r.returncode == 3 else "")
            ck.check("k8sa-validate PASS (exit 0)", r.returncode == 0, detail,
                     category="validation")
        except OSError as e:
            ck.check("k8sa-validate PASS (exit 0)", False, str(e), category="validation")
    else:
        ck.check("k8sa-validate PASS (exit 0)", False, "no deploy/k8s", category="validation")

    check_report(ck, exp, k8s)
    return ck


def print_table(ck, out=sys.stdout):
    width = max(len(r["name"]) for r in ck.results)
    for r in ck.results:
        detail = r["detail"] if r["status"] != "pass" else ""
        out.write(("%s  %s  %s" % (r["status"].upper(), r["name"].ljust(width), detail)).rstrip()
                  + "\n")
    s = ck.summary()
    skipped = ", %d skipped" % s["skipped"] if s["skipped"] else ""
    out.write("\n%d/%d checks passed%s, weighted score %.1f%%\n"
              % (s["passed"], s["total"], skipped, s["score"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score a k8s-anything run against an eval.")
    ap.add_argument("eval_dir")
    ap.add_argument("app_dir", nargs="?")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    ap.add_argument("--no-validate", action="store_true", help="skip k8sa-validate (reported SKIP)")
    ap.add_argument("--print-source", action="store_true", help="print expect.json 'source' and exit")
    a = ap.parse_args(argv)

    try:
        with open(os.path.join(a.eval_dir, "expect.json")) as f:
            exp = json.load(f)
    except (IOError, OSError, ValueError) as e:
        sys.stderr.write("cannot read expect.json: %s\n" % e)
        return 2
    errs = schema_errors(exp)
    if errs:
        sys.stderr.write("invalid expect.json:\n" + "".join("  - %s\n" % e for e in errs))
        return 2
    if a.print_source:
        print(exp.get("source", ""))
        return 0
    if not a.app_dir:
        ap.error("app_dir is required")

    ck = run_checks(exp, os.path.abspath(a.app_dir), validate=not a.no_validate,
                    renderer=render)
    s = ck.summary()
    if a.json:
        json.dump(dict(s, eval=os.path.basename(os.path.abspath(a.eval_dir)),
                       app=os.path.abspath(a.app_dir), checks=ck.results), sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif a.quiet:
        print("%d/%d %.1f%%" % (s["passed"], s["total"], s["score"]))
    else:
        print_table(ck)
    return 0 if s["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
