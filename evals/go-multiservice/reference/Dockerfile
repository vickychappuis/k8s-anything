# syntax=docker/dockerfile:1
# Go module with two binaries (go.mod; cmd/api, cmd/worker). Generated from the
# k8s-anything go.Dockerfile template. One image per binary:
#   docker build --build-arg MAIN=./cmd/api    -t go-multiservice-api .
#   docker build --build-arg MAIN=./cmd/worker -t go-multiservice-worker .
# The api image also runs the migration Job (`/app migrate`, cmd/api/main.go:33).
ARG GO_VERSION=1.23
FROM golang:${GO_VERSION} AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG MAIN=./cmd/api
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app ${MAIN}

# Static binary (pgx is pure Go, no CGO): distroless/static, no shell.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
USER 10001:10001
# api listens on $PORT (default 8080, cmd/api/main.go:43-46); the worker listens on nothing.
EXPOSE 8080
ENTRYPOINT ["/app"]
