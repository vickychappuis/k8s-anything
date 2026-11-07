#!/usr/bin/env python3
"""Score a k8s-anything run against an eval's expectations.

Usage: evals/check.py [--json] [--quiet] [--no-validate] <eval-dir> <app-dir-after-run>
       evals/check.py --print-source <eval-dir>
  <eval-dir>  contains expect.json (schema: evals/README.md)
  <app-dir>   the target app after the agent ran (Dockerfile(s), deploy/k8s/)

Checks properties, not an exact diff: agent output is not deterministic, but a good
run must satisfy every expectation. Exit 0 if no check fails, 1 otherwise (2 on a
usage error). Skipped checks (--no-validate) are reported as SKIP, never as PASS.

Stdlib only. Needs `kubectl` for `kubectl kustomize`; the rendered YAML (kustomize's
normalized block style) is parsed by the small parser below, so checks work on
structure, not on regexes over text. Runs bin/k8sa-validate from this repo.
"""
import argparse
import json
import os
import re
import subprocess
import sys

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


# --------------------------------------------------------------------------- YAML
class YAMLError(ValueError):
    pass


def _strip_comment(s):
    """Drop a trailing ' # comment' that is outside quotes."""
    quote = None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s


def _scalar(s):
    s = _strip_comment(s.strip())
    if s.startswith("!") and " " in s:  # tags such as !!str, !!binary
        s = s.split(" ", 1)[1].strip()
    if not s:
        return None
    if s[0] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    if s[0] == "'":
        return s[1:-1].replace("''", "'")
    if s == "{}":
        return {}
    if s == "[]":
        return []
    if s[0] == "[" and s[-1] == "]":
        return [_scalar(p) for p in _split_flow(s[1:-1])]
    if s[0] == "{" and s[-1] == "}":
        out = {}
        for p in _split_flow(s[1:-1]):
            k, _, v = p.partition(":")
            out[_scalar(k)] = _scalar(v)
        return out
    if s in ("null", "~", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if re.match(r"^[-+]?(0|[1-9]\d*)$", s):
        return int(s)
    if re.match(r"^[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?$", s):
        return float(s)
    return s


def _split_flow(s):
    parts, depth, quote, cur = [], 0, None, ""
    for c in s:
        if quote:
            quote = None if c == quote else quote
        elif c in "\"'":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += c
    if cur.strip():
        parts.append(cur)
    return parts


def _split_key(content):
    """Return (key, rest) if content is a mapping entry, else None."""
    if content[0] in "\"'":
        q = content[0]
        end = content.find(q, 1)
        while q == '"' and end > 0 and content[end - 1] == "\\":
            end = content.find(q, end + 1)
        if end < 0 or not content[end + 1:].lstrip().startswith(":"):
            return None
        key = _scalar(content[:end + 1])
        rest = content[end + 1:].lstrip()[1:]
        return str(key), rest.strip()
    if content[0] in "[{":
        return None
    m = re.match(r"^([^#]*?)\s*:(?:\s+(.*))?$", content)
    if not m or not m.group(1):
        return None
    return m.group(1), (m.group(2) or "").strip()


class _Parser(object):
    """Block-style YAML subset: what `kubectl kustomize` emits (maps, sequences at
    the same or deeper indent, plain/quoted/block scalars, empty flow {} and [],
    simple flow collections). No anchors or merge keys."""

    def __init__(self, text):
        self.lines = text.replace("\t", "  ").split("\n")
        self.i = 0

    def _skip(self):
        while self.i < len(self.lines):
            s = self.lines[self.i].strip()
            if s and not s.startswith("#"):
                return True
            self.i += 1
        return False

    def _cur(self):
        line = self.lines[self.i]
        return len(line) - len(line.lstrip(" ")), line.strip()

    def parse(self):
        if not self._skip():
            return None
        ind, content = self._cur()
        if _split_key(content) is None and not self._is_seq(content):
            self.i += 1
            return _scalar(content)
        node = self._node(ind)
        if self._skip():
            raise YAMLError("unexpected content at line %d: %r" % (self.i + 1, self.lines[self.i]))
        return node

    @staticmethod
    def _is_seq(content):
        return content == "-" or content.startswith("- ")

    def _node(self, ind):
        _, content = self._cur()
        return self._seq(ind) if self._is_seq(content) else self._map(ind)

    def _seq(self, ind):
        out = []
        while self._skip():
            cind, content = self._cur()
            if cind != ind or not self._is_seq(content):
                if cind > ind:
                    raise YAMLError("bad indentation at line %d" % (self.i + 1))
                break
            rest = content[1:].lstrip()
            if not rest or rest.startswith("#"):
                self.i += 1
                out.append(self._child(ind, allow_same=False))
            elif self._is_seq(rest) or _split_key(rest) is not None:
                # "- key: v" -> re-read the line as a map (or nested seq) indented
                # where its first key starts.
                new_ind = ind + (len(content) - len(rest))
                self.lines[self.i] = " " * new_ind + rest
                out.append(self._node(new_ind))
            else:
                self.i += 1
                out.append(self._value(rest, ind))
        return out

    def _map(self, ind):
        out = {}
        while self._skip():
            cind, content = self._cur()
            if cind != ind or self._is_seq(content):
                if cind > ind:
                    raise YAMLError("bad indentation at line %d" % (self.i + 1))
                break
            kv = _split_key(content)
            if kv is None:
                raise YAMLError("expected 'key:' at line %d: %r" % (self.i + 1, content))
            key, rest = kv
            self.i += 1
            if not rest or rest.startswith("#"):
                out[key] = self._child(ind, allow_same=True)
            else:
                out[key] = self._value(rest, ind)
        return out

    def _child(self, ind, allow_same):
        if not self._skip():
            return None
        cind, content = self._cur()
        if cind > ind or (allow_same and cind == ind and self._is_seq(content)):
            return self._node(cind)
        return None

    def _value(self, rest, ind):
        if rest[0] in "|>":
            return self._block_scalar(rest, ind)
        if rest[0] == '"' and not re.search(r'(?<!\\)"\s*(#.*)?$', rest[1:]):
            return self._multiline_quoted(rest)
        if rest[0] not in "\"'[{":
            # plain scalar folded over several more-indented lines
            while self.i < len(self.lines):
                line = self.lines[self.i]
                s = line.strip()
                lind = len(line) - len(line.lstrip(" "))
                if not s or lind <= ind or s.startswith("#"):
                    break
                rest += " " + s
                self.i += 1
        return _scalar(rest)

    def _multiline_quoted(self, first):
        buf = first
        while self.i < len(self.lines):
            s = self.lines[self.i].strip()
            self.i += 1
            buf = buf[:-1] if buf.endswith("\\") else buf + " "
            buf += s
            if re.search(r'(?<!\\)"\s*$', s):
                break
        return _scalar(buf)

    def _block_scalar(self, header, ind):
        chomp = "-" if "-" in header else ("+" if "+" in header else "")
        folded = header[0] == ">"
        raw = []
        block_ind = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip():
                lind = len(line) - len(line.lstrip(" "))
                if lind <= ind:
                    break
                if block_ind is None:
                    block_ind = lind
                raw.append(line[block_ind:] if lind >= block_ind else line.strip())
            else:
                raw.append("")
            self.i += 1
        while raw and raw[-1] == "" and chomp != "+":
            raw.pop()
        text = (" " if folded else "\n").join(raw)
        return text if chomp == "-" else text + "\n"


def parse_yaml(text):
    return _Parser(text).parse()


def parse_yaml_docs(text):
    docs = []
    for chunk in re.split(r"^---[ \t]*(?:#.*)?$", text, flags=re.M):
        doc = parse_yaml(chunk)
        if doc is not None:
            docs.append(doc)
    return docs


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
        return [d for d in parse_yaml_docs(r.stdout) if isinstance(d, dict)], ""
    except YAMLError as e:
        return None, "could not parse kustomize output: %s" % e


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
        ck.check("%s: no :latest base images" % rel,
                 not re.search(r"^\s*FROM\s+(--\S+\s+)*\S+:latest\b", df, re.M | re.I),
                 category="container")
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
        http = [p for p, pr in probes if "httpGet" in pr]
        ck.check("%s: no HTTP probes" % label, not http, "httpGet in %s" % http,
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
        if isinstance(req, dict):
            targets = [(n, paths) for n, paths in req.items()]
        else:
            names = [s["name"] for s in services or [] if s.get("kind", "web") in LONG_RUNNING]
            targets = [(n, req) for n in names] or [(None, req)]
        for sname, paths in targets:
            if sname is None:
                ws = [o for o in objs if kind_of(o) in ("Deployment", "StatefulSet")]
            else:
                kind = next((s.get("kind", "web") for s in services or [] if s["name"] == sname), None)
                w = find_workload(objs, {"name": sname, "kind": kind})
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
        if objs:
            check_overlay(ck, exp, ov, objs)

    if not validate:
        ck.skip("k8sa-validate PASS (exit 0)", "--no-validate", category="validation")
    elif os.path.isdir(k8s):
        try:
            r = subprocess.run([VALIDATE, k8s], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True)
            ck.check("k8sa-validate PASS (exit 0)", r.returncode == 0, "exit=%d" % r.returncode,
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
