"""Stack markers and framework detectors: true positives and known false-positive traps."""
import json

from .support import DetectCase


def pkg(deps=None, dev=None, **extra):
    data = dict(name="x", **extra)
    if deps is not None:
        data["dependencies"] = deps
    if dev is not None:
        data["devDependencies"] = dev
    return json.dumps(data)


class StackMarkers(DetectCase):
    def test_each_marker(self):
        cases = {
            "node": "package.json", "go": "go.mod", "jvm": "pom.xml", "ruby": "Gemfile",
            "php": "composer.json", "rust": "Cargo.toml", "dotnet": "App.csproj",
        }
        for stack, marker in cases.items():
            with self.subTest(stack=stack):
                out = self.detect({marker: "{}\n"}, sub=stack)
                self.assertEqual(out["stacks"], [stack])

    def test_python_markers(self):
        for i, marker in enumerate(["pyproject.toml", "requirements.txt", "requirements-dev.txt",
                                    "Pipfile", "uv.lock", "poetry.lock", "setup.py"]):
            with self.subTest(marker=marker):
                self.assertEqual(self.detect({marker: ""}, sub="p%d" % i)["stacks"], ["python"])

    def test_jvm_variants(self):
        for i, marker in enumerate(["build.gradle", "build.gradle.kts", "build.sbt"]):
            with self.subTest(marker=marker):
                self.assertEqual(self.detect({marker: ""}, sub="j%d" % i)["stacks"], ["jvm"])

    def test_no_stack_from_lookalikes(self):
        out = self.detect({"package.json.bak": "{}", "notes/requirements.md": "flask",
                           "go.mod.orig": ""})
        self.assertEqual(out["stacks"], [])
        self.assertEqual(out["frameworks"], [])


class NodeFrameworks(DetectCase):
    def test_true_positives(self):
        deps = {"next": "14", "express": "4", "fastify": "4", "@nestjs/core": "10", "hono": "4",
                "nuxt": "3", "react-router": "7", "@remix-run/node": "2", "astro": "4"}
        out = self.frameworks({"package.json": pkg(deps, dev={"vite": "5"})})
        self.assertEqual(out, sorted(["next", "express", "fastify", "nestjs", "hono", "nuxt",
                                      "react-router", "remix", "astro", "vite"]))

    def test_traps(self):
        deps = {"@types/express": "4", "nextjs-foo": "1", "express-session": "1",
                "fastify-plugin": "4", "eslint-config-next": "14", "@nestjs/common": "10"}
        self.assertEqual(self.frameworks({"package.json": pkg(deps)}), [])

    def test_name_in_scripts_is_not_a_dependency(self):
        out = self.frameworks({"package.json": pkg({}, scripts={"start": "next start"})})
        self.assertEqual(out, [])

    def test_non_object_json_does_not_crash(self):
        for i, body in enumerate(["[]", "null", "\"express\"", "{not json", "",
                                  '{"dependencies": ["express"]}']):
            with self.subTest(body=body):
                out = self.detect({"package.json": body}, sub="n%d" % i)
                self.assertEqual(out["stacks"], ["node"])
                self.assertEqual(out["frameworks"], [])

    def test_utf8_bom(self):
        out = self.frameworks({"package.json": "﻿" + pkg({"express": "4"})})
        self.assertEqual(out, ["express"])


class PythonFrameworks(DetectCase):
    ALL = ["celery", "django", "fastapi", "flask", "gunicorn", "starlette", "streamlit", "uvicorn"]

    def test_requirements_true_positives(self):
        req = ("Django[argon2]==4.2  # web\nflask>=3\nFastAPI\nstarlette~=0.36\n"
               "celery[redis]\ngunicorn ; sys_platform != 'win32'\nuvicorn[standard]\n"
               "streamlit==1.3\n-r base.txt\n-e .\n")
        self.assertEqual(self.frameworks({"requirements.txt": req}), self.ALL)

    def test_requirements_traps(self):
        req = "celery-redbeat==2\nfastapi-users\nflask_cors\ndjango-environ\npytest-django\n"
        self.assertEqual(self.frameworks({"requirements.txt": req}), [])

    def test_requirements_directory(self):
        out = self.frameworks({"requirements/base.txt": "django==5\n",
                               "requirements/prod.txt": "-r base.txt\ngunicorn\n"})
        self.assertEqual(out, ["django", "gunicorn"])

    def test_pyproject_pep621(self):
        toml = ('[project]\nname = "svc"\ndescription = "Flask app with Django-like admin"\n'
                'keywords = ["django", "celery"]\n'
                'dependencies = [\n  "fastapi>=0.110",\n  "uvicorn[standard]",\n'
                '  "celery-redbeat",\n  "fastapi-users[sqlalchemy]",\n]\n'
                '[project.optional-dependencies]\nworker = ["celery>=5"]\n'
                '[tool.black]\nline-length = 88\n[tool.poetry.scripts]\nflask = "x:y"\n')
        self.assertEqual(self.frameworks({"pyproject.toml": toml}), ["celery", "fastapi", "uvicorn"])

    def test_pyproject_poetry(self):
        toml = ('[tool.poetry]\nname = "flask"\n\n[tool.poetry.dependencies]\npython = "^3.11"\n'
                'Django = {version = "^5", extras = ["argon2"]}\ncelery-redbeat = "*"\n'
                '[tool.poetry.group.dev.dependencies]\ngunicorn = "*"\n'
                '[build-system]\nrequires = ["poetry-core", "flask"]\n')
        self.assertEqual(self.frameworks({"pyproject.toml": toml}), ["django", "gunicorn"])

    def test_pipfile(self):
        pf = '[[source]]\nname = "pypi"\n[packages]\nflask = "*"\n"fastapi-users" = "*"\n[dev-packages]\nuvicorn = "*"\n'
        self.assertEqual(self.frameworks({"Pipfile": pf}), ["flask", "uvicorn"])

    def test_setup_py(self):
        src = ('from setuptools import setup\nsetup(name="flask", description="Django tools",\n'
               '      install_requires=["fastapi>=0.1", "celery-redbeat"],\n'
               '      extras_require={"w": ["celery"]})\n')
        self.assertEqual(self.frameworks({"setup.py": src}), ["celery", "fastapi"])


