#!/usr/bin/env python3
"""Deterministic fingerprint of an app directory, printed as JSON.

Usage: detect.py [app-path]
Reads files only; never executes project code. Standard library only, Python 3.9+.

Top-level keys aggregate the whole repo. `services` lists deployable-unit candidates
(monorepo workspaces, Go cmd/* binaries, compose services with build:, Procfile
processes, or the root app) with per-service stack, frameworks, Dockerfile, a kind
guess (web/worker/unknown) and port evidence as file:line.
"""
import json
import os
import posixpath
import re
import sys

PRUNE = {"node_modules", ".git", ".venv", "venv", "vendor", "dist", "build", "target",
         ".next", "__pycache__", ".tox", ".gradle", ".idea"}
PRUNE_AT_ROOT = {"deploy"}  # may hold our own output; reported as existing_deploy_dir
MAX_DEPTH = 4
MAX_FILE = 1000000

STACK_MARKERS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "Pipfile", "uv.lock", "poetry.lock", "setup.py"],
    "go": ["go.mod"],
    "jvm": ["pom.xml", "build.gradle", "build.gradle.kts", "build.sbt"],
    "ruby": ["Gemfile"],
    "php": ["composer.json"],
    "rust": ["Cargo.toml"],
}
STACK_ORDER = list(STACK_MARKERS) + ["dotnet"]
REQ_TXT = re.compile(r"requirements[\w.-]*\.txt")

# Framework name -> how it appears as a dependency, per manifest type.
NODE_FW = {"next": "next", "express": "express", "fastify": "fastify", "@nestjs/core": "nestjs",
           "hono": "hono", "nuxt": "nuxt", "react-router": "react-router", "@remix-run/node": "remix",
           "astro": "astro", "vite": "vite"}
PY_FW = {"django": "django", "flask": "flask", "fastapi": "fastapi", "starlette": "starlette",
         "celery": "celery", "gunicorn": "gunicorn", "uvicorn": "uvicorn", "streamlit": "streamlit"}
GO_FW = {"github.com/gin-gonic/gin": "gin", "github.com/labstack/echo": "echo",
         "github.com/gofiber/fiber": "fiber", "github.com/go-chi/chi": "chi"}
RUBY_FW = {"rails": "rails", "sidekiq": "sidekiq", "sinatra": "sinatra", "puma": "puma"}
PHP_FW = {"laravel/framework": "laravel", "symfony/framework-bundle": "symfony"}
RUST_FW = {"actix-web": "actix-web", "axum": "axum", "rocket": "rocket"}
JVM_FW = {  # regex on comment-stripped build files
    "spring-boot": r"org\.springframework\.boot(?![\w-])|[\"':/]spring-boot-starter",
    "quarkus": r"io\.quarkus(?![\w-])", "micronaut": r"io\.micronaut(?![\w-])",
    "ktor": r"io\.ktor(?![\w-])",
}

WORKER_FW = {"celery", "sidekiq"}
WEB_FW = set(NODE_FW.values()) | set(PY_FW.values()) | set(GO_FW.values()) | \
    set(RUBY_FW.values()) | set(PHP_FW.values()) | set(RUST_FW.values()) | set(JVM_FW)
WEB_FW -= WORKER_FW
NODE_WORKER_DEPS = {"bullmq", "bull", "bee-queue", "agenda", "graphile-worker", "pg-boss"}
WORKER_NAME = re.compile(r"(?:^|[-_.])(workers?|consumers?|jobs?|queues?)(?:$|[-_.])", re.I)
WORKER_CMD = re.compile(r"\bworker\b|\bcelery\b|\bsidekiq\b|\bresque\b|queue:work|\bconsumer\b|\brq\b")
WEB_CMD = re.compile(r"\b(gunicorn|uvicorn|hypercorn|daphne|waitress-serve|puma|unicorn|"
                     r"rails\s+s(erver)?|next\s+start|nuxt\s+start|streamlit\s+run|php-fpm|nginx|"
                     r"runserver|serve)\b")
CMD_PORT = re.compile(r"(?:^|\s)(?:-p|--port|--listen)(?:\s+|=)(\$\{?\w+\}?|\d{2,5}(?!\d))"
                      r"|(?:^|\s)(?:--bind|-b)(?:\s+|=)\S*?:(\$\{?\w+\}?|\d{2,5}(?!\d))"
                      r"|\bPORT=(\d{2,5}(?!\d))")
