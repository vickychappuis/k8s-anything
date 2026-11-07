// Package store is the tiny Postgres layer shared by the api and the worker.
package store

import (
	"context"
	"database/sql"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib" // registers the "pgx" database/sql driver
)

// Open returns a lazily-connecting pool: no connection is made until first use.
// The pool is bounded so that replicas x MaxOpenConns stays well under Postgres'
// max_connections (100 by default), and connections are recycled so a database
// failover or a rotated password is picked up.
func Open(dsn string) (*sql.DB, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)
	db.SetConnMaxIdleTime(5 * time.Minute)
	return db, nil
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