class GoFrameworks(DetectCase):
    def test_true_positives(self):
        gomod = ("module example.com/x\n\ngo 1.22\n\nrequire (\n"
                 "\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/labstack/echo/v4 v4.11.0\n"
                 "\tgithub.com/gofiber/fiber/v2 v2.52.0\n\tgithub.com/go-chi/chi/v5 v5.0.12\n)\n")
        self.assertEqual(self.frameworks({"go.mod": gomod}), ["chi", "echo", "fiber", "gin"])

    def test_single_line_require(self):
        gomod = "module x\nrequire github.com/gin-gonic/gin v1.9.1\n"
        self.assertEqual(self.frameworks({"go.mod": gomod}), ["gin"])

    def test_traps(self):
        gomod = ("module example.com/echo-the-gin-output\n// echo the gin output\n"
                 "require (\n\tgithub.com/gin-contrib/cors v1.5.0\n"
                 "\tgithub.com/labstack/echo-contrib v0.15.0\n"
                 "\tgithub.com/gin-gonic/gin v1.9.1 // indirect\n)\n")
        files = {"go.mod": gomod, "main.go": 'package main\n// echo the gin output\nfunc main() {}\n',
                 "README.md": "echo the gin output"}
        self.assertEqual(self.frameworks(files), [])


class OtherFrameworks(DetectCase):
    def test_ruby(self):
        gem = ("source 'https://rubygems.org'\ngem 'rails', '~> 7.1'\ngem \"sidekiq\"\n"
               "gem 'puma'\ngem 'sinatra', require: false\ngem 'rails-html-sanitizer'\n"
               "# gem 'nope'\n")
        self.assertEqual(self.frameworks({"Gemfile": gem}), ["puma", "rails", "sidekiq", "sinatra"])

    def test_ruby_traps(self):
        gem = "gem 'sidekiq-cron'\ngem 'rails-controller-testing'\n# gem 'rails'\n"
        self.assertEqual(self.frameworks({"Gemfile": gem}), [])

    def test_php(self):
        cj = json.dumps({"require": {"laravel/framework": "^11", "symfony/framework-bundle": "^7"}})
        self.assertEqual(self.frameworks({"composer.json": cj}), ["laravel", "symfony"])

    def test_php_traps(self):
        cj = json.dumps({"require": ["laravel/framework"], "description": "laravel/framework"})
        self.assertEqual(self.frameworks({"composer.json": cj}), [])
        cj2 = json.dumps({"require-dev": {"laravel/framework": "^11"}, "require": {"laravel/tinker": "1"}})
        self.assertEqual(self.frameworks({"composer.json": cj2}), [])

    def test_rust(self):
        cargo = ('[package]\nname = "x"\n[dependencies]\naxum = "0.7"\n'
                 'actix-web = { version = "4" }\n[dependencies.rocket]\nversion = "0.5"\n')
        self.assertEqual(self.frameworks({"Cargo.toml": cargo}), ["actix-web", "axum", "rocket"])

    def test_rust_traps(self):
        cargo = '[package]\nname = "axum"\n[dependencies]\naxum-extra = "0.9"\n[features]\nrocket = []\n'
        self.assertEqual(self.frameworks({"Cargo.toml": cargo}), [])

    def test_jvm(self):
        pom = ("<project><parent><groupId>org.springframework.boot</groupId>"
               "<artifactId>spring-boot-starter-parent</artifactId></parent></project>")
        self.assertEqual(self.frameworks({"pom.xml": pom}), ["spring-boot"])
        gradle = ('plugins { id("io.quarkus") }\ndependencies {\n'
                  '  implementation("io.ktor:ktor-server-core:2.3.0")\n'
                  '  implementation("io.micronaut:micronaut-http")\n}\n')
        self.assertEqual(self.detect({"build.gradle.kts": gradle}, sub="g")["frameworks"],
                         ["ktor", "micronaut", "quarkus"])

    def test_jvm_spring_plugin_only(self):
        gradle = "plugins {\n  id 'org.springframework.boot' version '3.2.0'\n}\n"
        self.assertEqual(self.frameworks({"build.gradle": gradle}), ["spring-boot"])

    def test_jvm_traps(self):
        gradle = ("// TODO: maybe migrate to spring-boot later\n"
                  "dependencies { implementation 'com.example:quarkusish:1' }\n")
        self.assertEqual(self.frameworks({"build.gradle": gradle}), [])