WORKSPACE_DIRS = ("apps", "packages", "services")


# ---------------------------------------------------------------- file access

def walk(root):
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE and depth < MAX_DEPTH
                             and not (depth == 0 and d in PRUNE_AT_ROOT))
        for f in sorted(filenames):
            yield os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")


def read(root, rel):
    p = os.path.join(root, rel)
    try:
        if not os.path.isfile(p) or os.path.getsize(p) > MAX_FILE:  # FIFOs, sockets, huge files
            return ""
        with open(p, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read().replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return ""


def base(rel):
    return posixpath.basename(rel)


def parent(rel):
    d = posixpath.dirname(rel)
    return d or "."


DOC_SUFFIXES = (".md", ".txt", ".rst", ".orig", ".bak", ".rej", ".swp", ".dockerignore")


def is_dockerfile(name):
    if name.lower().endswith(DOC_SUFFIXES):
        return False
    return (name in ("Dockerfile", "Containerfile") or name.startswith("Dockerfile.")
            or name.endswith(".Dockerfile"))


COMPOSE_RE = re.compile(r"^(docker-)?compose(\.[\w-]+)?\.ya?ml$")


def json_load(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def line_of(text, needle, default=1):
    idx = text.find(needle)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else default


# ---------------------------------------------------------------- frameworks

def node_deps(data):
    deps = {}
    if isinstance(data, dict):
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(data.get(key), dict):
                deps.update(data[key])
    return deps


def node_frameworks(text):
    deps = node_deps(json_load(text))
    return {v for k, v in NODE_FW.items() if k in deps}


PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
TOML_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'')


def _strip_toml_strings(s):
    s = TOML_STRING.sub('""', s)
    return re.sub(r"#.*", "", s)


def toml_scan(text):
    """Tiny TOML reader: ({section: [keys]}, {(section, key): [array strings]})."""
    section, keys, arrays = "", {}, {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$", s)
        if m:
            section = re.sub(r"""\s*\.\s*""", ".", m.group(1)).replace('"', "").replace("'", "")
            continue
        m = re.match(r"""^("[^"]*"|'[^']*'|[A-Za-z0-9_.-]+)\s*=\s*(.*)$""", s)
        if not m:
            continue
        key, val = m.group(1).strip("\"'"), m.group(2)
        keys.setdefault(section, []).append(key)
        if val.startswith("["):
            buf = val
            while i < len(lines):
                flat = _strip_toml_strings(buf)
                if flat.count("[") <= flat.count("]"):
                    break
                buf += "\n" + lines[i]
                i += 1
            arrays[(section, key)] = [a or b for a, b in TOML_STRING.findall(buf)]
    return keys, arrays


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _spec_names(specs):
    names = set()
    for spec in specs:
        m = PEP508_NAME.match(spec)
        if m:
            names.add(m.group(1))
    return names


def py_names(rel, text):
    name = base(rel)
    names = set()
    if name.endswith(".txt"):
        lines = [ln.split("#", 1)[0].strip() for ln in text.split("\n")]
        names = _spec_names(ln for ln in lines if ln and not ln.startswith("-"))
    elif name == "setup.py":
        for m in re.finditer(r"\b(install_requires|extras_require)\s*=\s*", text):
            depth, j = 0, m.end()
            while j < len(text):
                c = text[j]
                depth += c in "[{("
                depth -= c in "]})"
                j += 1
                if depth <= 0:
                    break
            names |= _spec_names(a or b for a, b in TOML_STRING.findall(text[m.end():j]))
    else:  # pyproject.toml / Pipfile
        keys, arrays = toml_scan(text)
        for (section, key), specs in arrays.items():
            if ((section == "project" and key == "dependencies")
                    or section in ("project.optional-dependencies", "dependency-groups")
                    or (section == "tool.uv" and key == "dev-dependencies")
                    or section.startswith("tool.pdm.dev-dependencies")):
                names |= _spec_names(specs)
        for section, ks in keys.items():
            if (section in ("tool.poetry.dependencies", "tool.poetry.dev-dependencies",
                            "packages", "dev-packages")
                    or re.fullmatch(r"tool\.poetry\.group\.[^.]+\.dependencies", section)):
                names.update(ks)
    return {_norm(n) for n in names}


def py_frameworks(rel, text):
    names = py_names(rel, text)
    return {v for k, v in PY_FW.items() if k in names}


def go_frameworks(text):
    found, in_block = set(), False
    for line in text.split("\n"):
        s = line.strip()
        if "// indirect" in s:
            continue
        if re.match(r"^require\s*\($", s):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        m = re.match(r"^require\s+(\S+)\s", s + " ") if not in_block else re.match(r"^(\S+)\s+v", s)
        if m:
            found |= _go_fw_for(m.group(1))
    return found


def _go_fw_for(path):
    return {v for k, v in GO_FW.items() if path == k or re.fullmatch(re.escape(k) + r"/v\d+", path)}


def ruby_frameworks(text):
    return {v for k, v in RUBY_FW.items()
            if re.search(r"""^\s*gem\s+["']""" + re.escape(k) + r"""["']""", text, re.M)}


def php_frameworks(text):
    data = json_load(text)
    req = data.get("require") if isinstance(data, dict) else None
    if not isinstance(req, dict):
        return set()
    return {v for k, v in PHP_FW.items() if k in req}


def rust_frameworks(text):
    keys, _ = toml_scan(text)
    names = set()
    for section, ks in keys.items():
        if section in ("dependencies", "workspace.dependencies") or \
                re.fullmatch(r"target\..+\.dependencies", section):
            names.update(ks)
        m = re.fullmatch(r"(?:target\..+\.)?dependencies\.([A-Za-z0-9_-]+)", section)
        if m:
            names.add(m.group(1))
    return {v for k, v in RUST_FW.items() if k in names}


def jvm_frameworks(text):
    text = re.sub(r"<!--.*?-->|/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"(^|\s)//.*", " ", text)
    return {k for k, pat in JVM_FW.items() if re.search(pat, text)}


def is_requirements_dir_file(rel):
    return rel.endswith(".txt") and base(parent(rel)) == "requirements" and \
        not REQ_TXT.fullmatch(base(rel))


def is_python_manifest(rel):
    name = base(rel)
    return name in ("pyproject.toml", "Pipfile", "setup.py") or bool(REQ_TXT.fullmatch(name)) or \
        is_requirements_dir_file(rel)


def is_manifest(rel):
    name = base(rel)
    return name in ("package.json", "go.mod", "Gemfile", "composer.json", "Cargo.toml") or \
        name in STACK_MARKERS["jvm"] or is_python_manifest(rel)


def manifest_frameworks(rel, text):
    """(stack, frameworks) for a dependency manifest (see is_manifest)."""
    name = base(rel)
    if name == "package.json":
        return "node", node_frameworks(text)
    if is_python_manifest(rel):
        return "python", py_frameworks(rel, text)
    if name == "go.mod":
        return "go", go_frameworks(text)
    if name == "Gemfile":
        return "ruby", ruby_frameworks(text)
    if name == "composer.json":
        return "php", php_frameworks(text)
    if name == "Cargo.toml":
        return "rust", rust_frameworks(text)
    if name in STACK_MARKERS["jvm"]:
        return "jvm", jvm_frameworks(text)
    return None


# ---------------------------------------------------------------- ports

def expose_ports(text):
    """[(port, line)] from EXPOSE, including line continuations, ranges and $VARS."""
    found, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        start, line = i + 1, lines[i]
        i += 1
        m = re.match(r"^\s*EXPOSE(?:\s+(.*))?$", line, re.I)
        if not m:
            continue
        body = m.group(1) or ""
        while body.rstrip().endswith("\\") and i < len(lines):
            body = body.rstrip()[:-1] + " " + lines[i]
            i += 1
        body = re.sub(r"(^|\s)#.*", "", body)
        for tok in body.split():
            tok = tok.split("/")[0]
            if re.fullmatch(r"\d+(-\d+)?", tok) or tok.startswith("$"):
                found.append((tok, start))
    return found


def _port_from_short(item):
    """'8080', '"127.0.0.1:8080:80/tcp"', '${PORT:-8000}:8000', '6000-6005:6000-6005' -> container side."""
    item = item.strip().strip("\"'")
    if not item:
        return None
    item = re.sub(r"\$\{[^}]*\}", "VAR", item)  # neutralize ${VAR:-x} which contains ':'
    container = item.split("/")[0].rsplit(":", 1)[-1]
    return container if re.fullmatch(r"\d+(-\d+)?", container) else None


def cmd_ports(cmd):
    ports = [next(g for g in m.groups() if g) for m in CMD_PORT.finditer(cmd)]
    if not ports and re.search(r"\$\{?PORT\b", cmd):
        ports = ["$PORT"]
    return ports


# ---------------------------------------------------------------- compose

def _flow_items(val):
    return [x.strip() for x in val.strip()[1:].rstrip("]").split(",") if x.strip()]


def _unquote(s):
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def compose_info(text):
    """Services of a compose file without a YAML library.

    Returns [{name, line, build: {context, dockerfile} | None, command, ports: [(port, line)]}].
    `ports` holds the container side of `ports:` and `expose:`.
    """
    services = []
    in_services, svc_indent, cur = False, None, None
    key_indent, block = None, None
    for lineno, raw in enumerate(text.split("\n"), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_services = bool(re.match(r"^services\s*:", stripped))
            svc_indent, cur = None, None
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = indent
        if indent <= svc_indent:
            m = re.match(r"""^(["']?)([^"':\s][^"':]*)\1\s*:\s*(&\S+)?$""", stripped)
            cur = None
            if indent == svc_indent and m:
                cur = {"name": m.group(2).strip(), "line": lineno, "build": None,
                       "command": "", "ports": []}
                services.append(cur)
                key_indent, block = None, None
            continue
        if cur is None:
            continue
        if key_indent is None:
            key_indent = indent
        if indent <= key_indent:
            m = re.match(r"""^(["']?)([\w.-]+)\1\s*:(?:\s+(.*))?$""", stripped)
            block = None
            if not m:
                continue
            key, val = m.group(2), (m.group(3) or "").strip()
            block = key
            if key in ("ports", "expose") and val.startswith("["):
                for item in _flow_items(val):
                    p = _port_from_short(item)
                    if p:
                        cur["ports"].append((p, lineno))
            elif key == "build":
                cur["build"] = {"context": _unquote(val) if val else ".", "dockerfile": None}
            elif key in ("command", "entrypoint") and val:
                cur["command"] += " " + val
            continue
        # nested under a service key
        if block in ("ports", "expose"):
            is_item = stripped.startswith("-")
            item = stripped[1:].strip() if is_item else stripped
            m = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", item)
            if m:
                if m.group(1) == "target":
                    p = _port_from_short(m.group(2))
                    if p:
                        cur["ports"].append((p, lineno))
            elif is_item:
                p = _port_from_short(item)
                if p:
                    cur["ports"].append((p, lineno))
        elif block == "build" and cur["build"] is not None:
            m = re.match(r"^(context|dockerfile)\s*:\s*(.+)$", stripped)
            if m:
                cur["build"][m.group(1)] = _unquote(m.group(2))
        elif block in ("command", "entrypoint"):
            cur["command"] += " " + _unquote(stripped.lstrip("-").strip())
    return services


# ---------------------------------------------------------------- misc parsers

def env_keys(text):
    keys = set()
    for line in text.split("\n"):
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            keys.add(m.group(1))
    return keys


def procfile_entries(text):
    out = []
    for lineno, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            out.append((m.group(1), m.group(2).strip(), lineno))
    return out


K8S_KIND = re.compile(r"""^kind:\s*["']?(Deployment|StatefulSet|DaemonSet|Service|Ingress|CronJob|"""
                      r"""Job|HTTPRoute|Pod|ReplicaSet)["']?\s*(#.*)?$""", re.M)


def go_cmd_info(root, rels):
    """Frameworks, port evidence and 'serves HTTP' flag from the .go files of one cmd dir."""
    fws, ports, serves, is_main = set(), [], False, False
    for rel in rels:
        text = read(root, rel)
        if re.search(r"^package\s+main\b", text, re.M):
            is_main = True
        for imp in re.findall(r'"([\w.-]+\.[\w.-]+/[^"\s]+)"', text):
            fws |= {v for k, v in GO_FW.items()
                    if imp == k or imp.startswith(k + "/")}
        if "ListenAndServe" in text or re.search(r"\bnet\.Listen\(", text):
            serves = True
        for lineno, line in enumerate(text.split("\n"), 1):
            if re.search(r"Listen\w*\(|\.Run\(|\.Start\(|\bAddr\s*[:=]", line):
                for p in re.findall(r'"[^"\s]*:(\d{2,5})"', line):
                    ports.append((p, "%s:%d" % (rel, lineno)))
    return is_main, fws, ports, serves


# ---------------------------------------------------------------- services

def guess_kind(name, command, frameworks, ports, worker_hint=False, by_command=False):
    if command and WORKER_CMD.search(command):
        return "worker"
    if WORKER_NAME.search(name or ""):
        return "worker"
    if by_command:
        if name == "web" or ports or (command and WEB_CMD.search(command)):
            return "web"
        return "unknown"
    if ports or (set(frameworks) & WEB_FW):
        return "web"
    if worker_hint or (set(frameworks) & WORKER_FW):
        return "worker"
    return "unknown"


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        key = json.dumps(it, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


class Index:
    """Per-directory facts gathered during the walk."""

    def __init__(self):
        self.stacks = {}       # dir -> set(stack)
        self.fw = {}           # dir -> {stack: set(fw)}
        self.manifests = {}    # dir -> [rel]
        self.dockerfiles = {}  # rel -> [(port, line)]
        self.pkg = {}          # dir -> (rel, text)

    def add_stack(self, d, stack):
        self.stacks.setdefault(d, set()).add(stack)

    def add_fw(self, d, stack, fws, rel):
        self.add_stack(d, stack)
        self.fw.setdefault(d, {}).setdefault(stack, set()).update(fws)
        self.manifests.setdefault(d, []).append(rel)

    def stack_of(self, d):
        stacks = self.stacks.get(d, set())
        with_fw = [s for s in STACK_ORDER if s in stacks and self.fw.get(d, {}).get(s)]
        ordered = with_fw or [s for s in STACK_ORDER if s in stacks]
        return ordered[0] if ordered else None

    def frameworks_of(self, d):
        out = set()
        for fws in self.fw.get(d, {}).values():
            out |= fws
        return sorted(out)

    def dockerfile_in(self, d, strict=False):
        prefix = "" if d == "." else d + "/"
        names = [r for r in self.dockerfiles if parent(r) == d]
        for n in ("Dockerfile", "Containerfile"):
            if prefix + n in self.dockerfiles:
                return prefix + n
        return names[0] if len(names) == 1 and not strict else None

    def expose_evidence(self, dockerfile):
        return [{"port": p, "evidence": "%s:%d" % (dockerfile, ln)}
                for p, ln in self.dockerfiles.get(dockerfile, [])]

    def script_ports(self, d):
        if d not in self.pkg:
            return []
        rel, text = self.pkg[d]
        data = json_load(text)
        scripts = data.get("scripts") if isinstance(data, dict) else None
        out = []
        if isinstance(scripts, dict):
            for k, v in scripts.items():
                if isinstance(v, str) and k in ("start", "serve", "dev", "preview", "prod"):
                    for p in cmd_ports(v):
                        out.append({"port": p, "evidence": "%s:%d" % (rel, line_of(text, json.dumps(k)))})
        return out

    def worker_hint(self, d):
        if d not in self.pkg:
            return False
        data = json_load(self.pkg[d][1])
        start = data.get("scripts", {}).get("start", "") if isinstance(data, dict) and \
            isinstance(data.get("scripts"), dict) else ""
        return bool(set(node_deps(data)) & NODE_WORKER_DEPS) or \
            bool(isinstance(start, str) and WORKER_CMD.search(start))


def service(name, path, source, kind, stack, frameworks, dockerfile, ports, evidence):
    return {"name": name, "path": path, "sources": [source], "kind": kind, "stack": stack,
            "frameworks": sorted(frameworks), "dockerfile": dockerfile,
            "ports": _dedupe(ports), "evidence": evidence}


def dir_service(idx, name, d, source, evidence):
    dockerfile = idx.dockerfile_in(d)
    ports = (idx.expose_evidence(dockerfile) if dockerfile else []) + idx.script_ports(d)
    fws = idx.frameworks_of(d)
    kind = guess_kind(name, "", fws, ports, worker_hint=idx.worker_hint(d))
    return service(name, d, source, kind, idx.stack_of(d), fws, dockerfile, ports, evidence)


def build_services(root, idx, compose_svcs, procs, go_cmds):
    found = []  # (path, order, entry)

    workspaces = {}
    for d in sorted(idx.stacks):
        parts = d.split("/")
        if len(parts) == 2 and parts[0] in WORKSPACE_DIRS:
            workspaces[d] = dir_service(idx, parts[1], d, "workspace", sorted(idx.manifests.get(d, [d])))

    merged = {}
    for compose_rel, svc in compose_svcs:
        b = svc["build"]
        if b is None:
            continue
        ctx = b["context"]
        remote = "://" in ctx or ctx.startswith("git@") or ctx.endswith(".git")
        if remote:
            path, dockerfile = ctx, None
        else:
            path = posixpath.normpath(posixpath.join(posixpath.dirname(compose_rel), ctx))
            if b["dockerfile"]:
                dockerfile = posixpath.normpath(posixpath.join(path, b["dockerfile"]))
            else:
                dockerfile = idx.dockerfile_in(path, strict=True)
        inside = not remote and not path.startswith("..") and not path.startswith("/")
        declared = [{"port": p, "evidence": "%s:%d" % (compose_rel, ln)} for p, ln in svc["ports"]]
        evidence = ["%s:%d" % (compose_rel, svc["line"])]
        key = (svc["name"], path)
        if key not in merged:  # the same service may be declared in several compose files
            merged[key] = {"name": svc["name"], "path": path, "inside": inside,
                           "dockerfile": dockerfile, "declared": [], "command": "", "evidence": []}
        m = merged[key]
        m["declared"] += declared
        m["command"] += svc["command"]
        m["evidence"] += evidence
    for m in merged.values():
        path, inside, dockerfile = m["path"], m["inside"], m["dockerfile"]
        ports = m["declared"] + (idx.expose_evidence(dockerfile) if inside and dockerfile else [])
        fws = idx.frameworks_of(path) if inside else []
        if m["command"].strip():  # the command defines the process; image facts don't
            kind = guess_kind(m["name"], m["command"], fws, m["declared"], by_command=True)
        else:
            kind = guess_kind(m["name"], "", fws, ports, worker_hint=idx.worker_hint(path))
        e = service(m["name"], path, "compose", kind, idx.stack_of(path) if inside else None,
                    fws, dockerfile, ports, m["evidence"])
        found.append(e)
        ws = workspaces.get(e["path"])
        if ws:
            e["sources"] = sorted(set(e["sources"]) | {"workspace"})
            e["evidence"] = e["evidence"] + [x for x in ws["evidence"] if x not in e["evidence"]]
    for e in found:
        workspaces.pop(e["path"], None)
    found.extend(workspaces.values())

    for d, rels in sorted(go_cmds.items()):
        is_main, fws, ports, serves = go_cmd_info(root, rels)
        if not is_main:
            continue
        name = base(d)
        dockerfile = idx.dockerfile_in(d, strict=True) or next(
            (r for r in sorted(idx.dockerfiles) if base(r) in ("Dockerfile." + name, name + ".Dockerfile")), None)
        ports = [{"port": p, "evidence": ev} for p, ev in ports]
        if dockerfile:
            ports += idx.expose_evidence(dockerfile)
        kind = guess_kind(name, "", fws, ports or (["serves"] if serves else []))
        main = next((r for r in rels if base(r) == "main.go"), rels[0])
        found.append(service(name, d, "go-cmd", kind, "go", fws, dockerfile, ports, [main]))

    for rel, (name, cmd, lineno) in procs:
        d = parent(rel)
        ports = [{"port": p, "evidence": "%s:%d" % (rel, lineno)} for p in cmd_ports(cmd)]
        kind = guess_kind(name, cmd, [], ports, by_command=True)
        found.append(service(name, d, "procfile", kind, idx.stack_of(d), idx.frameworks_of(d),
                             idx.dockerfile_in(d), ports, ["%s:%d" % (rel, lineno)]))

    if not found and idx.stack_of("."):
        found.append(dir_service(idx, base(root) or "app", ".", "root",
                                 sorted(idx.manifests.get(".", []))))
    order = {id(e): i for i, e in enumerate(found)}
    return sorted(found, key=lambda e: (e["path"], order[id(e)]))


# ---------------------------------------------------------------- main

def detect(root):
    out = {k: set() for k in ("stacks", "frameworks", "expose_ports", "compose_services",
                              "compose_container_ports", "procfile_processes", "env_keys")}
    lists = {k: [] for k in ("dockerfiles", "compose_files", "procfiles", "env_files",
                             "existing_helm_charts", "existing_kustomizations", "existing_k8s_manifests")}
    idx = Index()
    compose_svcs, procs, go_cmds = [], [], {}

    for rel in walk(root):
        name, d = base(rel), parent(rel)
        for stack, markers in STACK_MARKERS.items():
            if name in markers or (stack == "python" and REQ_TXT.fullmatch(name)):
                out["stacks"].add(stack)
                idx.add_stack(d, stack)
        if name.endswith((".csproj", ".sln")):
            out["stacks"].add("dotnet")
            idx.add_stack(d, "dotnet")

        if re.search(r"(^|/)cmd/[^/]+/[^/]+\.go$", rel) and not name.endswith("_test.go"):
            go_cmds.setdefault(d, []).append(rel)

        if is_manifest(rel):
            text = read(root, rel)
            stack, fws = manifest_frameworks(rel, text)
            out["stacks"].add(stack)
            out["frameworks"] |= fws
            # requirements/base.txt belongs to the directory holding requirements/
            owner = parent(d) if is_requirements_dir_file(rel) else d
            idx.add_fw(owner, stack, fws, rel)
            if name == "package.json":
                idx.pkg[d] = (rel, text)

        if is_dockerfile(name):
            lists["dockerfiles"].append(rel)
            ev = expose_ports(read(root, rel))
            idx.dockerfiles[rel] = ev
            out["expose_ports"].update(p for p, _ in ev)
        elif COMPOSE_RE.match(name):
            lists["compose_files"].append(rel)
            for svc in compose_info(read(root, rel)):
                out["compose_services"].add(svc["name"])
                out["compose_container_ports"].update(p for p, _ in svc["ports"])
                compose_svcs.append((rel, svc))
        elif name == "Procfile":
            lists["procfiles"].append(rel)
            for entry in procfile_entries(read(root, rel)):
                out["procfile_processes"].add(entry[0])
                procs.append((rel, entry))
        elif name == ".env" or name.startswith(".env.") or name.endswith(".env"):
            lists["env_files"].append(rel)
            out["env_keys"] |= env_keys(read(root, rel))
        elif name == "Chart.yaml":
            lists["existing_helm_charts"].append(rel)
        elif name in ("kustomization.yaml", "kustomization.yml", "Kustomization"):
            lists["existing_kustomizations"].append(rel)
        elif name.endswith((".yaml", ".yml")) and K8S_KIND.search(read(root, rel)):
            lists["existing_k8s_manifests"].append(rel)

    # deploy/ is pruned from the walk (it may hold our own output); report it separately.
    lists["existing_deploy_dir"] = ["deploy"] if os.path.isdir(os.path.join(root, "deploy")) else []

    result = {"path": root}
    for k in ("stacks", "frameworks"):
        result[k] = sorted(out[k])
    result["dockerfiles"] = lists["dockerfiles"]
    result["expose_ports"] = sorted(out["expose_ports"])
    result["compose_files"] = lists["compose_files"]
    result["compose_services"] = sorted(out["compose_services"])
    result["compose_container_ports"] = sorted(out["compose_container_ports"])
    result["procfiles"] = lists["procfiles"]
    result["procfile_processes"] = sorted(out["procfile_processes"])
    result["env_files"] = lists["env_files"]
    result["env_keys"] = sorted(out["env_keys"])
    for k in ("existing_helm_charts", "existing_kustomizations", "existing_k8s_manifests",
              "existing_deploy_dir"):
        result[k] = lists[k]
    result["services"] = build_services(root, idx, compose_svcs, procs, go_cmds)
    return result


def clean(obj):
    """Undecodable filename bytes (surrogate escapes) -> U+FFFD, so output is always valid JSON."""
    if isinstance(obj, str):
        return obj.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    if isinstance(obj, dict):
        return {clean(k): clean(v) for k, v in obj.items()}
    return obj


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    if not os.path.isdir(root):
        print("not a directory: %s" % root, file=sys.stderr)
        return 2
    json.dump(clean(detect(root)), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
