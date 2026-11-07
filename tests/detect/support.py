"""Shared helpers: build throwaway app trees and run detect.py on them as a CLI."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DETECT = os.environ.get("K8SA_DETECT") or os.path.join(REPO, "skills", "k8s-anything", "scripts", "detect.py")


def write_tree(root, files):
    """files: {relative path: str | bytes}. A str is written as UTF-8 verbatim
    (no newline translation, so CRLF fixtures stay CRLF)."""
    for rel, content in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        with open(path, "wb") as fh:
            fh.write(data)


class DetectCase(unittest.TestCase):
    """Each test gets a fresh temp dir; `detect(files)` returns the parsed JSON."""

    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="k8sa detect 'q' ")  # space + quote on purpose
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, root):
        r = subprocess.run([sys.executable, "-I", DETECT, root],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return r

    def detect(self, files=None, sub="app"):
        root = os.path.join(self.tmp, sub)
        os.makedirs(root, exist_ok=True)
        write_tree(root, files or {})
        r = self.run_cli(root)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        try:
            return json.loads(r.stdout.decode("utf-8"))
        except ValueError as e:  # pragma: no cover - the assertion is the point
            self.fail("invalid JSON: %s\n%s" % (e, r.stdout[:2000]))

    def frameworks(self, files):
        return self.detect(files)["frameworks"]

    def service(self, out, path, name=None):
        for s in out["services"]:
            if s["path"] == path and (name is None or s["name"] == name):
                return s
        self.fail("no service path=%r name=%r in %s" % (
            path, name, [(s["path"], s["name"]) for s in out["services"]]))

    @staticmethod
    def ports(svc):
        return sorted({p["port"] for p in svc["ports"]})
