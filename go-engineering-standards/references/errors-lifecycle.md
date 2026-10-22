# Errors, resources, retries, configuration, shutdown

Load when touching error handling, `defer`/`Close`, retries, timeouts, configuration, graceful shutdown, or `main` wiring. Rules `E1`–`E4` and `R4` in SKILL.md are the summary.

## 1. Errors are values (E1)

- Return errors for expected failures. `panic` only for programmer bugs or deliberate, documented init failure. Libraries never `os.Exit` or `log.Fatal`.
- Add context once per boundary: `fmt.Errorf("load account %q: %w", id, err)`. Use `%w` when callers may inspect the cause; `%v` when deliberately hiding it (security boundary, unstable third-party type).
- Match with `errors.Is`, `errors.As`, or `errors.AsType[T]` (Go 1.26+). Never by message text; standard-library messages change (JSON errors did in 1.27).
- Wrap error **values**, not pointers to value-type errors. Go 1.27 vet flags `%w` with `*E` when `E` implements `error`.
- Export sentinels (`ErrNotFound`, `ErrClosed`) or typed errors only for cases callers branch on.
- Document partial results. Default: on error, return the zero value.
- `errors.Join` for independent failures (operation + cleanup). Callers matching with `Is` will match any member.
- `_ = f()` on a material error needs a comment saying why it is safe.

```go
func Load(ctx context.Context, s Store, id string) (Record, error) {
	rec, err := s.Find(ctx, id)
	if err != nil {
		return Record{}, fmt.Errorf("find record %q: %w", id, err)
	}
	return rec, nil
}
```

**Log or return, not both (E3).** Lower layers return context-rich errors. The operation boundary (HTTP handler, CLI command, worker supervisor) logs once, with trace IDs, and decides the response.

### Typed nil

An interface is nil only when both its type and value are nil. Returning a nil `*MyErr` through an `error` result yields a **non-nil** error.

```go
// BAD: callers see err != nil even on success.
func validate(in Input) error {
	var verr *ValidationError
	if in.Name == "" {
		verr = &ValidationError{Field: "name"}
	}
	return verr // typed nil when valid
}

// GOOD: return the untyped nil explicitly on success.
func validate(in Input) error {
	if in.Name == "" {
		return &ValidationError{Field: "name"}
	}
	return nil
}
```

Declare helper results as `error`, not concrete error pointers, unless there is a reason.

## 2. Resources and `defer` (E2)

- `defer x.Close()` immediately after successful acquisition, in the scope that owns `x`. Never close what a goroutine still uses; join first.
- Check errors from `Close` on writers, `Flush`, `Sync`, `Commit`, `Rename`. Read-side `Close` errors are usually safe to ignore; say so.
- In loops, move per-item acquire/close (and `cancel()`) into a helper so resources are released each iteration, not at function exit.
- Deferred call **arguments** are evaluated at the `defer` statement. Use a closure for late evaluation or to modify a named error result.

```go
// WriteFile writes data to path, truncating it. It is NOT atomic and NOT
// crash-durable; see WriteFileAtomic for replacement semantics.
func WriteFile(path string, data []byte) (err error) {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create %q: %w", path, err)
	}
	defer func() {
		if cerr := f.Close(); cerr != nil {
			err = errors.Join(err, fmt.Errorf("close %q: %w", path, cerr))
		}
	}()
	if _, err := f.Write(data); err != nil {
		return fmt.Errorf("write %q: %w", path, err)
	}
	return nil
}
```

Atomic replace (POSIX semantics; verify for the target OS and filesystem):

