#!/usr/bin/env python3
"""Deterministic fingerprint of an app directory, printed as JSON.

Usage: detect.py [app-path]
Reads files only; never executes project code. Standard library only.
"""
import json
import os
import re
import sys

PRUNE = {"node_modules", ".git", ".venv", "venv", "vendor", "dist", "build", "target",
         ".next", "__pycache__", ".tox", ".gradle", ".idea", "deploy"}
MAX_DEPTH = 4
MAX_FILE = 1_000_000

STACK_MARKERS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "Pipfile", "uv.lock", "poetry.lock", "setup.py"],
    "go": ["go.mod"],
    "jvm": ["pom.xml", "build.gradle", "build.gradle.kts", "build.sbt"],
    "ruby": ["Gemfile"],
    "php": ["composer.json"],
    "rust": ["Cargo.toml"],
}

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
JVM_FW = {"spring-boot": "spring-boot", "quarkus": "quarkus", "micronaut": "micronaut", "ktor": "ktor"}


def walk(root):
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.count(os.sep) - root_depth
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE and depth < MAX_DEPTH)
        for f in sorted(filenames):
            yield os.path.relpath(os.path.join(dirpath, f), root)


def read(root, rel):
    p = os.path.join(root, rel)
    try:
        if os.path.getsize(p) > MAX_FILE:
            return ""
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read().replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return ""


def base(rel):
    return os.path.basename(rel)


def is_dockerfile(name):
    return (name in ("Dockerfile", "Containerfile") or name.startswith("Dockerfile.")
            or name.endswith(".Dockerfile"))


COMPOSE_RE = re.compile(r"^(docker-)?compose(\.[\w-]+)?\.ya?ml$")


def node_frameworks(text):
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(data.get(key), dict):
            deps.update(data[key])
    return {v for k, v in NODE_FW.items() if k in deps}


PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def py_names(rel, text):
    names = set()
    if base(rel).startswith("requirements"):
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = PEP508_NAME.match(line)
            if m:
                names.add(m.group(1))
    else:  # pyproject / Pipfile / setup.py: quoted requirement strings or TOML keys
        for m in re.finditer(r"""["']([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@ ]|["'])""", text):
            names.add(m.group(1))
        for m in re.finditer(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=", text, re.M):
            names.add(m.group(1))
    return {re.sub(r"[-_.]+", "-", n).lower() for n in names}


def py_frameworks(rel, text):
    names = py_names(rel, text)
    return {v for k, v in PY_FW.items() if k in names}


def go_frameworks(text):
    return {v for k, v in GO_FW.items() if re.search(r"^\s*(require\s+)?" + re.escape(k) + r"(/v\d+)?\s", text, re.M)}


def ruby_frameworks(text):
    return {v for k, v in RUBY_FW.items() if re.search(r"""^\s*gem\s+["']""" + re.escape(k) + r"""["']""", text, re.M)}


def php_frameworks(text):
    try:
        req = json.loads(text).get("require", {})
    except (ValueError, AttributeError):
        return set()
    return {v for k, v in PHP_FW.items() if k in req}


def rust_frameworks(text):
    return {v for k, v in RUST_FW.items() if re.search(r"^\s*" + re.escape(k) + r"\s*=", text, re.M)}


def jvm_frameworks(text):
    found = set()
    for k, v in JVM_FW.items():
        if re.search(r"[\"':>/.]" + re.escape(k) + r"([\"':<-]|$)", text, re.M) or f"io.{k}" in text:
            found.add(v)
    return found


def expose_ports(text):
    ports = set()
    for line in text.splitlines():
        m = re.match(r"^\s*EXPOSE\s+(.*)$", line, re.I)
        if m:
            for tok in m.group(1).split():
                tok = tok.split("/")[0]
                if tok.isdigit():
                    ports.add(tok)
                elif tok.startswith("$"):
                    ports.add(tok)
    return ports


def compose_info(text):
    """Return (services, container_ports) without a YAML library."""
    services, ports = [], set()
    lines = [l for l in text.splitlines()]
    in_services = False
    svc_indent = None
    in_ports = False
    ports_indent = 0
    for raw in lines:
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_services = stripped.startswith("services:")
            svc_indent = None
            in_ports = False
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = indent
        if indent == svc_indent and stripped.endswith(":"):
            services.append(stripped[:-1].strip("\"'"))
            in_ports = False
            continue
        if stripped.startswith(("ports:", "expose:")):
            in_ports, ports_indent = True, indent
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("["):
                for item in inline.strip("[]").split(","):
                    ports.update(_port_from_short(item))
            continue
        if in_ports:
            if indent <= ports_indent:
                in_ports = False
            else:
                item = stripped[1:].strip() if stripped.startswith("-") else stripped
                if item.startswith("target:"):
                    ports.update(_port_from_short(item.split(":", 1)[1]))
                elif stripped.startswith("-") and not re.match(r"^[a-z_]+:", item):
                    ports.update(_port_from_short(item))
    return services, ports


def _port_from_short(item):
    """'8080', '"127.0.0.1:8080:80/tcp"', '${PORT:-8000}:8000', '6000-6005:6000-6005' -> container side."""
    item = item.strip().strip("\"'")
    if not item:
        return set()
    item = re.sub(r"\$\{[^}]*\}", "VAR", item)  # neutralize ${VAR:-x} which contains ':'
    item = item.split("/")[0]
    container = item.rsplit(":", 1)[-1]
    if re.fullmatch(r"\d+(-\d+)?", container):
        return {container}
    return set()


def env_keys(text):
    keys = set()
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            keys.add(m.group(1))
    return keys


K8S_KIND = re.compile(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Service|Ingress|CronJob|Job|HTTPRoute)\s*$", re.M)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    out = {k: set() for k in ("stacks", "frameworks", "expose_ports", "compose_services",
                              "compose_container_ports", "procfile_processes", "env_keys")}
    lists = {k: [] for k in ("dockerfiles", "compose_files", "procfiles", "env_files",
                             "existing_helm_charts", "existing_kustomizations", "existing_k8s_manifests")}

    for rel in walk(root):
        name = base(rel)
        for stack, markers in STACK_MARKERS.items():
            if name in markers or (stack == "python" and re.fullmatch(r"requirements[\w.-]*\.txt", name)):
                out["stacks"].add(stack)
        if name.endswith((".csproj", ".sln")):
            out["stacks"].add("dotnet")

        if name == "package.json":
            out["frameworks"] |= node_frameworks(read(root, rel))
        elif name in ("pyproject.toml", "Pipfile", "setup.py") or re.fullmatch(r"requirements[\w.-]*\.txt", name):
            out["frameworks"] |= py_frameworks(rel, read(root, rel))
        elif name == "go.mod":
            out["frameworks"] |= go_frameworks(read(root, rel))
        elif name == "Gemfile":
            out["frameworks"] |= ruby_frameworks(read(root, rel))
        elif name == "composer.json":
            out["frameworks"] |= php_frameworks(read(root, rel))
        elif name == "Cargo.toml":
            out["frameworks"] |= rust_frameworks(read(root, rel))
        elif name in ("pom.xml", "build.gradle", "build.gradle.kts", "build.sbt"):
            out["frameworks"] |= jvm_frameworks(read(root, rel))

        if is_dockerfile(name):
            lists["dockerfiles"].append(rel)
            out["expose_ports"] |= expose_ports(read(root, rel))
        elif COMPOSE_RE.match(name):
            lists["compose_files"].append(rel)
            svcs, ports = compose_info(read(root, rel))
            out["compose_services"].update(svcs)
            out["compose_container_ports"] |= ports
        elif name == "Procfile":
            lists["procfiles"].append(rel)
            for line in read(root, rel).splitlines():
                m = re.match(r"^([A-Za-z0-9_-]+):", line)
                if m:
                    out["procfile_processes"].add(m.group(1))
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
    deploy = os.path.join(root, "deploy")
    lists["existing_deploy_dir"] = ["deploy"] if os.path.isdir(deploy) else []

    result = {"path": root}
    for k in ("stacks", "frameworks"):
        result[k] = sorted(out[k])
    for k in ("dockerfiles",):
        result[k] = lists[k]
    result["expose_ports"] = sorted(out["expose_ports"])
    result["compose_files"] = lists["compose_files"]
    result["compose_services"] = sorted(out["compose_services"])
    result["compose_container_ports"] = sorted(out["compose_container_ports"])
    result["procfiles"] = lists["procfiles"]
    result["procfile_processes"] = sorted(out["procfile_processes"])
    result["env_files"] = lists["env_files"]
    result["env_keys"] = sorted(out["env_keys"])
    for k in ("existing_helm_charts", "existing_kustomizations", "existing_k8s_manifests", "existing_deploy_dir"):
        result[k] = lists[k]
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
