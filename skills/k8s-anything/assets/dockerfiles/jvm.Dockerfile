# syntax=docker/dockerfile:1
# PORT/EXPOSE default to 8080: set both to the port found in Discover.
# JVM fallback (Maven wrapper). Prefer the framework's own image tooling first:
# Spring Boot `./mvnw spring-boot:build-image` or Jib; Quarkus container-image.
# Gradle: replace the build line with `./gradlew --no-daemon bootJar` and the jar path.
ARG JAVA_VERSION=21
FROM eclipse-temurin:${JAVA_VERSION}-jdk AS build
WORKDIR /src
COPY . .
RUN ./mvnw -q -DskipTests package && cp target/*.jar /app.jar

FROM eclipse-temurin:${JAVA_VERSION}-jre
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app.jar /app/app.jar
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