```go
// WriteFileAtomic replaces path with data so readers see either the old or
// the new contents. On success the data and the rename are synced to disk.
func WriteFileAtomic(path string, data []byte, perm os.FileMode) (err error) {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".tmp-"+filepath.Base(path)+"-*")
	if err != nil {
		return fmt.Errorf("create temp in %q: %w", dir, err)
	}
	tmpName := tmp.Name()
	defer func() {
		if err != nil {
			_ = tmp.Close()          // best effort; primary error already set
			_ = os.Remove(tmpName)   // best effort cleanup of the temp file
		}
	}()

	if _, err = tmp.Write(data); err != nil {
		return fmt.Errorf("write temp: %w", err)
	}
	if err = tmp.Chmod(perm); err != nil {
		return fmt.Errorf("chmod temp: %w", err)
	}
	if err = tmp.Sync(); err != nil {
		return fmt.Errorf("sync temp: %w", err)
	}
	if err = tmp.Close(); err != nil {
		return fmt.Errorf("close temp: %w", err)
	}
	if err = os.Rename(tmpName, path); err != nil {
		return fmt.Errorf("rename to %q: %w", path, err)
	}
	d, err := os.Open(dir)
	if err != nil {
		return fmt.Errorf("open dir %q for sync: %w", dir, err)
	}
	defer d.Close()
	if err = d.Sync(); err != nil {
		return fmt.Errorf("sync dir %q: %w", dir, err)
	}
	return nil
}
```

Directory `Sync` is not supported everywhere (notably Windows); handle per platform with build tags rather than ignoring the error globally.

Durability vocabulary — keep these distinct in docs and reports: written to a buffer → flushed to the OS → synced to disk → committed in a DB transaction → replicated.

## 3. Transactions

- One owner per transaction. Roll back on every failure path; commit once; return the commit error.
- `defer tx.Rollback()` after `BeginTx` is fine: after a successful `Commit`, `Rollback` returns `sql.ErrTxDone`, which you ignore deliberately.
- Never share a `*sql.Tx` across goroutines unless the driver documents it.

## 4. Retries, timeouts, idempotency (E4)

- Transient is not the same as safe to retry. Ask: is the operation idempotent? Could the first attempt have committed? Is there a dedup key?
- Bound attempts or total time. Exponential backoff with jitter. Wait with a timer inside `select` on `ctx.Done()`.
- Honor `Retry-After` and rate limits. Never auto-retry auth or validation failures.
- Request bodies must be replayable (`GetBody`) before retrying HTTP requests.
- Distinguish: connection failure, timeout, cancellation, non-2xx response, partial write.
- Batches: define partial success, requeue, poison-message handling, dead-letter policy.

## 5. Configuration

- Parse and validate at startup; fail with an actionable error. Do not mask invalid values with silent defaults.
- Document precedence (flags, env, file), units (`time.Duration`, bytes), and ranges. Reject negatives and overflows.
- Print effective config with secrets redacted.

## 6. Graceful shutdown

One coordinator in `main`:

1. Receive the signal (`signal.NotifyContext`; in 1.26+ `context.Cause` names the signal).
2. Stop accepting new work (close listeners, stop consumers).
3. Cancel children and drain queues in dependency order.
4. Wait with a bounded grace period (`http.Server.Shutdown(ctx)`); fall back to `Close` on timeout.
5. Flush and close resources; report every error.
6. Exit with a meaningful status.

- `Server.Shutdown` drains; `Server.Close` aborts. Test the timeout fallback.
- Document whether `Close` is idempotent. Use `sync.Once` when several callers may close, without hiding invalid state transitions.
- `main` must not return while owned goroutines still log, write, or use clients.

```go
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := loadConfig()
	if err != nil {
		return fmt.Errorf("config: %w", err)
	}
	srv := &http.Server{
		Addr:              cfg.Addr,
		Handler:           newHandler(cfg),
		ReadHeaderTimeout: 5 * time.Second,
	}

	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()

	select {
	case err := <-errc:
		return fmt.Errorf("listen: %w", err) // never http.ErrServerClosed here
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return errors.Join(fmt.Errorf("shutdown: %w", err), srv.Close())
	}
	if err := <-errc; err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve: %w", err)
	}
	return nil
}
```

`context.Background()` is correct for `shutdownCtx`: the signal context is already cancelled, and shutdown needs its own fresh deadline.
