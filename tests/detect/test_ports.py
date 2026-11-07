"""Dockerfile EXPOSE and docker-compose port syntaxes."""
from .support import DetectCase


class DockerfileExpose(DetectCase):
    def expose(self, dockerfile, name="Dockerfile"):
        out = self.detect({name: dockerfile})
        self.assertEqual(out["dockerfiles"], [name])
        return out["expose_ports"]

    def test_protocol_suffix(self):
        self.assertEqual(self.expose("FROM x\nEXPOSE 8080/tcp\n"), ["8080"])

    def test_multiple_and_repeated(self):
        df = "FROM x\nEXPOSE 80 443/tcp 53/udp\nexpose 9090\n"
        self.assertEqual(self.expose(df), ["443", "53", "80", "9090"])

    def test_variables(self):
        df = "FROM x\nARG PORT=3000\nEXPOSE $PORT ${OTHER}\n"
        self.assertEqual(self.expose(df), ["$PORT", "${OTHER}"])

    def test_range_comment_and_continuation(self):
        df = "FROM x\n# EXPOSE 1111\nEXPOSE 7000-7002 \\\n    8000  # trailing\n"
        self.assertEqual(self.expose(df), ["7000-7002", "8000"])

    def test_dockerfile_name_variants(self):
        files = {"Dockerfile": "EXPOSE 1\n", "Containerfile": "EXPOSE 2\n",
                 "Dockerfile.worker": "EXPOSE 3\n", "api.Dockerfile": "EXPOSE 4\n",
                 "Dockerfile.md": "not a dockerfile EXPOSE 5\n", "docs/Dockerfile.txt": "x"}
        out = self.detect(files)
        self.assertEqual(sorted(out["dockerfiles"]),
                         ["Containerfile", "Dockerfile", "Dockerfile.worker", "api.Dockerfile"])
        self.assertEqual(out["expose_ports"], ["1", "2", "3", "4"])

    def test_crlf(self):
        self.assertEqual(self.expose("FROM x\r\nEXPOSE 8080\r\nEXPOSE 9090/tcp\r\n"), ["8080", "9090"])


class ComposePorts(DetectCase):
    def compose(self, body, name="docker-compose.yml"):
        out = self.detect({name: body})
        self.assertEqual(out["compose_files"], [name])
        return out

    def test_short_syntax(self):
        body = 'services:\n  web:\n    image: x\n    ports:\n      - 8080\n      - "3000:3000"\n      - 5432:5432\n'
        out = self.compose(body)
        self.assertEqual(out["compose_services"], ["web"])
        self.assertEqual(out["compose_container_ports"], ["3000", "5432", "8080"])

    def test_quoted_with_host_ip_and_protocol(self):
        body = ("services:\n  web:\n    ports:\n      - \"127.0.0.1:8001:8000/tcp\"\n"
                "      - '[::1]:9001:9000'\n      - 0.0.0.0:53:53/udp\n")
        self.assertEqual(self.compose(body)["compose_container_ports"], ["53", "8000", "9000"])

    def test_ranges(self):
        body = 'services:\n  web:\n    ports:\n      - "6000-6005:7000-7005"\n      - 9000-9001\n'
        self.assertEqual(self.compose(body)["compose_container_ports"], ["7000-7005", "9000-9001"])

    def test_variable_host_side(self):
        body = ('services:\n  web:\n    ports:\n      - "${WEB_PORT:-8080}:80"\n'
                '      - ${API_PORT}:3000\n      - "${ONLY_VAR:-5000}"\n')
        self.assertEqual(self.compose(body)["compose_container_ports"], ["3000", "80"])

    def test_long_syntax(self):
        body = ("services:\n  web:\n    ports:\n      - target: 80\n        published: 8080\n"
                "        protocol: tcp\n      - published: \"9443\"\n        target: \"443\"\n"
                "        mode: host\n    environment:\n      target: 1234\n")
        self.assertEqual(self.compose(body)["compose_container_ports"], ["443", "80"])

    def test_expose(self):
        body = 'services:\n  api:\n    expose:\n      - "3000"\n      - 4000\n  db:\n    expose: ["5432"]\n'
        out = self.compose(body)
        self.assertEqual(out["compose_services"], ["api", "db"])
        self.assertEqual(out["compose_container_ports"], ["3000", "4000", "5432"])

    def test_flow_list(self):
        body = 'services:\n  web:\n    ports: ["80:8080", "443:8443"]\n'
        self.assertEqual(self.compose(body)["compose_container_ports"], ["8080", "8443"])

    def test_comments_anchors_and_other_sections(self):
        body = ("x-base: &base\n  ports:\n    - \"1111:1111\"\n"
                "services:  # the services\n"
                "  # a comment at service indent\n"
                "  web: &web\n    <<: *base\n    ports:\n      - \"80:8000\" # web port\n"
                "    command: [\"sh\", \"-c\", \"echo 1:2\"]\n"
                "  \"quoted\":\n    image: y\n"
                "volumes:\n  data:\n")
        out = self.compose(body)
        self.assertEqual(out["compose_services"], ["quoted", "web"])
        self.assertEqual(out["compose_container_ports"], ["8000"])

    def test_four_space_indent_and_crlf(self):
        body = "services:\r\n    web:\r\n        ports:\r\n            - \"80:5000\"\r\n    redis:\r\n        image: redis\r\n"
        out = self.compose(body, name="compose.yaml")
        self.assertEqual(out["compose_services"], ["redis", "web"])
        self.assertEqual(out["compose_container_ports"], ["5000"])

    def test_compose_name_variants(self):
        files = {"compose.yml": "services:\n  a:\n    image: x\n",
                 "docker-compose.override.yaml": "services:\n  b:\n    image: x\n",
                 "compose.dev.yaml": "services:\n  c:\n    image: x\n",
                 "my-compose.yml": "services:\n  d:\n    image: x\n"}
        out = self.detect(files)
        self.assertEqual(sorted(out["compose_files"]),
                         ["compose.dev.yaml", "compose.yml", "docker-compose.override.yaml"])
        self.assertEqual(out["compose_services"], ["a", "b", "c"])
