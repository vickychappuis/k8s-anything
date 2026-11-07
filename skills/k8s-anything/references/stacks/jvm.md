# JVM (Java / Kotlin / Scala)

**Detect:** `pom.xml`, `build.gradle(.kts)`, `build.sbt`. Framework: Spring Boot,
Quarkus, Micronaut.

**Build:** prefer the framework's image tooling — Spring Boot
`./mvnw spring-boot:build-image` (Buildpacks) or Jib (`jib:dockerBuild`), Quarkus
container-image extension. Otherwise multi-stage with layered jars.

**Runtime:** JRE (not JDK), e.g. `eclipse-temurin:<lts>-jre`. JVM flags:
`-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError`.

**Health:** Spring Actuator → `/actuator/health/liveness` and `/actuator/health/readiness`
(enable `management.endpoint.health.probes.enabled=true`). Quarkus → `/q/health/live|ready`.

**Startup:** slow — always add a `startupProbe` (e.g. `periodSeconds: 5, failureThreshold: 30`).

**Port:** Spring `8080` (`server.port`), Quarkus `8080`.

**Resources:** `250m / 512Mi` request, `1Gi` limit.
