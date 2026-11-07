// Command worker polls the jobs table and marks pending jobs as done.
// It serves no HTTP port.
package main

import (
	"context"
	"database/sql"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.com/go-multiservice/internal/store"
)

func main() {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		log.Fatal("DATABASE_URL is required")
	}
	interval := 2 * time.Second
	if v := os.Getenv("POLL_INTERVAL"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			log.Fatalf("POLL_INTERVAL: %v", err)
		}
		interval = d
	}
	db, err := store.Open(dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	log.Printf("worker polling every %s", interval)
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			log.Print("worker stopping")
			return
		case <-t.C:
			n, err := processBatch(ctx, db)
			if err != nil {
				// Database down or schema not migrated yet: log and retry next tick.
				log.Printf("poll: %v", err)
				continue
			}
			if n > 0 {
				log.Printf("processed %d job(s)", n)
			}
		}
	}
}

func processBatch(ctx context.Context, db *sql.DB) (int64, error) {
	res, err := db.ExecContext(ctx, `UPDATE jobs SET done_at = now()
		WHERE id IN (SELECT id FROM jobs WHERE done_at IS NULL
		             ORDER BY id LIMIT 10 FOR UPDATE SKIP LOCKED)`)
	if err != nil {
		return 0, err
	}
	return res.RowsAffected()
}
