#!/usr/bin/env python3
"""Score a k8s-anything run against an eval's expectations.

Usage: evals/check.py <eval-dir> <app-dir-after-run>
  <eval-dir>  contains expect.json (see evals/flask-redis/expect.json)
  <app-dir>   the target app after the agent ran (has Dockerfile, deploy/k8s/)

Checks properties, not an exact diff: agent output is not deterministic, but a good
run must satisfy every expectation. Exit 0 if all pass, 1 otherwise.
Needs kubectl (for `kubectl kustomize`). Runs k8sa-validate from this repo.
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATE = os.path.join(REPO, "bin", "k8sa-validate")


def render(path):
    r = subprocess.run(["kubectl", "kustomize", path], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr.strip()
    docs = [d for d in re.split(r"^---\s*$", r.stdout, flags=re.M) if d.strip()]
    return docs, ""


def kind_of(doc):
    m = re.search(r"^kind:\s*(\S+)", doc, re.M)
    return m.group(1) if m else ""


def main():
    eval_dir, app = (os.path.abspath(a) for a in sys.argv[1:3])
    exp = json.load(open(os.path.join(eval_dir, "expect.json")))
    k8s = os.path.join(app, "deploy", "k8s")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # --- container
    df_path = os.path.join(app, "Dockerfile")
    df = open(df_path).read() if os.path.exists(df_path) else ""
    check("Dockerfile exists", df)
    users = re.findall(r"^\s*USER\s+(\S+)", df, re.M)
    check("Dockerfile runs as numeric non-root USER",
          users and re.match(r"^[1-9]\d*(:\d+)?$", users[-1]), f"USER={users[-1] if users else None}")
    check("no :latest base images", not re.search(r"^\s*FROM\s+\S+:latest\b", df, re.M | re.I))
    check(".dockerignore exists", os.path.exists(os.path.join(app, ".dockerignore")))
    for bad in exp.get("forbidden_cmd_patterns", []):
        check(f"Dockerfile doesn't run dev server ({bad})", not re.search(bad, df))

    # --- app source untouched
    for rel in exp.get("unchanged_files", []):
        orig = os.path.join(REPO, exp["source"], rel)
        now = os.path.join(app, rel)
        same = os.path.exists(now) and open(orig, "rb").read() == open(now, "rb").read()
        check(f"source unchanged: {rel}", same)

    # --- manifests
    rendered = {}
    for ov in ("dev", "prod"):
        docs, err = render(os.path.join(k8s, "overlays", ov))
        check(f"overlay {ov} builds", docs is not None, err[:200])
        rendered[ov] = docs or []

    for ov, docs in rendered.items():
        if not docs:
            continue
        kinds = [kind_of(d) for d in docs]
        check(f"{ov}: has Namespace", "Namespace" in kinds)
        text = "\n".join(docs)
        check(f"{ov}: readiness on {exp['health_path']}",
              re.search(r"readinessProbe:\s*\n(?:\s+.*\n){0,3}?\s+path:\s*" + re.escape(exp["health_path"]), text))
        cms = "\n".join(d for d in docs if kind_of(d) == "ConfigMap")
        for key in exp.get("secret_or_dropped_keys", []):
            check(f"{ov}: {key} not in any ConfigMap", key not in cms)
        if ov == "prod":
            for key in exp.get("secret_or_dropped_keys", []):
                secrets = [d for d in docs if kind_of(d) == "Secret"]
                check(f"prod: no inlined Secret values for {key}",
                      not any(key in s for s in secrets))
        for img in exp.get("dev_only_images", []):
            has = re.search(r"image:\s*[\"']?(?:\S*/)?" + re.escape(img) + r"(?:[:@\s\"']|$)", text)
            check(f"{ov}: {img} image {'present' if ov == 'dev' else 'absent'}",
                  bool(has) == (ov == "dev"))

    prod = rendered.get("prod", [])
    if any(kind_of(d) == "HorizontalPodAutoscaler" for d in prod):
        deploys = [d for d in prod if kind_of(d) == "Deployment"]
        check("prod: HPA owns replicas (no replicas field on HPA'd Deployment)",
              not any(re.search(r"^\s{2}replicas:", d, re.M) and "app.kubernetes.io/component: web" in d
                      for d in deploys))
    check("prod: has PodDisruptionBudget", any(kind_of(d) == "PodDisruptionBudget" for d in prod))
    check("prod: has NetworkPolicy", any(kind_of(d) == "NetworkPolicy" for d in prod))

    # --- validation
    if os.path.isdir(k8s):
        r = subprocess.run([VALIDATE, k8s], capture_output=True, text=True)
        check("k8sa-validate PASS (exit 0)", r.returncode == 0, f"exit={r.returncode}")

    # --- report
    rp = os.path.join(k8s, "K8S_REPORT.md")
    report = open(rp).read() if os.path.exists(rp) else ""
    check("K8S_REPORT.md exists", report)
    for section in ("Evidence", "Assumptions", "Open questions", "Checklist", "Validation"):
        check(f"report has '{section}'", re.search(r"^#+\s*" + section, report, re.M | re.I))
    check("report cites file:line evidence", re.search(r"\b[\w./-]+\.\w+:\d+", report))
    for word in exp.get("report_mentions", []):
        check(f"report mentions '{word}'", word.lower() in report.lower())

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok else ''}".rstrip())
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
