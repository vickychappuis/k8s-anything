# Go

**Detect:** `go.mod`. Entry points: `main.go` or `cmd/*/main.go` — each is a candidate
service and gets its own image (`--build-arg MAIN=./cmd/<name>`).

**Template:** `assets/dockerfiles/go.Dockerfile` (static binary, distroless, UID 10001).
Needs CGO? Switch to `gcr.io/distroless/base-debian12` and drop `CGO_ENABLED=0`.

**Port:** `http.ListenAndServe`, `:8080` literals, `PORT` env. `":"+port` binds all
interfaces; `"localhost:8080"` doesn't.

**Signals:** look for `signal.NotifyContext` + `srv.Shutdown`. Absent → in-flight
requests drop on rollout; flag it (preStop sleep only partly helps).

**Resources:** `50m / 64Mi`, limit `256Mi`; `GOMEMLIMIT` ≈ 90% of the limit.
