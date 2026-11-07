# Go

**Detect:** `go.mod`. Entry points: `main.go` or `cmd/*/main.go` (each is a candidate service).

**Build:** `CGO_ENABLED=0 go build -trimpath -ldflags="-s -w"`; cache `go mod download`
layer. Runtime `gcr.io/distroless/static-debian12:nonroot` (or `scratch` + CA certs).

**Port:** look for `http.ListenAndServe`, `:8080` literals, `PORT` env.

**Signals:** check for `signal.NotifyContext` / `srv.Shutdown`. If absent, flag:
in-flight requests drop on rollout.

**Resources:** `50m / 64Mi` request, `256Mi` limit. Consider `GOMEMLIMIT` ≈ 90% of limit.
