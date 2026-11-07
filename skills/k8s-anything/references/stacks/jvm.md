# JVM (Java / Kotlin / Scala)

**Detect:** `pom.xml`, `build.gradle(.kts)`, `build.sbt`. Frameworks: Spring Boot,
Quarkus, Micronaut, Ktor.

**Build:** prefer framework tooling — Spring Boot `./mvnw spring-boot:build-image`
(Buildpacks) or Jib; Quarkus container-image extension. Fallback:
`assets/dockerfiles/jvm.Dockerfile` (JRE runtime, UID 10001).

**Runtime:** `JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"`.
Embedded Tomcat writes to `/tmp` — covered by the scaffold's `emptyDir`.

**Health:** Spring Actuator → readiness `/actuator/health/readiness`, liveness
`/actuator/health/liveness` (`management.endpoint.health.probes.enabled=true`; on by
default when Boot detects Kubernetes). The liveness group doesn't check dependencies,
so an HTTP liveness probe is fine here. Quarkus → `/q/health/ready`, `/q/health/live`.

**Startup:** slow — startupProbe `periodSeconds: 5`, `failureThreshold: 30`+.

**Port:** Spring `8080` (`server.port`), Quarkus `8080`.

**Resources:** `250m / 512Mi`, limit `1Gi`.
