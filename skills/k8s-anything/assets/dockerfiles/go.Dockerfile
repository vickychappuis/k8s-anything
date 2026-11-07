# syntax=docker/dockerfile:1
# PORT/EXPOSE default to 8080: set both to the port found in Discover.
# Go service. MAIN is the package to build (e.g. ./cmd/api); one image per binary.
ARG GO_VERSION=1.23
FROM golang:${GO_VERSION} AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
ARG MAIN=.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app ${MAIN}

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app"]
