// Package store is the tiny Postgres layer shared by the api and the worker.
package store

import (
	"context"
	"database/sql"

	_ "github.com/jackc/pgx/v5/stdlib" // registers the "pgx" database/sql driver
)

// Open returns a lazily-connecting pool: no connection is made until first use.
func Open(dsn string) (*sql.DB, error) {
	return sql.Open("pgx", dsn)
}

// Migrate creates the schema. Idempotent.
func Migrate(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS jobs (
		id         BIGSERIAL PRIMARY KEY,
		payload    TEXT NOT NULL,
		created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
		done_at    TIMESTAMPTZ
	)`)
	return err
}
